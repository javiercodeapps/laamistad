from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import time
import re
import textwrap
import logging
_logger = logging.getLogger(__name__)

class SaleOrderQR(models.Model):
    _inherit = "sale.order"

    ticket_num = fields.Char(string="Ticket Number", size=4)
    seller = fields.Char(string="Seller", size=1)
    scale = fields.Char(string="Scale Number", size=3)
    total_items = fields.Integer(string="Total Items", default=0)
    payment_provider = fields.Many2one('payment.transaction',copy=False)
    mp_link = fields.Char(string="MP Link", copy=False)
    caja_id = fields.Many2one('account.cashbox.session', string="Sesión de Caja")
    is_admin = fields.Boolean(default=False, store=True,tracking=True)


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
        context = self.env.context
        # Find the Sale Order Type where the name contains 'Efectivo' or 'Tarjeta' or 'Mercado Pago' or 'CC'
        payment_type = context.get('payment_type')
        if efectivo:
            efectivo=float(efectivo)
        if efectivo and efectivo > 0:
            payment_type = 'Multiple'
        label = context.get('label')
        if payment_type == 'MP':
            popup = self.env['paimon.popup.confirmation']
            action = popup.show(self, 'Selccion el metodo a utilizar', 'action_confirm_type')
            return action

        if payment_type == 'Multiple' and not efectivo:
            popup = self.env['paimon.popup.confirmation']
            action = popup.show_efectivo(self, 'Ingreso el monto en efectivo y seleccione el otro metodo de pago <h3>Total: %s</h3>' % self.amount_total, 'action_confirm_type')
            return action

        sale_order_type = self.env["sale.order.type"].search([("name", "ilike", payment_type),("company_id","=",self.company_id.id)], limit=1)
        if self.state == 'sale':
            _logger.info('Procesando pago')
            self.type_id=sale_order_type.id
            provider = self.env["payment.provider"].sudo().search([('name','=','MP QR'),('state','=','enabled'),('company_id.id','=',self.company_id.id)],limit=1)
            if payment_type == 'MP QR' and provider:
                payment_provider = self.pay_mp_qr()
                self.payment_provider = payment_provider.id
                return self.pay_mp_qr_wizard()
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
        caja = self.env['account.cashbox.session'].search([('state','=','opened'),('company_id.id','=',self.company_id.id)])
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
                _logger.info('Procesando pago')
                _logger.info('Procesando pago %s' % payment_type)
                _logger.info('Procesando pago %s' % self)
                provider = self.env["payment_mercadopago_point.mercadopago"].sudo().search([('company_id.id','=', self.company_id.id)], limit=1)
                _logger.info('Procesando pago %s' % provider)
                if not self.payment_provider:
                    self.payment_provider = provider.id
                    _logger.info("Creando Link de pago:" )
                    mp_link = provider.create_order_link(self)
                    _logger.info("Link de pago: %s" % mp_link)
                    self.mp_link = mp_link
                    self.message_post(body="Link de pago: %s" % mp_link)
                    self.env.cr.commit()
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

    def pay_mp_link(self,data):
        _logger.info('MP LINK DATA %s' % data)
        payment_provider = self.env["payment_mercadopago_point.mercadopago.history"].sudo().search([('preference','ilike', data['preference_id'])], limit=1)
        if payment_provider:
            so = payment_provider.sale_id
            provider = self.env["payment_mercadopago_point.mercadopago"].sudo().search([('company_id.id','=', so.company_id.id)], limit=1)
            status =  provider.get_payment_status(so,data['payment_id'])
            _logger.info('Status de SO: %s' % so.id)
            _logger.info('Status de SO: %s' % so.state)
            _logger.info('Status de SO: %s' % so.invoice_ids)
            _logger.info('Status de pago: %s' % status)
            if status == 'approved':
                #self.env.cr.commit()
                for moves in so.invoice_ids:
                    _logger.info('TEST MOVES 1 %s' % moves)
                    pay1=self.with_company(so.company_id).pay_multiple(moves,so.type_id.payment_journal_id,moves.amount_total)
                    _logger.info('TEST pay 1 %s' % pay1)
                    self.reconciliar_venta(moves,[pay1])
        return 0
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
            dest_account = self.env['account.account'].search([('code','=','1.1.3.01.010'),('company_id','=',rec.company_id.id)],limit=1)
            if pay_journal and rec.state == 'posted' and rec.payment_state in ['not_paid', 'partial']:
                partner_type = 'customer'
                receiptbook = self.env[ 'account.payment.receiptbook'].search([
                                                ('partner_type', '=', partner_type),
                                                ('company_id', '=', rec.company_id.id),
                                      ], limit=1)
                payable_lines = rec.line_ids.filtered(
                    lambda l: l.account_id.account_type == 'receivable' and l.amount_residual > 0
                )
                payment_group = rec.env['account.payment.group'].create({
                            'partner_type': partner_type,
                            'partner_id': rec.partner_id.id,
                            'receiptbook_id': receiptbook.id,
                            'to_pay_move_line_ids':[(6, 0, payable_lines.ids)],
                        })

                payment_methods = pay_journal.inbound_payment_method_line_ids.payment_method_id
                payment_type = 'inbound'
                payment_method = payment_methods.filtered(
                    lambda x: x.code == 'manual')
                if not payment_method:
                    raise ValidationError(_(
                        'Pay now journal must have manual method!'))

                caja = self.env['account.cashbox.session'].search([('state','=','opened'),('company_id.id','=',rec.company_id.id)])
                payment_group.with_company(rec.company_id).payment_ids.create({
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
                    'destination_account_id': dest_account.id,
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
        # Diario de factura electronica
        journal = self.env['account.journal'].search([('name','ilike','Ventas electr')])
        # Busco facturas
        aml_obj = self.env['account.move.line']
        for invoice in self.invoice_ids:
            if invoice.journal_id == journal.id:
                return UserError('La factura ya esta facturada correctamente')
            if invoice.state=='posted':
                aml_obj = self.env['account.move.line']
                for payment in invoice.payment_group_ids:
                    for move_line in payment.move_line_ids:
                        if move_line.account_type == 'asset_receivable':
                            aml_obj += move_line
    
                invoice.button_draft()
                invoice.button_cancel()
        
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


#####################
### IMPRIMIR LA FACTURA

    def action_print_invoice(self):
        self.ensure_one()
        invoice = self.invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice' and inv.state != 'cancel')
        if not invoice:
            raise UserError("No hay factura relacionada con este pedido de venta.")
        if len(invoice) > 1:
            raise UserError("Hay más de una factura asociada. Este botón solo admite una.")

        return self.env.ref("account.account_invoices").report_action(invoice)

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

