from odoo import models, fields, api, _
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import time
import re
import textwrap
import logging
_logger = logging.getLogger(__name__)
# Bloquear autozorizaciones del encargado cuando el pedido esta enviado y facturado 
# Bloquear autizacion de caja cerrada
# 


class SaleOrderQR(models.Model):
    _inherit = "sale.order"

    ticket_num = fields.Char(string="Ticket Number", size=4)
    seller = fields.Char(string="Seller", size=1)
    scale = fields.Char(string="Scale Number", size=3)
    total_items = fields.Integer(string="Total Items", default=0)
    payment_provider = fields.Many2one('payment.transaction')
    caja_id = fields.Many2one('account.cashbox.session', string="Sesión de Caja")
    is_admin = fields.Boolean(default=False, store=True,tracking=True)
    mp_link = fields.Char(string="MP Link", copy=False)

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
            seller = header[17:18]  # Seller (1 character)
            scale = header[18:21]  # Scale Number (3 characters)
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
        payment_type = context.get('payment_type')
        if efectivo:
            efectivo=float(efectivo)
        if efectivo and efectivo > 0:
            payment_type = 'Multiple'
        label = context.get('label')
        if payment_type == 'MP':
            popup = self.env['scan_qr.popup.confirmation']
            action = popup.show_mp(self, 'Selccion el metodo a utilizar', 'action_confirm_type')
            return action

        if payment_type == 'Multiple' and not efectivo:
            popup = self.env['scan_qr.popup.confirmation']
            action = popup.show_efectivo(self, 'Ingreso el monto en efectivo y seleccione el otro metodo de pago <h3>Total: %s</h3>' % self.amount_total, 'action_confirm_type')
            return action

        sale_order_type = self.env["sale.order.type"].search([("name", "ilike", payment_type),("company_id","=",self.company_id.id)], limit=1)
        if self.state == 'sale':
            _logger.info('Procesando pago')
            if sale_order_type:
                self.type_id = sale_order_type.id
            provider = self.env["payment.provider"].sudo().search([('name','=','MP QR'),('state','=','enabled'),('company_id.id','=',self.company_id.id)],limit=1)
            if payment_type == 'MP QR' and provider:
                payment_provider = self.pay_mp_qr()
                self.payment_provider = payment_provider.id
                return self.pay_mp_qr_wizard()
            if payment_type == 'MP Link':
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
        _logger.info('%s %s %s %s' % (payment_type,efectivo,context.get('payment_type'),sale_order_type ) )
        self.type_id=sale_order_type.id
        self.env.cr.commit()
        if payment_type == 'CTACTE':
            tag_id = self.env["crm.tag"].search([('name','=','CTACTE')])
            self.tag_ids = tag_id.ids 
            self.state = 'sent'
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
            provider = self.env["payment.provider"].sudo().search([('name','=','MP QR'),('state','=','enabled'),('company_id.id','=',self.company_id.id)],limit=1)
            if payment_type == 'MP QR' and provider:
                if self.efectivo > 0:
                    for moves in self.invoice_ids:
                        sale_efectivo = self.env["sale.order.type"].search([("name", "ilike", 'Efectivo'),("company_id","=",self.company_id.id)], limit=1)
                        sale_varios = self.env["sale.order.type"].search([("name", "ilike", 'Varios'),("company_id","=",self.company_id.id)], limit=1)
                        pay1=self.pay_multiple(moves,sale_efectivo.payment_journal_id,self.efectivo)
                        self.reconciliar_venta(moves,[pay1])
                        payment_provider = self.pay_mp_qr(self.efectivo)
                        self.payment_provider = payment_provider.id
                        self.type_id = sale_varios.id
                else:
                    payment_provider = self.pay_mp_qr(self.efectivo)
                    self.payment_provider = payment_provider.id
                return self.pay_mp_qr_wizard()
            elif payment_type in ['MP Link']:
                return self._mp_link_generate()
            elif payment_type != 'CTACTE Factura':
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

    def _mp_link_generate(self):
        """Genera y guarda el link de pago de Mercado Pago para esta orden.

        Se usa tanto para pedidos en borrador/enviados (tras confirmarlos) como
        para pedidos ya confirmados ('sale'), de modo que elegir 'MP Link'
        siempre genere el link."""
        self.ensure_one()
        provider = self.env["payment_mercadopago_point.mercadopago"].sudo().search([
            ('company_id.id', '=', self.company_id.id)], limit=1)
        if not provider:
            raise UserError(_("No se encontró la configuración de Mercado Pago Point "
                              "para la compañía %s.") % self.company_id.name)
        _logger.info('Generando link MP para la orden %s' % self.name)
        mp_link = provider.create_order_link(self)
        _logger.info('Link de pago: %s' % mp_link)
        self.mp_link = mp_link
        self.message_post(body="Link de pago: %s" % mp_link)
        self.env.cr.commit()
        return True

    def action_mp_link_regenerate(self):
        """Botón del formulario: regenera el link de pago de Mercado Pago.

        Solo para órdenes que no están pagas; vuelve a abrir el formulario
        para mostrar el link actualizado."""
        self.ensure_one()
        if self.payment_status == 'Paid':
            raise UserError(_("La orden %s ya está paga; no se regenera el link de pago.") % self.name)
        self._mp_link_generate()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def pay_mp_qr_wizard(self):
        _logger.info('Abriendo QR 1 %s %s' % (self.payment_status,self.payment_provider) )
        if self.payment_provider and self.payment_provider.state in ['draft','pending']:
            _logger.info('Abriendo QR 2')
            return self.payment_provider.action_mp_open_qr()

    def pay_mp_qr(self,efectivo=0):
        transaction_vals = self.prepare_payment_mp_qr(efectivo)
        if not transaction_vals:
            return True
        wizard_sudo = self.sudo()
        transaction = wizard_sudo.env["payment.transaction"].create(transaction_vals)
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
            "target": "new",
            "context": {"default_sale_order_id": self.id},
        }

    def _mp_link_validate_orders(self):
        """Valida que las órdenes puedan agruparse en un único link de pago MP.

        Se usa tanto al abrir el wizard (validación previa, antes de mostrar la
        lista) como al generar el link. Se aceptan pedidos enviados ('sent') y
        confirmados ('sale'); cualquier otro estado se rechaza.
        """
        if not self:
            raise UserError(_("Debe seleccionar al menos una orden de venta."))
        invalid_state = self.filtered(lambda o: o.state not in ('sent', 'sale'))
        if invalid_state:
            raise UserError(_("Solo se pueden agrupar pedidos enviados ('Presupuesto enviado') "
                              "o confirmados ('Pedido de venta'). Revise: %s")
                            % ", ".join(invalid_state.mapped('name')))
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
            'target': 'new',
            'context': {'active_model': 'sale.order', 'active_ids': orders.ids},
        }

    def pay_mp_link(self, data):
        """Procesa el retorno de éxito de un link de pago de Mercado Pago.

        Verifica el pago contra la API de MP, factura las órdenes del
        external_reference (una o varias separadas por coma) y las paga con
        el diario de pago del tipo de pedido. Cuando quedan pagadas avisa en
        el canal '<código de la compañía> Pagos link'."""
        data = data or {}
        external_reference = data.get('external_reference') or ''
        payment_id = data.get('payment_id') or data.get('collection_id')
        names = [n.strip() for n in external_reference.split(',') if n.strip()]
        if not names:
            _logger.warning('MP success sin external_reference: %s' % data)
            return False
        orders = self.env['sale.order'].sudo().search([('name', 'in', names)])
        if not orders:
            _logger.warning('MP success: no se encontraron órdenes para %s' % external_reference)
            return False
        # Verifico el estado real del pago contra la API de Mercado Pago
        # (no confío en los parámetros de la URL, que pueden ser falsificados)
        status = data.get('status')
        provider = self.env['payment_mercadopago_point.mercadopago'].sudo().search([
            ('company_id', '=', orders[:1].company_id.id)], limit=1)
        if payment_id and provider and payment_id != 'TEST':
            try:
                status = provider.get_payment_status(orders[:1], payment_id)
            except Exception:
                _logger.exception('MP success: no se pudo verificar el pago %s' % payment_id)
        _logger.info('MP success: reference=%s payment_id=%s status=%s' % (external_reference, payment_id, status))
        if status != 'approved':
            orders.message_post(body='Mercado Pago: el link devolvió el estado %s (pago %s). No se facturó.' % (status, payment_id))
            return False
        pagadas = self.env['sale.order'].sudo()
        for order in orders:
            try:
                # savepoint por orden: si una falla, las demás se procesan igual
                with self.env.cr.savepoint():
                    if order._mp_link_invoice_and_pay():
                        pagadas |= order
            except Exception:
                _logger.exception('MP success: error al facturar/pagar la orden %s' % order.name)
                order.message_post(body='Error al facturar/pagar el pago del link de Mercado Pago. Revise la orden.')
        if pagadas:
            pagadas._mp_link_notify_payment(payment_id)
        return True

    def _mp_link_invoices(self):
        """Facturas de venta no canceladas de la orden."""
        return self.invoice_ids.filtered(lambda i: i.move_type == 'out_invoice' and i.state != 'cancel')

    def _mp_link_invoice_and_pay(self):
        """Factura la orden y paga la factura con el diario de pago del tipo
        de pedido. El diario de facturación lo toma del tipo de pedido
        (sale_order_type lo aplica en _prepare_invoice).
        Retorna True solo si en esta llamada se pagaron facturas."""
        self.ensure_one()
        # El pago del link confirma la venta: si por algún motivo la orden
        # sigue en borrador o enviada, la confirmo antes de facturar
        if self.state in ('draft', 'sent'):
            self.action_confirm()
        invoices = self._mp_link_invoices()
        if not invoices:
            self._create_invoices()
            invoices = self._mp_link_invoices()
        if not invoices:
            raise UserError(_("No se pudieron crear las facturas de la orden %s.") % self.name)
        pay_journal = self.type_id.payment_journal_id
        if not pay_journal:
            raise UserError(_("El tipo de pedido %s de la orden %s no tiene configurado el diario de pago.") % (self.type_id.display_name, self.name))
        pagada = False
        for invoice in invoices:
            if invoice.state == 'draft':
                invoice.action_post()
            if invoice.payment_state in ['not_paid', 'partial']:
                monto = invoice.amount_residual if invoice.payment_state == 'partial' else invoice.amount_total
                payment_group = self.pay_multiple(invoice, pay_journal, monto)
                if payment_group:
                    self.reconciliar_venta(invoice, [payment_group])
                    pagada = True
                    self.message_post(body='Pago del link de Mercado Pago registrado en la factura %s (diario %s).' % (invoice.name, pay_journal.display_name))
        return pagada

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
            channel.sudo().message_post(body=body, message_type='comment', subtype_xmlid='mail.mt_comment')


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

    def prepare_payment_mp_qr(self,efectivo=0):
        self.ensure_one()
        provider = self.env["payment.provider"].sudo().search([('name','=','MP QR'),('company_id.id','=',self.company_id.id)],limit=1)
        if not provider:
            return False
        _logger.info('PROVIDER %s' % provider)
        res = { "provider_id": int(provider.id),
                "reference": self.env["payment.transaction"]._compute_reference( provider.code, prefix=self.name),
                "amount": self.amount_total - efectivo,
                "currency_id": self.currency_id.id,
                "partner_id": self.partner_id.id,
              }
        res["invoice_ids"] = [(6, 0, [self.invoice_ids.id])]
        res["sale_order_ids"] = [(6, 0, [self.id])]

        return res
