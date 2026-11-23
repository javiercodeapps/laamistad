from odoo import models, fields, api, _, SUPERUSER_ID
from odoo.tools import float_compare
from datetime import datetime, timedelta
from odoo.exceptions import UserError, ValidationError
import time
import re
import textwrap
import logging
_logger = logging.getLogger(__name__)
# Bloquear autozorizaciones del encargado cuando el pedido esta enviado y facturado 
# Bloquear autizacion de caja cerrada
# 


def _mp_link_reference_key(value):
    """Normaliza una referencia externa de Mercado Pago para compararla.

    Mercado Pago devuelve la referencia tal cual se envió, pero puede llegar
    envuelta en comillas (repr/JSON) o con espacios distintos; se comparan los
    nombres de las órdenes sin importar mayúsculas, comillas ni espacios.
    """
    names = [n.strip().strip('"\'').strip().upper()
             for n in str(value or '').split(',')]
    return frozenset(n for n in names if n)


class SaleOrderQR(models.Model):
    _inherit = "sale.order"

    ticket_num = fields.Char(string="Ticket Number", size=4)
    seller = fields.Char(string="Seller", size=2)
    scale = fields.Char(string="Scale Number", size=3)
    total_items = fields.Integer(string="Total Items", default=0)
    payment_provider = fields.Many2one('payment.transaction', copy=False)
    caja_id = fields.Many2one('account.cashbox.session', string="Sesión de Caja")
    is_admin = fields.Boolean(default=False, store=True,tracking=True)
    mp_link = fields.Char(string="MP Link", copy=False)

    def write(self, vals):
        res = super().write(vals)
        # Mientras el pedido está en presupuesto por un MP QR, cualquier cambio
        # en las líneas de producto tiene que recalcular el descuento: si no,
        # las líneas de descuento (y el importe del QR) quedan con el valor
        # viejo. Sólo afecta a pedidos con un QR generado y se protege con un
        # flag de contexto para no reentrar desde apply_discount().
        if 'order_line' in vals and not self.env.context.get('mp_qr_no_discount_recalc'):
            orders = self.filtered(
                lambda o: o.state in ('draft', 'sent') and o._mp_qr_discount_applied())
            if orders:
                try:
                    orders.with_context(
                        mp_qr_no_discount_recalc=True)._mp_qr_recalc_discount()
                except Exception:
                    # Un problema al recalcular NO puede impedir guardar las
                    # líneas: se registra y el descuento se recalcula al
                    # generar/refrescar el QR de todas formas.
                    _logger.exception('MP QR: no se pudo recalcular el descuento '
                                      'tras cambiar las líneas del pedido %s',
                                      ', '.join(orders.mapped('name')))
        return res

    ## Parses QR data and creates a Sale Order
    @api.model
    def create_sale_order_from_qr(self, qr_code, payment_type):
        lines = qr_code.strip().split("\n")

        # Extract Header
        header = lines[0]
        date_str, time_str, ticket_num, seller, scale, total_items = self._parse_header(header)

        # Extract Products
        product_lines=[]
        for line in lines[1:]:
            if '-' in line:
                continue
            if '/' in line:
                continue
            product_lines = product_lines +  textwrap.fill(line,13).split()
        order_lines = self._parse_products(product_lines)

        # Convert date to YYYY-MM-DD format
        day, month, year = date_str.split("/")
        year = "20" + year  # Convert "24" to "2024"
        formatted_date = f"{year}-{month}-{day}"
        # Ensure time is properly formatted
        formatted_time = time_str[:2] + ":" + time_str[3:]
        # Combine into final datetime string
        datetime_str = f"{formatted_date} {formatted_time}"
        # Parse into datetime object
        try:
            date_order = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
            date_order = date_order + timedelta(hours=3)
        except:
            date_order = fields.datetime.now()

        # Adjust the datetime manually for GMT -3
        # Subtract 3 hours to shift to GMT -3
        date_order = date_order + timedelta(hours=3)

        # Set payment_term_id to 'Pago inmediato'
        payment_term = self.env['account.payment.term'].search([('name', '=', 'Pago inmediato')], limit=1)
        if not payment_term:
            raise UserError("No se econtró el Término de pago 'Pago inmediato'.")

        # Find the Sale Order Type where the name contains 'Efectivo' or 'Tarjeta' or 'Mercado Pago' or 'CC'
        #sale_order_type = self.env["sale.order.type"].search([("name", "ilike", payment_type)], limit=1)
        #sale_order_type = self.env["sale.order.type"].search([("name", "ilike", payment_type)], limit=1)
        sale_order_type = self.env["sale.order.type"].search([("name", "ilike", payment_type),("company_id","=",self.env.company.id)], limit=1)
        if not sale_order_type:
            raise UserError(f"No se encontró el Tipos de pedido de venta '{payment_type}' %s. " % self.env.company.id)

        caja = self.env['account.cashbox.session'].search([('state','=','opened'),])
        # Create Sale Order
        order = self.create({
            "partner_id": 7, # Consumidor Final Anónimo
            "date_order": date_order,
            "order_line": [(0, 0, line) for line in order_lines],
            "ticket_num": ticket_num,
            "seller": seller,
            "scale": scale,
            "total_items": total_items,
            "payment_term_id": payment_term.id,
            "caja_id":caja.id,
        })
        order.write({"type_id": sale_order_type.id})
        return order.id

    def _parse_header(self, header):
        try:
            # Ensure we correctly handle each section of the header
            date_str = header[:8]  # Fecha (dd/mm/yy)
            date_str = re.sub('-','/',date_str)
            time_str = header[8:13]  # Hora (hh:mm)
            time_str = re.sub('Ñ',':',time_str)
            ticket_num = header[13:17]  # Ticket Number (4 characters after time)
            seller = header[17:19]  # Seller (1 character)
            scale = header[19:21]  # Scale Number (3 characters)
            total_items = int(header[21:23])  # Item Count (2 digits)

            # Return the parsed values
            return date_str, time_str, ticket_num, seller, scale, total_items

        except Exception as e:
            # Raise a ValueError with the original header and exception message for better debugging
            raise UserError(f"Error parsing header: {header}, exception: {e}")

    # Parse product lines using the barcode nomenclature (units or weight-based) and create sale order lines
    def _parse_products(self, product_lines):
        order_lines = []
        for product in product_lines:
            ean13 = product.strip()

            # Verifying that the barcode has the correct length and format
            if len(ean13) == 13:
                barcode_type = ean13[0]  # First digit determines if it's a weighted or unit product
                barcode     = ean13[0:7]  # Internal product reference (next 6 digits)
                product_ref = int(ean13[1:7])  # Internal product reference (next 6 digits)
                quantity_or_weight = ean13[7:12]  # Weight (for weighted products) or quantity (for unit products)
                validator = ean13[12]  # Code validator (not used for lookup, but could be validated)

                # Search for the product by internal reference
                #product_obj = self.env["product.product"].search([("default_code", "=", product_ref)], limit=1)
                product_obj = self.env["product.product"].search([("barcode", "=", barcode)], limit=1)

                if product_obj:
                    if barcode_type == "3":  # If it's a unit-based product
                        uom = product_obj.uom_id  # Default unit of measure
                        order_lines.append({
                            "product_id": product_obj.id,
                            "name": product_obj.name,
                            "product_uom_qty": int(quantity_or_weight),  # Quantity is directly the value in barcode
                            "product_uom": uom.id,
                            "price_unit": product_obj.lst_price,
                        })
                    elif barcode_type == "2":  # If it's a weight-based product
                        # Convert the quantity (NNDDD) into a weight in kilograms
                        weight = float(quantity_or_weight[:2] + '.' + quantity_or_weight[2:])  # Example: '01500' => 1.500
                        #uom = self.env.ref('uom.product_uom_kgm')  # Assuming the weight UOM is kg
                        uom = self.env.ref('__custom__.uom.product_uom_kgm_uni')  # Assuming the weight UOM is kg
                        order_lines.append({
                            "product_id": product_obj.id,
                            "name": product_obj.name,
                            "product_uom_qty": weight,  # Weight is used directly
                            "product_uom": uom.id,
                            "price_unit": product_obj.lst_price,
                        })
                    else:
                        raise UserError(f"Unknown barcode type for product: {ean13}")
                else:
                    raise UserError(f"Producto con la referencia {product_ref} no encontrado para el código de barras {ean13}.")
            else:
                raise UserError(f"Código de barras {ean13} no tiene el formato correcto (debe tener 13 dígitos).")

        return order_lines

########################
# Creamos una accion unica y le pasamos por context y tipo de pago, tiene que existir en los sale_order_type
    def action_confirm_type(self,efectivo=None):
        caja = self.env['account.cashbox.session'].search([('state','=','opened'),])
        context = self.env.context
        # Find the Sale Order Type where the name contains 'Efectivo' or 'Tarjeta' or 'Mercado Pago' or 'CC'
        selected_payment_type = context.get('payment_type')
        label = context.get('label')
        if efectivo:
            efectivo = float(efectivo)
        # Monto en efectivo de un pago múltiple: viene del popup ('text') o del
        # campo 'efectivo' cargado directamente en el formulario del pedido.
        efectivo_amount = float(efectivo or 0) or (self.efectivo or 0)
        payment_type = selected_payment_type
        if efectivo and efectivo > 0:
            # El popup de efectivo antes pisaba el medio elegido con 'Multiple',
            # por lo que su botón 'MP QR' nunca llegaba a generar el QR.
            payment_type = 'MP QR' if selected_payment_type == 'MP QR' else 'Multiple'
        if payment_type == 'MP':
            popup = self.env['scan_qr.popup.confirmation']
            action = popup.show_mp(self, 'Selccion el metodo a utilizar', 'action_confirm_type')
            return action

        if payment_type == 'Multiple' and not efectivo:
            popup = self.env['scan_qr.popup.confirmation']
            action = popup.show_efectivo(self, 'Ingreso el monto en efectivo y seleccione el otro metodo de pago <h3>Total: %s</h3>' % self.amount_total, 'action_confirm_type')
            return action

        # Si hay un QR pendiente y se va a finalizar con OTRO medio de pago, lo
        # cancelamos: un IPN tardío no debe confirmar/facturar dos veces.
        if payment_type != 'MP QR':
            qr_discount_applied = self._mp_qr_discount_applied()
            self._mp_qr_cancel_pending('Se eligió el medio de pago %s' % payment_type)
            if qr_discount_applied:
                # Al generar el QR se ejecutó apply_discount() para que el
                # importe del código fuera el definitivo. apply_discount() NO
                # es idempotente: hay que quitar esas líneas para que el nuevo
                # medio recalcule el descuento con SU tipo de pedido. Si no,
                # se descuenta dos veces (y puede dividir por cero).
                self._mp_qr_reset_discount()

        sale_order_type = self.env["sale.order.type"].search([("name", "ilike", payment_type),("company_id","=",self.company_id.id)], limit=1)
        if self.state == 'sale':
            _logger.info('Procesando pago')
            # No pisar el tipo del pedido con el de 'MP Link' antes de
            # prepararlo: si ya está facturado como 'CTACTE Factura',
            # _mp_link_prepare_order debe reconocerlo para no cambiarlo (ni
            # devolverlo a 'Presupuesto enviado'); si no lo está, es ese mismo
            # método el que lo pasa a CTACTE.
            if sale_order_type and payment_type != 'MP Link':
                self.type_id = sale_order_type.id
            if payment_type == 'MP QR':
                # Pedido ya confirmado/facturado por otro medio: se genera el QR,
                # pero al acreditarse NO se vuelve a facturar.
                self.pay_mp_qr(self.efectivo or 0)
                return self.pay_mp_qr_wizard()
            if payment_type == 'MP Link':
                # Vamos a verificar si la orden tiene un link activo antes de generar uno nuevo
                if self.mp_link:
                    # Verificamos si el link sigue vigente
                    info = self._mp_link_current_link_info()
                    if info:
                        expiration = fields.Datetime.context_timestamp(self, info['expiration'])
                        raise UserError(_('El último link generado sigue vigente hasta el %s. '
                                          'No se generó uno nuevo.') % expiration.strftime('%d/%m/%Y %H:%M'))
                    return self.action_mp_link_regenerate()
                # Cuando generamos un link de pago la orden la dejamos con el
                # tipo CTACTE (para que la caja la vea como cuenta corriente
                # pendiente) y le agregamos los tags CTACTE y MP LINK. Si ya
                # está como 'CTACTE Factura' no se le toca nada: solo se le
                # agrega el tag MP LINK.
                self._mp_link_prepare_order()
                if not self._mp_link_is_ctacte_factura():
                    self.state = 'sent'
                    if not self.caja_id:
                        self.caja_id = caja.id
                    self.date_order = fields.datetime.now()
                return self._mp_link_generate()
            for moves in self.invoice_ids:
                pay1=self.pay_multiple(moves,self.type_id.payment_journal_id,self.amount_due)
                _logger.info(pay1)
                self.reconciliar_venta(moves,[pay1])
            return True
        tag_id = self.env["crm.tag"].search([('name','=',label)])
        if tag_id:
            self.tag_ids = tag_id.ids 
        if payment_type == 'CTACTE' and 'Consumidor Final' in self.partner_id.name:
            raise UserError('Debe seleccionar un cliente distinto a consumidor final para CTACTE')
        if not sale_order_type:
            raise UserError(f"No se encontró el Tipos de pedido de venta '{payment_type}'.")
        if payment_type == 'MP Link':
            # Igual que en el flujo de pedidos ya confirmados: el pedido queda
            # como CTACTE con los tags CTACTE y MP LINK (o solo con el tag
            # MP LINK si ya está facturado como 'CTACTE Factura'), y recién al
            # cobrarse el link pasa al tipo MP Link.
            self._mp_link_prepare_order()
            if not self._mp_link_is_ctacte_factura():
                self.state = 'sent'
                if not self.caja_id:
                    self.caja_id = caja.id
                self.date_order = fields.datetime.now()
            self.env.cr.commit()
            return self._mp_link_generate()
        _logger.info('%s %s %s %s' % (payment_type,efectivo,context.get('payment_type'),sale_order_type ) )
        self.type_id=sale_order_type.id
        self.env.cr.commit()
        if payment_type == 'MP QR':
            # MP QR NO confirma ni factura acá: el pedido se mantiene en
            # PRESUPUESTO (draft) y sin factura. Recién cuando Mercado Pago
            # acredita el pago se confirma el pedido y se emite la factura.
            return self._mp_qr_start(caja, efectivo_amount)
        if payment_type == 'CTACTE':
            tag_id = self.env["crm.tag"].search([('name','=','CTACTE')])
            self.tag_ids = tag_id.ids 
            self.state = 'sent'
            if not self.caja_id:
                self.caja_id = caja.id
            self.date_order = fields.datetime.now()
           #self.sale_discount = 0
           #self.sale_with_discount = 0
           #self.sale_discount_percent = 0
        else:
            if self.type_id.name == 'Efectivo':
                self.apply_redondeo()
                if abs(self.redondeo) > 1000:
                    raise UserError('No puede aplicar un redondeo mayor a 1.000 (%s) ' % self.redondeo)
            self.apply_discount()
            _logger.info('Desspues de confirmar %s %s %s' % (payment_type,efectivo,context.get('payment_type') ) )
            if not self.caja_id:
                self.caja_id = caja.id
            self.action_confirm()
            self.is_admin = False
            if payment_type != 'CTACTE Factura':
                for moves in self.invoice_ids:
                    if self.type_id.name != 'Efectivo' and self.efectivo > 0:
                        sale_efectivo = self.env["sale.order.type"].search([("name", "ilike", 'Efectivo'),("company_id","=",self.company_id.id)], limit=1)
                        sale_varios = self.env["sale.order.type"].search([("name", "ilike", 'Varios'),("company_id","=",self.company_id.id)], limit=1)
                        pay1=self.pay_multiple(moves,sale_efectivo.payment_journal_id,self.efectivo)
                        self.reconciliar_venta(moves,[pay1])
                        pay1=self.pay_multiple(moves,self.type_id.payment_journal_id,moves.amount_total - self.efectivo)
                        self.reconciliar_venta(moves,[pay1])
                        self.type_id = sale_varios.id
                    else:
                        pay1=self.pay_multiple(moves,self.type_id.payment_journal_id,moves.amount_total)
                        self.reconciliar_venta(moves,[pay1])
            return 0

    def _mp_link_type(self):
        """Tipo de pedido 'MP Link' de la compañía de la orden.

        Ese tipo es el que aporta el diario de pago del link y el que se le
        asigna al pedido recién cuando el pago se acredita."""
        self.ensure_one()
        return self.env['sale.order.type'].search([
            ('name', 'ilike', 'MP Link'),
            ('company_id', '=', self.company_id.id)], limit=1)

    def _mp_link_ctacte_type(self):
        """Tipo de pedido 'CTACTE' de la compañía de la orden.

        Es el tipo con el que queda guardado el pedido mientras el link está
        pendiente: el resumen de caja toma los pedidos CTACTE como cuenta
        corriente pendiente de cobro. Se busca por nombre exacto para no
        confundirlo con 'CTACTE Factura'."""
        self.ensure_one()
        return self.env['sale.order.type'].search([
            ('name', '=ilike', 'CTACTE'),
            ('company_id', '=', self.company_id.id)], limit=1)

    def _mp_link_is_ctacte_factura(self):
        """Indica si el pedido ya está facturado como cuenta corriente
        ('CTACTE Factura').

        En ese caso no hay que tocarle el tipo, el estado, la caja ni la
        fecha: ya está facturado y la caja lo toma como CTACTE pendiente de
        cobro. Solo corresponde marcarlo con el tag MP LINK."""
        self.ensure_one()
        name = (self.type_id.name or '').upper()
        return 'CTACTE' in name and 'FACTURA' in name

    def _mp_link_tags(self):
        """Tags 'CTACTE' y 'MP LINK' (se crean si no existen)."""
        tags = self.env['crm.tag']
        for name in ('CTACTE', 'MP LINK'):
            tag = self.env['crm.tag'].search([('name', '=ilike', name)], limit=1)
            if not tag:
                tag = self.env['crm.tag'].sudo().create({'name': name})
            tags |= tag
        return tags

    def _mp_link_prepare_order(self):
        """Deja la(s) orden(es) listas para generar el link de pago.

        - Si el pedido todavía no está facturado como cuenta corriente, pasa
          al tipo CTACTE y se le agregan los tags CTACTE y MP LINK.
        - Si ya está facturado como 'CTACTE Factura', no se le cambia nada:
          solo se le agrega el tag MP LINK.

        No se cambia el estado de la orden: eso lo decide cada flujo (alta
        desde el popup o link generado desde el wizard de varias órdenes)."""
        if not self:
            return True
        self._mp_link_check_not_paid()
        tags = self._mp_link_tags()
        mp_link_tag = tags.filtered(lambda t: (t.name or '').upper() == 'MP LINK')
        for order in self:
            if 'Consumidor Final' in (order.partner_id.name or ''):
                raise UserError(_('Debe seleccionar un cliente distinto a consumidor final para CTACTE'))
            if order._mp_link_is_ctacte_factura():
                order.tag_ids = [(4, mp_link_tag.id)]
                continue
            ctacte_type = order._mp_link_ctacte_type()
            if not ctacte_type:
                raise UserError(_("No se encontró el tipo de pedido 'CTACTE' para la compañía %s.")
                                % order.company_id.name)
            order.type_id = ctacte_type.id
            order.tag_ids = [(4, tag.id) for tag in tags]
        return True

    def _mp_link_provider(self):
        """Configuración de Mercado Pago Point de la compañía de la orden."""
        self.ensure_one()
        provider = self.env["payment_mercadopago_point.mercadopago"].sudo().search([
            ('company_id.id', '=', self.company_id.id)], limit=1)
        if not provider:
            raise UserError(_("No se encontró la configuración de Mercado Pago Point "
                              "para la compañía %s.") % self.company_id.name)
        return provider

    def _mp_link_last_history(self, orders=None):
        """Último link generado para las órdenes indicadas (o para esta)."""
        orders = orders or self
        return self.env['payment_mercadopago_point.mercadopago.history'].sudo().search(
            [('sale_id', 'in', orders.ids)], order='date desc', limit=1)

    def _mp_link_reference(self, orders=None):
        """Referencia externa con la que se creó el último link del grupo."""
        orders = orders or self
        history = self._mp_link_last_history(orders)
        if history and history.name:
            return history.name
        return ', '.join(orders.mapped('name'))[:256]

    def _mp_link_related_orders(self):
        """Órdenes que comparten el último link (un link puede agrupar varias)."""
        self.ensure_one()
        history = self._mp_link_last_history(self)
        if history and history.name:
            names = [n.strip().strip('"\'') for n in history.name.split(',') if n.strip()]
            orders = self.env['sale.order'].sudo().search([('name', 'in', names)])
            if orders:
                return orders
        return self

    def _mp_link_current_link_info(self, orders=None):
        """Datos del último link si sigue vigente (vencimiento futuro).

        Devuelve {} si no hay link, si no se conoce su vencimiento o si ya
        venció: en esos casos corresponde generar uno nuevo.
        """
        orders = orders or self
        history = self._mp_link_last_history(orders)
        if not history:
            return {}
        data = history._get_link_data()
        link = data.get('mp_link')
        expiration = history._get_expiration_datetime()
        if not link or not expiration:
            return {}
        if expiration <= fields.Datetime.now():
            return {}
        return {
            'link': link,
            'expiration': expiration,
            'history': history,
        }

    def _mp_link_notify_action(self, message, notif_type='info', reload=False):
        """Acción cliente para mostrar un aviso y, opcionalmente, recargar
        el formulario de la orden."""
        action = {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Mercado Pago'),
                'message': message,
                'type': notif_type,
                'sticky': False,
            },
        }
        if reload:
            action['params']['next'] = {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': self.id,
                'view_mode': 'form',
                'views': [[False, 'form']],
                'target': 'current',
            }
        return action

    def _mp_link_payment_journal(self):
        """Diario con el que se registra el cobro del link.

        El pedido queda guardado como CTACTE hasta que el pago se acredita, así
        que el diario no se toma del tipo del pedido sino del tipo 'MP Link'.
        """
        self.ensure_one()
        journal = self._mp_link_type().payment_journal_id or self.type_id.payment_journal_id
        if not journal:
            raise UserError(_("El tipo de pedido 'MP Link' no tiene configurado el diario de pago."))
        return journal

    def _mp_link_generate_for_orders(self, orders):
        """Genera un único link para el grupo de órdenes y lo guarda en todas."""
        orders = orders.sorted('id')
        if not orders:
            raise UserError(_("Debe seleccionar al menos una orden de venta."))
        provider = orders[:1]._mp_link_provider()
        # El pedido queda como CTACTE (con tags CTACTE y MP LINK) hasta que el
        # link se cobre; si ya está facturado como CTACTE Factura solo se le
        # agrega el tag MP LINK.
        orders._mp_link_prepare_order()
        _logger.info('Generando link MP para las órdenes %s' % orders.mapped('name'))
        mp_link = provider.create_order_link(orders)
        _logger.info('Link de pago: %s' % mp_link)
        orders.sudo().write({'mp_link': mp_link})
        return mp_link

    def _mp_link_generate(self):
        """Genera y guarda el link de pago de Mercado Pago para esta orden.

        Se usa tanto para pedidos en borrador/enviados (tras confirmarlos) como
        para pedidos ya confirmados ('sale'), de modo que elegir 'MP Link'
        siempre genere el link."""
        self.ensure_one()
        self._mp_link_generate_for_orders(self)
        self.env.cr.commit()
        return True

    def action_mp_link_check_payment(self):
        """Comprueba en Mercado Pago si el pago ingresó aunque el callback no
        se haya disparado y, si está aprobado, continúa el proceso
        (factura, registra el pago y notifica)."""
        self.ensure_one()
        orders = self._mp_link_related_orders()
        if orders and all(o.payment_status == 'Paid' for o in orders):
            if len(orders) == 1:
                message = _('La orden %s ya está paga.') % orders.name
            else:
                message = _('Las órdenes %s ya están pagas.') % ', '.join(
                    orders.mapped('name'))
            return self._mp_link_notify_action(message, 'info')
        provider = self._mp_link_provider()
        reference = self._mp_link_reference(orders)
        try:
            payments = provider.search_payments(reference)
        except Exception:
            _logger.exception('No se pudo consultar los pagos del link %s', reference)
            raise UserError(_('No se pudo consultar Mercado Pago. '
                              'Intente nuevamente en unos instantes.'))
        approved = next((p for p in payments if p.get('status') == 'approved'), None)
        if approved:
            processed = self.pay_mp_link({
                'external_reference': reference,
                'payment_id': approved.get('id'),
            })
            if processed:
                return self._mp_link_notify_action(
                    _('El pago de Mercado Pago fue confirmado y se registró correctamente.'),
                    'success', reload=True)
            return self._mp_link_notify_action(
                _('Mercado Pago no confirmó el pago del link o no se pudo '
                  'registrar. Revise el chatter de las órdenes.'),
                'warning', reload=True)
        pending = next((p for p in payments if p.get('status') in (
            'pending', 'in_process', 'authorized')), None)
        if pending:
            return self._mp_link_notify_action(
                _('Mercado Pago informa un pago pendiente (estado: %s). '
                  'Todavía no se registró.') % pending.get('status'),
                'warning', reload=True)
        rejected = next((p for p in payments if p.get('status') == 'rejected'), None)
        if rejected:
            return self._mp_link_notify_action(
                _('Mercado Pago informa que el último pago fue rechazado. '
                  'Puede regenerar el link y volver a intentar.'),
                'danger', reload=True)
        return self._mp_link_notify_action(
            _('No se encontraron pagos en Mercado Pago para el link %s.') % reference,
            'info', reload=True)

    def action_mp_link_regenerate(self):
        """Botón del formulario: regenera el link de pago de Mercado Pago.

        Antes de regenerar verifica en Mercado Pago si el pago ya ingresó
        (por si no llegó el callback) y si el último link sigue vigente.
        Solo genera un link nuevo cuando el anterior venció y no hay pagos.
        """
        self.ensure_one()
        orders = self._mp_link_related_orders()
        if any(o.payment_status == 'Paid' for o in orders):
            raise UserError(_("La orden %s ya está paga; no se regenera el link de pago.") % self.name)
        provider = self._mp_link_provider()
        reference = self._mp_link_reference(orders)
        try:
            payments = provider.search_payments(reference)
        except Exception:
            _logger.exception('No se pudo verificar el pago del link %s', reference)
            raise UserError(_('No se pudo verificar el pago con Mercado Pago. '
                              'No se regeneró el link; intente nuevamente.'))
        approved = next((p for p in payments if p.get('status') == 'approved'), None)
        if approved:
            processed = self.pay_mp_link({
                'external_reference': reference,
                'payment_id': approved.get('id'),
            })
            if processed:
                return self._mp_link_notify_action(
                    _('El pago ya había ingresado en Mercado Pago y se registró '
                      'correctamente. No se regeneró el link.'),
                    'success', reload=True)
            return self._mp_link_notify_action(
                _('Mercado Pago no confirmó el pago del link o no se pudo '
                  'registrar. Revise el chatter de las órdenes.'),
                'warning', reload=True)
        pending = next((p for p in payments if p.get('status') in (
            'pending', 'in_process', 'authorized')), None)
        if pending:
            return self._mp_link_notify_action(
                _('Hay un pago pendiente en Mercado Pago (estado: %s). '
                  'No se regeneró el link para evitar un cobro duplicado.')
                % pending.get('status'), 'warning', reload=True)
        info = self._mp_link_current_link_info(orders)
        if info:
            orders.sudo().write({'mp_link': info['link']})
            expiration = fields.Datetime.context_timestamp(self, info['expiration'])
            return self._mp_link_notify_action(
                _('El último link generado sigue vigente hasta el %s. '
                  'No se generó uno nuevo.')
                % expiration.strftime('%d/%m/%Y %H:%M'),
                'warning', reload=True)
        self._mp_link_generate_for_orders(orders)
        self.env.cr.commit()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'current',
        }

    def pay_mp_qr_wizard(self, tx=None):
        """Abre el QR sólo si la transacción sigue pendiente.

        Si ya se acreditó o se canceló/venció se avisa en lugar de devolver
        ``None`` (que cerraba el diálogo sin explicación)."""
        tx = tx or self.payment_provider
        _logger.info('Abriendo QR 1 %s %s' % (self.payment_status, tx))
        if not tx:
            return self._mp_link_notify_action(
                _('No hay un código QR de Mercado Pago generado para este pedido.'), 'warning')
        if tx.state in ('done', 'authorized'):
            return self._mp_link_notify_action(
                _('El pago del QR de Mercado Pago ya fue registrado.'), 'success', reload=True)
        if tx.state in ('cancel', 'error'):
            return self._mp_link_notify_action(
                _('El QR de Mercado Pago fue cancelado o venció. El pedido sigue en '
                  'presupuesto y sin factura: puede elegir otro medio de pago o '
                  'volver a generar el QR.'), 'warning', reload=True)
        _logger.info('Abriendo QR 2')
        return tx.action_mp_open_qr()

    def pay_mp_qr(self,efectivo=0):
        """Genera la orden QR en Mercado Pago SIN facturar el pedido."""
        self.ensure_one()
        if self.state == 'cancel':
            raise UserError(_('No se puede generar un QR para el pedido cancelado %s.') % self.name)
        if self.payment_status == 'Paid':
            raise UserError(_('El pedido %s ya está pago; no se genera un QR nuevo.') % self.name)
        # Si quedó un QR pendiente (regeneración), se cancela antes de crear otro.
        self._mp_qr_cancel_pending('Se generó un nuevo QR de Mercado Pago', post_message=False)
        transaction_vals = self.prepare_payment_mp_qr(efectivo)
        if not transaction_vals:
            # Sin proveedor no se crea la transacción; el llamador avisa y el
            # pedido sigue en presupuesto, sin factura.
            return False
        wizard_sudo = self.sudo()
        transaction = wizard_sudo.env["payment.transaction"].create(transaction_vals)
        # Enlazar ANTES de consultar Mercado Pago: si la API respondiera 'paid'
        # en el primer GET, el enganche de confirmación debe encontrar el pedido.
        self.payment_provider = transaction.id
        transaction.mp_payment_order_create()
        transaction.mp_payment_order_get()
        _logger.info('Espero que se procese el pago')
        return transaction


    def pay_multiple(self,moves,journal_efectivo,efectivo):
        for rec in moves:
            pay_journal = journal_efectivo
            if pay_journal and rec.state == 'posted' and rec.payment_state in ['not_paid', 'partial']:
                partner_type = 'customer'
                receiptbook = self.env[ 'account.payment.receiptbook'].search([
                                                ('partner_type', '=', partner_type),
                                                ('company_id', '=', rec.company_id.id),
                                      ], limit=1)

                payment_group = rec.env['account.payment.group'].create({
                            'partner_type': partner_type,
                            'partner_id': rec.partner_id.id,
                            'receiptbook_id': receiptbook.id,
                            'to_pay_move_line_ids':[],
                        })

                payment_methods = pay_journal.inbound_payment_method_line_ids.payment_method_id
                payment_type = 'inbound'
                payment_method = payment_methods.filtered(
                    lambda x: x.code == 'manual')
                if not payment_method:
                    raise ValidationError(_(
                        'Pay now journal must have manual method!'))

                caja = self.env['account.cashbox.session'].search([('state','=','opened'),('company_id.id','=',rec.company_id.id)])
                payment_group.payment_ids.create({
                    'payment_group_id': payment_group.id,
                    'payment_type': payment_type,
                    'partner_type': partner_type,
                    'company_id': rec.company_id.id,
                    'partner_id': payment_group.partner_id.id,
                    'amount': abs(efectivo),
                    'journal_id': pay_journal.id,
                    'ref': rec.name,
                    'payment_method_id': payment_method.id,
                    'date': payment_group.payment_date,
                    'cashbox_session_id': caja.id,
                })
                _logger.info('FAC %s' % payment_group.to_pay_move_line_ids)
                payment_group.remove_all()
                payment_group.post()
                return payment_group

    def set_cashbox_session(self):
        caja = self.env['account.cashbox.session'].search([('state','=','opened')])
        payments = self.env['account.payment'].search([
                           ('journal_id', 'in', caja.cashbox_id.journal_ids.ids),
                           ('create_date', '>', caja.opening_date),
                           ('state', '=', 'posted'),
                           ('cashbox_session_id', '=', False),
                           ])
        for payment in payments:
            payment.write({"cashbox_session_id": caja.id})

    def reconciliar_venta(self,invoice_ids,payment_ids):
        aml_obj = self.env['account.move.line']
        for payment in payment_ids:
            for move_line in payment.move_line_ids:
                if move_line.account_type == 'asset_receivable':
                    aml_obj += move_line
        for invoice in invoice_ids:
            for move_line in invoice.open_move_line_ids:
                if move_line.account_type == 'asset_receivable':
                    aml_obj += move_line
        aml_obj.reconcile()  

########################
### REFACTURAR                     
# Pasa la factura a borrador
# Cambia el diario de facturacion a electronica
# Vuelve a confirmar
    def refacturar_pedido(self):
        # Busco facturas
        aml_obj = self.env['account.move.line']
        for invoice in self.invoice_ids:
            if invoice.state=='posted':
                aml_obj = self.env['account.move.line']
                for payment in invoice.payment_group_ids:
                    for move_line in payment.move_line_ids:
                        if move_line.account_type == 'asset_receivable':
                            aml_obj += move_line
    
                invoice.button_draft()
                invoice.button_cancel()
        
        # Diario de factura electronica
        journal = self.env['account.journal'].search([('name','ilike','Ventas electr')])
        #journal = self.type_id.journal_id
        self._create_invoices()
        for invoice in self.invoice_ids:
            if invoice.state=='draft':
                invoice.journal_id = journal.id
                invoice.action_post()
                for move_line in invoice.open_move_line_ids:
                    if move_line.account_type == 'asset_receivable':
                        aml_obj += move_line
        aml_obj.reconcile()  

########################
### PARA LA IMPRESIÓN DE LA FACTURA

    def get_related_invoices(self):
        """Fetches invoices related to the Sale Order."""
        return self.env['account.move'].search([('invoice_origin', '=', self.name), ('move_type', 'in', ['out_invoice', 'out_refund'])])

    def action_print_sale_order_invoice_report(self):
        """Generates the Sale Order report including related invoices."""
        return self.env.ref('scan_qr.action_report_sale_order_with_invoice').report_action(self)

#######################

    def action_add_products_from_qr(self):
        # Abre un asistente para escanear otro QR y agregar productos.
        return {
            "type": "ir.actions.act_window",
            "name": "Scan QR Code",
            "res_model": "scan.qr.wizard",
            "view_mode": "form",
            "views": [[False, "form"]],
            "target": "new",
            "context": {"default_sale_order_id": self.id},
        }

    def _mp_link_check_not_paid(self):
        """Los pedidos ya pagos no pueden incluirse en un link de pago.

        Se controla tanto al abrir el wizard de link múltiple como al generar
        el link desde el popup de un pedido individual, para no cobrar dos
        veces el mismo pedido."""
        paid = self.filtered(lambda o: o.payment_status == 'Paid')
        if paid:
            raise UserError(_("No se puede generar un link de pago para pedidos "
                              "ya pagos. Revise: %s") % ", ".join(paid.mapped('name')))
        return True

    def _mp_link_validate_orders(self):
        """Valida que las órdenes puedan agruparse en un único link de pago MP.

        Se usa tanto al abrir el wizard (validación previa, antes de mostrar la
        lista) como al generar el link. Se aceptan pedidos enviados ('sent') y
        confirmados ('sale'); cualquier otro estado se rechaza, igual que los
        pedidos ya pagos.
        """
        if not self:
            raise UserError(_("Debe seleccionar al menos una orden de venta."))
        invalid_state = self.filtered(lambda o: o.state not in ('sent', 'sale'))
        if invalid_state:
            raise UserError(_("Solo se pueden agrupar pedidos enviados ('Presupuesto enviado') "
                              "o confirmados ('Pedido de venta'). Revise: %s")
                            % ", ".join(invalid_state.mapped('name')))
        self._mp_link_check_not_paid()
        if len(self.partner_id) > 1:
            raise UserError(_("Todas las órdenes deben ser del mismo cliente. "
                              "Clientes encontrados: %s")
                            % ", ".join(self.partner_id.mapped('display_name')))
        partner = self.partner_id
        if 'Consumidor Final' in (partner.name or ''):
            raise UserError(_("No se puede generar un link de pago para un cliente Consumidor Final (%s). "
                              "Debe seleccionar un cliente con nombre.") % partner.display_name)
        if len(self.currency_id) > 1:
            raise UserError(_("Todas las órdenes deben tener la misma moneda."))
        if len(self.company_id) > 1:
            raise UserError(_("Todas las órdenes deben pertenecer a la misma compañía."))
        return self

    def action_mp_link_wizard(self):
        """Abre el wizard para generar un link de pago de Mercado Pago
        con una o varias órdenes seleccionadas (la suma de todas ellas).
        Las órdenes se validan ANTES de abrir el wizard y se pasan por contexto."""
        if not self:
            raise UserError(_("Seleccione al menos una orden de venta."))
        orders = self._mp_link_validate_orders()
        _logger.info('Abriendo wizard Link MP para órdenes %s' % orders.mapped('name'))
        return {
            'name': _("Link de pago Mercado Pago"),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.mp.link.wizard',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {'active_model': 'sale.order', 'active_ids': orders.ids},
        }

    def pay_mp_link(self, data):
        """Procesa el retorno de un link de pago de Mercado Pago.

        El estado del pago NUNCA se toma de los parámetros recibidos (la URL de
        retorno es pública y se puede falsificar): se consulta el pago en la
        API de Mercado Pago y se valida contra las órdenes. Si no se puede
        verificar (sin id de pago, pago inexistente, error de la API, importe o
        referencia que no coinciden) NO se factura.

        Factura las órdenes del external_reference (una o varias separadas por
        coma) y las paga con el diario de pago del tipo de pedido. Cuando quedan
        pagadas avisa en el canal '<código de la compañía> Pagos link'.

        Devuelve True solo si el pago quedó registrado (o ya lo estaba);
        False si no se pudo verificar o no se pudo registrar.
        """
        data = data or {}
        external_reference = data.get('external_reference') or ''
        payment_id = data.get('payment_id') or data.get('collection_id')
        # Se toleran comillas envolventes: a veces el valor llega como repr/JSON
        # ('"S61473, S61047"') en lugar de 'S61473, S61047'
        names = [n.strip().strip('"\'').strip() for n in external_reference.split(',')]
        names = [n for n in names if n]
        if not names:
            _logger.warning('MP link sin external_reference: %s' % data)
            return False
        orders = self.env['sale.order'].sudo().search([('name', 'in', names)])
        if not orders:
            _logger.warning('MP link: no se encontraron órdenes para %s' % external_reference)
            return False
        # Verifico el pago contra la API de Mercado Pago (no confío en los
        # parámetros de la URL, que pueden ser falsificados). Si no se puede
        # verificar, no se procesa nada.
        payment = orders._mp_link_verify_payment(payment_id, external_reference)
        if not payment:
            return False
        _logger.info('MP link: reference=%s payment_id=%s status=%s'
                     % (external_reference, payment_id, payment.get('status')))
        pagadas = self.env['sale.order'].sudo()
        error = False
        try:
            # El link es un ÚNICO pago: un solo savepoint para todas las órdenes
            with self.env.cr.savepoint():
                if orders._mp_link_invoice_and_pay():
                    pagadas = orders
        except Exception:
            error = True
            _logger.exception('MP link: error al facturar/pagar las órdenes %s'
                              % ', '.join(orders.mapped('name')))
            orders.message_post(body='Error al facturar/pagar el pago del link de Mercado Pago. Revise las órdenes.')
        if pagadas:
            pagadas._mp_link_notify_payment(payment_id)
            # El pedido se guardó como CTACTE mientras el link estaba pendiente;
            # una vez cobrado pasa al tipo MP Link (así lo toma la caja).
            mp_link_type = pagadas[:1]._mp_link_type()
            if mp_link_type:
                pagadas.write({"type_id": mp_link_type.id})
            return True
        if error:
            return False
        # No quedaba nada por pagar: si las órdenes ya están pagas, el pago ya
        # estaba registrado (por ejemplo, si se recargó la URL de éxito).
        if all(o.payment_status == 'Paid' for o in orders):
            _logger.info('MP link: el pago %s ya estaba registrado en %s'
                         % (payment_id, ', '.join(orders.mapped('name'))))
            return True
        orders.message_post(body='Mercado Pago: el pago %s está aprobado, pero no se '
                                 'encontraron facturas impagas para registrar el cobro.' % payment_id)
        return False

    def _mp_link_payment_warning(self, message):
        """Deja constancia en el chatter de las órdenes de un pago de Mercado
        Pago que no se pudo verificar o registrar."""
        _logger.warning('MP link: %s' % message)
        for order in self:
            order.message_post(body='Mercado Pago: %s' % message)

    def _mp_link_verify_payment(self, payment_id, external_reference=None):
        """Consulta el pago en Mercado Pago y lo valida contra estas órdenes.

        Devuelve el diccionario del pago SOLO si está aprobado, corresponde a
        la referencia externa del link y cubre el total de las órdenes. Ante
        cualquier duda devuelve ``{}`` (fail closed) y deja el detalle en el
        log y en el chatter de las órdenes: un pago sin verificar no se
        factura ni se cobra.
        """
        if not self:
            return {}
        orders = self.sudo()
        company = orders[:1].company_id
        payment_id = str(payment_id or '').strip()
        provider = self.env['payment_mercadopago_point.mercadopago'].sudo().search([
            ('company_id', '=', company.id)], limit=1)
        if not provider:
            orders._mp_link_payment_warning(
                'no se pudo verificar el pago %s porque la compañía %s no tiene '
                'configuración de Mercado Pago.' % (payment_id or '-', company.name))
            return {}
        if not payment_id or payment_id.upper() == 'TEST':
            orders._mp_link_payment_warning(
                'no se recibió un identificador de pago válido (%s): no se facturó. '
                'Verifique el cobro en Mercado Pago.' % (payment_id or '-'))
            return {}
        try:
            payment = provider.get_payment(payment_id)
        except Exception:
            _logger.exception('MP link: no se pudo consultar el pago %s' % payment_id)
            orders._mp_link_payment_warning(
                'no se pudo consultar el pago %s en Mercado Pago: no se facturó.'
                % payment_id)
            return {}
        if not payment:
            orders._mp_link_payment_warning(
                'Mercado Pago no devolvió datos del pago %s: no se facturó.'
                % payment_id)
            return {}
        status = payment.get('status')
        if status != 'approved':
            orders._mp_link_payment_warning(
                'Mercado Pago informa el pago %s en estado %s: no se facturó.'
                % (payment_id, status or '-'))
            return {}
        # El pago tiene que ser de ESTE link: mismo conjunto de órdenes
        if external_reference is None:
            external_reference = ', '.join(orders.mapped('name'))
        if _mp_link_reference_key(payment.get('external_reference')) != \
                _mp_link_reference_key(external_reference):
            orders._mp_link_payment_warning(
                'el pago %s es de la referencia "%s" y no de este link ("%s"): '
                'no se facturó.' % (payment_id,
                                    payment.get('external_reference') or '-',
                                    external_reference))
            return {}
        # ... y por el importe y la moneda correctos
        currency = orders[:1].currency_id
        payment_currency = payment.get('currency_id')
        if payment_currency and currency.name and payment_currency != currency.name:
            orders._mp_link_payment_warning(
                'el pago %s es en %s y las órdenes en %s: no se facturó.'
                % (payment_id, payment_currency, currency.name))
            return {}
        try:
            paid = float(payment.get('transaction_amount') or 0.0)
        except (TypeError, ValueError):
            paid = 0.0
        total = sum(orders.mapped('amount_total'))
        if float_compare(paid, total, precision_rounding=currency.rounding or 0.01) < 0:
            orders._mp_link_payment_warning(
                'el pago %s es por %s y las órdenes suman %s: no se facturó. '
                'Verifique el cobro en Mercado Pago.'
                % (payment_id, currency.format(paid), currency.format(total)))
            return {}
        if float_compare(paid, total, precision_rounding=currency.rounding or 0.01) > 0:
            _logger.warning('MP link: el pago %s (%s) supera el total de las órdenes (%s)'
                            % (payment_id, currency.format(paid), currency.format(total)))
        return payment

    def _mp_link_invoices(self):
        """Facturas de venta no canceladas de la orden."""
        return self.invoice_ids.filtered(lambda i: i.move_type == 'out_invoice' and i.state != 'cancel')

    def _mp_link_prepare_invoices(self):
        """Confirma las órdenes del link (si hace falta) y devuelve sus facturas
        de venta publicadas."""
        invoices = self.env['account.move']
        for order in self:
            # El pago del link confirma la venta: si por algún motivo la orden
            # sigue en borrador o enviada, la confirmo antes de facturar
            if order.state in ('draft', 'sent'):
                order.action_confirm()
            order_invoices = order._mp_link_invoices()
            if not order_invoices:
                order._create_invoices()
                order_invoices = order._mp_link_invoices()
            if not order_invoices:
                raise UserError(_("No se pudieron crear las facturas de la orden %s.") % order.name)
            invoices |= order_invoices
        invoices.filtered(lambda i: i.state == 'draft').action_post()
        return invoices

    def _mp_link_invoice_and_pay(self):
        """Factura las órdenes del link y registra UN ÚNICO pago por el total,
        conciliado con todas las facturas de las órdenes (no un pago por
        factura). El diario de pago lo toma del tipo 'MP Link', ya que el
        pedido queda como CTACTE hasta que el pago se acredita.

        Devuelve el pago (account.payment.group) creado, o un recordset vacío
        si no quedaba nada por pagar."""
        invoices = self._mp_link_prepare_invoices()
        # Todo el link es un solo pago: facturas, diario, moneda y cliente
        # tienen que poder convivir en el mismo grupo de pagos
        if len(self.company_id) > 1:
            raise UserError(_("Todas las órdenes deben pertenecer a la misma compañía."))
        if len(self.partner_id) > 1:
            raise UserError(_("Todas las órdenes deben ser del mismo cliente para "
                              "registrar un único pago."))
        if len(self.currency_id) > 1:
            raise UserError(_("Todas las órdenes deben tener la misma moneda."))
        pay_journal = self.env['account.journal']
        for order in self:
            pay_journal |= order._mp_link_payment_journal()
        if len(pay_journal) > 1:
            raise UserError(_("Las órdenes tienen diarios de pago distintos (%s): "
                              "no se puede registrar un único pago.")
                            % ", ".join(pay_journal.mapped('display_name')))
        # Líneas por cobrar: solo las facturas de estas órdenes que siguen impagas
        to_pay_lines = invoices.filtered(
            lambda i: i.payment_state in ('not_paid', 'partial')
        ).open_move_line_ids.filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled)
        if not to_pay_lines:
            return self.env['account.payment.group']
        monto = sum(to_pay_lines.mapped('amount_residual'))
        company = self.company_id
        partner = self.partner_id
        receiptbook = self.env['account.payment.receiptbook'].search([
            ('partner_type', '=', 'customer'),
            ('company_id', '=', company.id),
        ], limit=1)
        payment_group = self.env['account.payment.group'].create({
            'partner_type': 'customer',
            'partner_id': partner.id,
            'company_id': company.id,
            'receiptbook_id': receiptbook.id,
            'to_pay_move_line_ids': [],
        })
        # _compute_to_pay_move_lines trae TODAS las deudas del cliente; dejo
        # únicamente las facturas de estas órdenes para que el pago quede
        # asociado (conciliado) a ellas
        payment_group.remove_all()
        payment_group.to_pay_move_line_ids = [(6, 0, to_pay_lines.ids)]
        payment_method = pay_journal.inbound_payment_method_line_ids.payment_method_id.filtered(
            lambda x: x.code == 'manual')
        if not payment_method:
            raise UserError(_('El diario %s no tiene configurado el método de pago "manual".')
                            % pay_journal.display_name)
        caja = self.env['account.cashbox.session'].search([
            ('state', '=', 'opened'), ('company_id', '=', company.id)], limit=1)
        payment_group.payment_ids.create({
            'payment_group_id': payment_group.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'company_id': company.id,
            'partner_id': partner.id,
            'amount': monto,
            'journal_id': pay_journal.id,
            'ref': ', '.join(self.mapped('name')),
            'payment_method_id': payment_method.id,
            'date': payment_group.payment_date,
            'cashbox_session_id': caja.id,
        })
        # post() postea el pago y lo concilia con to_pay_move_line_ids
        payment_group.post()
        # Por las dudas cierro lo que haya quedado pendiente (idempotente)
        open_lines = to_pay_lines.filtered(lambda l: not l.reconciled)
        payment_receivable = payment_group.payment_ids.mapped('line_ids').filtered(
            lambda l: l.account_id.account_type == 'asset_receivable' and not l.reconciled)
        if open_lines and payment_receivable:
            (open_lines + payment_receivable).reconcile()
        for order in self:
            order.message_post(body='Pago del link de Mercado Pago registrado con el pago %s (diario %s) por las facturas %s.'
                                    % (payment_group.name or payment_group.document_number or payment_group.id,
                                       pay_journal.display_name,
                                       ', '.join(invoices.mapped('name'))))
        return payment_group

    def _mp_link_notify_payment(self, payment_id=None):
        """Avisa en el canal '<código de la compañía> Pagos link' que se
        confirmó el pago por link de Mercado Pago de estas órdenes."""
        for company in self.mapped('company_id'):
            orders = self.filtered(lambda o: o.company_id == company)
            channel_name = '%s Pagos link' % (company.code or company.name)
            channel = self.env['mail.channel'].sudo().search([('name', '=', channel_name)], limit=1)
            if not channel:
                _logger.warning('No se encontró el canal de notificación "%s" para avisar el pago del link.' % channel_name)
                continue
            invoices = orders.mapped('invoice_ids').filtered(lambda i: i.move_type == 'out_invoice' and i.state != 'cancel')
            moneda = orders[:1].currency_id
            body = (
                '<h4>Pago confirmado por link de Mercado Pago</h4>'
                '<ul>'
                '<li><b>Órdenes:</b> %s</li>'
                '<li><b>Cliente:</b> %s</li>'
                '<li><b>Importe:</b> %s</li>'
                '<li><b>Facturas:</b> %s</li>'
                '<li><b>Pago MP:</b> %s</li>'
                '</ul>'
            ) % (
                ', '.join(orders.mapped('name')),
                orders[:1].partner_id.display_name,
                moneda.format(sum(orders.mapped('amount_total'))),
                ', '.join(invoices.mapped('name')) or '-',
                payment_id or '-',
            )
            # Se publica como OdooBot (SUPERUSER_ID) para que el mensaje NO quede
            # marcado como "visto" por quien dispara el webhook: en Odoo 16
            # sudo() no cambia el usuario, y mail.channel.message_post marca el
            # mensaje como visto para self.env.user. Si lo publicara el usuario
            # que abre la URL de éxito, a ese usuario no le aparecería el aviso
            # de "no leído" en la burbuja.
            channel.sudo().with_user(SUPERUSER_ID).message_post(
                body=body, message_type='comment', subtype_xmlid='mail.mt_comment')


#####################
### IMPRIMIR LA FACTURA

    def action_print_invoice(self):
        self.ensure_one()
        invoice = self.invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice' and inv.state != 'cancel')
        if not invoice and self.tag_ids and any(tag.name == 'CTACTE' for tag in self.tag_ids):
            #return self.env.ref("custom_invoice_ticket.action_report_sale_order_ticket_b").report_action(self)
            report_invoice = self.env.ref("custom_invoice_ticket.action_report_sale_order_ticket")
            result = report_invoice.report_action(self)
           #if isinstance(result, dict):
           #    result['close_on_report_done'] = True
            return result
        if not invoice:
            raise UserError("No hay factura relacionada con este pedido de venta.")
        if len(invoice) > 1:
            raise UserError("Hay más de una factura asociada. Este botón solo admite una.")

        if invoice.journal_id.l10n_ar_afip_pos_system == 'II_IM':
            #return self.env.ref("custom_invoice_ticket.action_report_invoice_ticket_b").report_action(invoice)
            report_invoice = self.env.ref("custom_invoice_ticket.action_report_invoice_ticket")
        else:
            #return self.env.ref("custom_invoice_ticket.action_report_invoice_ticket").report_action(invoice)
            report_invoice = self.env.ref("custom_invoice_ticket.action_report_invoice_ticket")

        result = report_invoice.report_action(invoice)
       #if isinstance(result, dict):
       #    result['close_on_report_done'] = True
        
        return result
    def action_download_invoice(self):
        self.ensure_one()
        invoice = self.invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice' and inv.state != 'cancel')
        if not invoice and self.tag_ids and any(tag.name == 'CTACTE' for tag in self.tag_ids):
            #return self.env.ref("custom_invoice_ticket.action_report_sale_order_ticket_b").report_action(self)
            report_invoice = self.env.ref("custom_invoice_ticket.action_report_sale_order_ticket_b_pdf")
            result = report_invoice.report_action(self)
            return result
        if not invoice:
            raise UserError("No hay factura relacionada con este pedido de venta.")
        if len(invoice) > 1:
            raise UserError("Hay más de una factura asociada. Este botón solo admite una.")

        if invoice.journal_id.l10n_ar_afip_pos_system == 'II_IM':
            #return self.env.ref("custom_invoice_ticket.action_report_invoice_ticket_b").report_action(invoice)
            report_invoice = self.env.ref("custom_invoice_ticket.action_report_invoice_ticket_pdf")
        else:
            #return self.env.ref("custom_invoice_ticket.action_report_invoice_ticket").report_action(invoice)
            report_invoice = self.env.ref("custom_invoice_ticket.action_report_invoice_ticket_pdf")

        result = report_invoice.report_action(invoice)
        
        return result

    ########################################################################
    ### MP QR: el pedido se mantiene en PRESUPUESTO hasta que el pago se acredita
    ########################################################################

    def _mp_qr_provider(self):
        """Proveedor de Mercado Pago QR para el pedido.

        NO se filtra por ``state``: ese campo sólo controla la visibilidad del
        proveedor en el checkout del sitio web. Las órdenes QR presenciales se
        crean por API con ``mercado_pago_qr_access_token`` y funcionan con el
        proveedor en 'enabled', 'test' o incluso 'disabled' (así funcionaba
        ``prepare_payment_mp_qr`` antes del cambio). Se prefiere el nombre
        histórico 'MP QR' y la compañía del pedido; luego se tolera el código
        del proveedor y otras compañías, para no romper la caja.
        """
        self.ensure_one()
        Provider = self.env["payment.provider"].sudo()
        company = self.company_id.id
        for domain in (
            [('name', '=', 'MP QR'), ('company_id', '=', company)],
            [('name', '=', 'MP QR')],
            [('code', '=', 'mercado_pago_qr'), ('company_id', '=', company)],
            [('code', '=', 'mercado_pago_qr')],
        ):
            provider = Provider.search(domain, limit=1)
            if provider:
                return provider
        candidatos = Provider.search([
            '|', ('name', '=', 'MP QR'), ('code', '=', 'mercado_pago_qr')])
        _logger.warning(
            'MP QR: no se encontró proveedor para la compañía %s (id=%s). '
            'Proveedores con name="MP QR"/code="mercado_pago_qr": %s',
            self.company_id.name, self.company_id.id,
            [(p.id, p.name, p.code, p.state, p.company_id.id) for p in candidatos])
        return Provider.browse()

    def _mp_qr_invoices(self):
        """Facturas de venta no canceladas (funciona sobre un recordset)."""
        return self.mapped('invoice_ids').filtered(
            lambda inv: inv.move_type == 'out_invoice' and inv.state != 'cancel')

    def _mp_qr_pending_transactions(self):
        """Transacciones QR todavía pendientes ligadas a este pedido."""
        self.ensure_one()
        tx_model = self.env['payment.transaction'].sudo()
        txs = tx_model.browse()
        if self.payment_provider and self.payment_provider.state in ('draft', 'pending'):
            txs |= self.payment_provider
        # Compatibilidad con transacciones creadas antes de este cambio, que se
        # vinculaban al pedido mediante sale_order_ids.
        txs |= tx_model.search([
            ('sale_order_ids', 'in', [self.id]),
            ('provider_id.code', '=', 'mercado_pago_qr'),
            ('state', 'in', ('draft', 'pending')),
        ])
        return txs

    def _mp_qr_cancel_pending(self, reason=None, post_message=True):
        """Cancela el QR pendiente SIN tocar el pedido.

        El presupuesto queda sin factura y se puede cobrar por otro medio. Un
        IPN tardío sobre una transacción cancelada no factura (fail closed).
        """
        self.ensure_one()
        txs = self._mp_qr_pending_transactions()
        for tx in txs:
            if hasattr(tx, 'mp_payment_order_cancel'):
                try:
                    tx.sudo().mp_payment_order_cancel()
                except Exception:
                    _logger.exception('MP QR: no se pudo cancelar la orden %s en Mercado Pago',
                                      tx.provider_reference or tx.reference)
            tx.sudo()._set_canceled(reason or 'QR cancelado desde el pedido de venta')
            if post_message:
                self.message_post(body=_(
                    'Se canceló el código QR de Mercado Pago pendiente (%s). El pedido '
                    'sigue en presupuesto y sin factura; puede continuar con otro '
                    'medio de pago.') % tx.reference)
        return txs

    def _mp_qr_discount_lines(self):
        """Líneas de descuento/redondeo generadas automáticamente.

        Se identifican por el producto de ``sale.order.discount`` y por la
        convención del propio proyecto (nombres 'DESCUENTO...' y 'REDONDEO',
        la misma que usa ``sale_order_discount.copy()``).
        """
        self.ensure_one()
        try:
            discount_products = self.env['sale.order.discount'].sudo().search([]).mapped('product_id')
        except KeyError:
            # El modelo de descuentos no está instalado en esta BD.
            discount_products = self.env['product.product']
        return self.order_line.filtered(
            lambda l: l.product_id in discount_products
            or (l.product_id.name or '').upper().startswith('DESCUENTO')
            or (l.product_id.name or '').upper() == 'REDONDEO')

    def _mp_qr_discount_applied(self):
        """True si el pedido tiene un QR (no pagado) que ya aplicó el descuento."""
        self.ensure_one()
        tx = self.payment_provider.sudo()
        return bool(tx and tx.provider_id.code == 'mercado_pago_qr'
                    and tx.state in ('draft', 'pending', 'cancel', 'error'))

    def _mp_qr_reset_discount(self):
        """Quita las líneas de descuento/redondeo y deja los importes limpios.

        ``apply_discount()`` NO es idempotente: ejecutarlo sobre un pedido que
        ya tiene esas líneas recalcula sobre un total ya descontado (descuento
        duplicado o división por cero). Al cancelar el QR hay que dejar el
        pedido limpio para que el nuevo medio de pago lo recalcule con SU tipo.
        """
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            return True
        lines = self._mp_qr_discount_lines()
        if lines:
            lines.unlink()
        # Recalcular los importes desde el total SIN líneas de descuento,
        # conservando el porcentaje (manual o del tipo de pedido).
        self.invalidate_recordset(
            ['order_line', 'amount_total', 'amount_untaxed', 'amount_tax'])
        total = self.amount_total
        percent = self.sale_discount_percent or 0.0
        descuento = total * percent / 100.0
        self.write({
            'sale_discount': descuento,
            'sale_with_discount': total - descuento,
        })
        return True

    def _mp_qr_recalc_discount(self):
        """Recalcula el descuento con las líneas de producto ACTUALES.

        Acepta un recordset (el hook de ``write`` puede traer varios pedidos),
        así que se itera en vez de exigir ``ensure_one``.
        """
        for order in self.filtered(lambda o: o.state in ('draft', 'sent')):
            order._mp_qr_reset_discount()
            order.apply_discount()
        return True

    def _mp_qr_start(self, caja, efectivo_amount=0):
        """Genera el código QR SIN confirmar ni facturar el pedido.

        El pedido sigue en estado 'draft' (Presupuesto). La factura se emite
        recién en ``_mp_qr_confirm_and_invoice``, cuando el pago se acredita.
        """
        self.ensure_one()
        # Si ya hay un QR vigente para el pedido NO generamos otro: primero
        # refrescamos su estado en Mercado Pago (por si el IPN no llegó) y
        # reabrimos el mismo QR. Así se evita un segundo cobro. Si el total del
        # pedido cambió (se agregaron productos), el QR viejo ya no sirve.
        pending = self._mp_qr_pending_transactions()
        expected_amount = self.amount_total - (efectivo_amount or 0)
        if pending and float_compare(
                pending[:1].amount, expected_amount,
                precision_rounding=self.currency_id.rounding or 0.01) == 0:
            tx = pending[:1]
            try:
                tx.sudo().mp_payment_order_get()
            except Exception:
                _logger.exception('MP QR: no se pudo refrescar el estado del QR %s', tx.reference)
            if tx.state in ('draft', 'pending', 'authorized', 'done'):
                return self.pay_mp_qr_wizard(tx)
            # Venció o se canceló: seguimos abajo y generamos uno nuevo.
        elif pending:
            self._mp_qr_cancel_pending('El total del pedido cambió; se regenera el QR')
        if self.type_id.name == 'Efectivo':
            self.apply_redondeo()
            if abs(self.redondeo) > 1000:
                raise UserError('No puede aplicar un redondeo mayor a 1.000 (%s) ' % self.redondeo)
        # El descuento se RECALCULA (no se re-aplica) ANTES de crear la
        # transacción: el importe del QR tiene que coincidir con el total
        # definitivo de las líneas actuales, sin arrastrar descuentos viejos.
        self._mp_qr_recalc_discount()
        if not self.caja_id:
            self.caja_id = caja.id
        # Guardamos la parte en efectivo para registrar su cobro al acreditarse
        # el QR (antes no existe factura contra la cual imputarla).
        self.efectivo = efectivo_amount
        self.is_admin = False
        tx = self.pay_mp_qr(self.efectivo or 0)
        if not tx:
            # Sin proveedor configurado no se genera el QR, pero el pedido
            # SIGUE en presupuesto y sin factura: se puede cobrar por otro medio.
            return self._mp_link_notify_action(
                _('No se encontró el proveedor de Mercado Pago QR para la compañía %s. '
                  'Revise la configuración del proveedor o cobre con otro medio de pago.')
                % self.company_id.name, 'warning', reload=True)
        return self.pay_mp_qr_wizard()

    def _mp_qr_register_cash(self, invoices):
        """Registra la parte en efectivo de un pago múltiple. Se ejecuta recién
        cuando el QR se acreditó y la factura ya existe."""
        self.ensure_one()
        if not self.efectivo or self.efectivo <= 0:
            return True
        sale_efectivo = self.env["sale.order.type"].search(
            [("name", "ilike", 'Efectivo'), ("company_id", "=", self.company_id.id)], limit=1)
        sale_varios = self.env["sale.order.type"].search(
            [("name", "ilike", 'Varios'), ("company_id", "=", self.company_id.id)], limit=1)
        if not sale_efectivo or not sale_efectivo.payment_journal_id:
            raise UserError(_("El tipo de pedido 'Efectivo' no tiene configurado el diario de pago."))
        for invoice in invoices:
            pay = self.pay_multiple(invoice, sale_efectivo.payment_journal_id, self.efectivo)
            if pay:
                self.reconciliar_venta(invoice, [pay])
        if sale_varios:
            self.type_id = sale_varios.id
        return True

    def _mp_qr_confirm_and_invoice(self, tx):
        """Confirma el presupuesto y emite la factura.

        Se llama ÚNICAMENTE desde el enganche del proveedor, después de
        verificar que el pago del QR es correcto.
        """
        self.ensure_one()
        if self.state == 'cancel':
            raise UserError(_("El pedido %s está cancelado; no se puede facturar.") % self.name)
        invoices = self._mp_qr_invoices()
        if self.state in ('draft', 'sent'):
            # 'sale_order_type_automation' crea y publica la factura al confirmar.
            # La transacción sigue en 'pending' y NO está vinculada por
            # sale_order_ids, así que la automatización no omite la facturación.
            self.action_confirm()
            invoices = self._mp_qr_invoices()
        if not invoices:
            self._create_invoices(final=True)
            invoices = self._mp_qr_invoices()
        if not invoices:
            raise UserError(_("No se pudieron crear las facturas del pedido %s.") % self.name)
        invoices.filtered(lambda inv: inv.state == 'draft').action_post()
        # Vincular la factura a la transacción: account_payment._create_payment
        # la usa para crear el cobro del QR y conciliarlo.
        tx.sudo().invoice_ids = [(6, 0, invoices.ids)]
        self._mp_qr_register_cash(invoices)
        self.message_post(body=_(
            'Pago del QR de Mercado Pago acreditado (%s). Se confirmó el pedido, '
            'se emitieron las facturas %s y se registró el cobro.')
            % (tx.reference, ', '.join(invoices.mapped('name'))))
        return invoices

    def _mp_qr_payment_warning(self, message):
        """Deja constancia en el chatter de un pago que NO se pudo verificar."""
        _logger.warning('MP QR: %s' % message)
        for order in self:
            order.message_post(body=_('Mercado Pago QR: %s') % message)
        return True

    def prepare_payment_mp_qr(self,efectivo=0):
        self.ensure_one()
        provider = self._mp_qr_provider()
        if not provider:
            _logger.warning('MP QR: no se generó la transacción porque no hay proveedor '
                            'configurado para %s.', self.company_id.name)
            return False
        _logger.info('PROVIDER %s' % provider)
        amount = self.amount_total - (efectivo or 0)
        if amount <= 0:
            raise UserError(_('El importe del QR debe ser mayor que cero. Revise el '
                              'monto en efectivo del pago múltiple.'))
        res = { "provider_id": int(provider.id),
                "reference": self.env["payment.transaction"]._compute_reference( provider.code, prefix=self.name),
                "amount": amount,
                "currency_id": self.currency_id.id,
                "partner_id": self.partner_id.id,
              }
        # Sólo se vinculan facturas que YA existan (pedido confirmado por otro
        # medio). En el flujo normal NO hay factura al generar el QR: se crea
        # al acreditarse el pago.
        invoices = self._mp_qr_invoices()
        if invoices:
            res["invoice_ids"] = [(6, 0, invoices.ids)]
        # NO se setea sale_order_ids: así el módulo 'sale' no marca el
        # presupuesto como enviado ni envía correos, y _invoice_sale_orders no
        # pisa invoice_ids cuando llegue el pago.
        return res
