from odoo import models, fields, api
from odoo.exceptions import UserError
import textwrap

import re
import logging
_logger = logging.getLogger(__name__)


class ScanQRWizard(models.TransientModel):
    _name = "scan.qr.wizard"
    _description = "Scan QR Code for Sale Order"

    qr_code = fields.Text("QR Code", required=True)
    clave = fields.Char()
    sale_order_id = fields.Many2one("sale.order", string="Sale Order", readonly=True)

    # VISUALIZACIÓN DE PRODUCTO Y PRECIO TOTAL DE LECTURA DE QR
    product_lines = fields.One2many("scan.qr.wizard.line", "wizard_id", string="Products")
    total_amount = fields.Float("Total", compute="_compute_total", store=True)

    # CREACIÓN DE LA SALE ORDER
    # Métodos para procesar distintos Tipos de pedido de venta: Efectivo, Tarjeta, Mercado Pago, Cuenta Corriente.
    def action_process_qr_efectivo(self):
        # Control si tengo una caja abierta
        return self._process_qr("Efectivo")
    def action_process_qr_tarjeta(self):
        return self._process_qr("Tarjeta")
    def action_process_qr_mercadopago(self):
        return self._process_qr("Mercado Pago")
    def action_process_qr_cuentacorriente(self):
        return self._process_qr("Cuenta Corriente")
    def _process_qr(self, payment_type):
        caja = self.env['account.cashbox.session'].search([('state','=','opened'),])
        if not caja:
            raise UserError('No se encontro ninguna caja abierta')
        sale_order_model = self.env["sale.order"]
        order_id = sale_order_model.create_sale_order_from_qr(self.qr_code, payment_type)

        if order_id:
            order = sale_order_model.browse(order_id)
            # Confirmación de sale order: order.action_confirm()

            return {
                "type": "ir.actions.act_window",
                "res_model": "sale.order",
                "res_id": order.id,
                "view_mode": "form",
                "target": "current",
            }
        else:
            raise UserError(f"Error al crear la orden con pago '{payment_type}'. Verifique el QR.")


    # VISUALIZACIÓN DE PRODUCTO Y PRECIO TOTAL DE LECTURA DE QR
    @api.depends("product_lines.price_subtotal")
    def _compute_total(self):
        for wizard in self:
            wizard.total_amount = sum(wizard.product_lines.mapped("price_subtotal"))

    def action_process_qr(self):

        product_lines = self._parse_qr_code(self.qr_code)

        if not product_lines:
            raise UserError("No valid products found in QR code.")

        self.product_lines.unlink()
        self.write({"product_lines": [(0, 0, line) for line in product_lines]})

        return {
          'type': 'ir.actions.act_window',
          'res_model': 'scan.qr.wizard',
          'view_mode': 'form',
          'res_id': self.id,
          'target': 'new',
        }

    def _parse_qr_code(self, qr_code):

        clean_qr_code = re.sub(r'\D', '', qr_code)
        products_part = clean_qr_code[19:]
        barcodes = [products_part[i:i+13] for i in range(0, len(products_part), 13) if len(products_part[i:i+13]) == 13]

        product_lines = []

        for ean13 in barcodes:
            # Extraer datos del código de barras
            barcode_type = ean13[0]  # Primer dígito
            internal_ref = ean13[1:7].lstrip("0")  # Referencia interna sin ceros a la izquierda
            quantity_or_weight = int(ean13[7:12])  # Peso o cantidad
            validator = ean13[12]  # Dígito de control
            product = self.env["product.product"].search([("default_code", "=", internal_ref)], limit=1)

            if not product:
                _logger.warning(f"Product not found for reference: {internal_ref}")
                continue

            product_lines.append({
                "product_id": product.id,
                "name": product.name,
                "price_unit": product.lst_price,
                "product_uom_qty": quantity_or_weight if barcode_type == "3" else 1, 
                # Si es cantidad, usar valor, si es peso, usar 1, agregar los decimales
                "price_subtotal": product.lst_price * (quantity_or_weight if barcode_type == "3" else 1),
            })

        if not product_lines:
            raise UserError("No valid products found in QR code.")

        return product_lines

    def process_qr_add_lines_gratis(self):
        # Verifico si la clave pasada es correcta, sino no hago pongo un mensaje
        if self.clave  !=  self.env['ir.config_parameter'].sudo().get_param('autorizacioncaja'):
            raise UserError('Clave incorrecta, no puede agregar productos sin cargo')
        if not self.sale_order_id:
            raise UserError("No hay una orden de venta seleccionada.")

        sale_order = self.sale_order_id
        lines = self.qr_code.strip().split("\n")
        product_lines = lines[1:]
        product_lines = textwrap.fill(product_lines[0],13).split()
        product_l     = self.env["sale.order"]._parse_products(product_lines)
        product_lines = []
        for p in product_l:
            p['price_unit'] = 0
            product_lines.append(p)

        if not product_lines:
            raise UserError("No se encontraron productos en el código QR.")

        sale_order.write({"order_line": [(0, 0, line) for line in product_lines]})

        return {"type": "ir.actions.act_window_close"}
        

    # AGREGADO DE PRODUCTOS
    # Agrega productos escaneados a la orden de venta existente después de validar.
    def process_qr_add_lines(self):
        if not self.sale_order_id:
            raise UserError("No hay una orden de venta seleccionada.")

        sale_order = self.sale_order_id
        lines = self.qr_code.strip().split("\n")
        product_lines = lines[1:]
        product_lines = textwrap.fill(product_lines[0],13).split()
        product_lines = self.env["sale.order"]._parse_products(product_lines)

        if not product_lines:
            raise UserError("No se encontraron productos en el código QR.")

        sale_order.write({"order_line": [(0, 0, line) for line in product_lines]})

        return {"type": "ir.actions.act_window_close"}

# PARA LA TABLA DE LECTURA DE LOS QR EN EL WIZARD
class ScanQRWizardLine(models.TransientModel):
    _name = "scan.qr.wizard.line"
    _description = "Wizard QR Code Lines"

    wizard_id = fields.Many2one("scan.qr.wizard", string="Wizard")
    product_id = fields.Many2one("product.product", string="Product")
    name = fields.Char("Description")
    #quantity = fields.Float("Quantity", default=1.0)
    product_uom_qty = fields.Float("Quantity", default=1.0)
    price_unit = fields.Float("Unit Price")
    price_subtotal = fields.Float("Subtotal", compute="_compute_subtotal", store=True)

    @api.depends("product_uom_qty", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.product_uom_qty * line.price_unit
