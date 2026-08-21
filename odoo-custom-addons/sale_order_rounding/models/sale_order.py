from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.depends('order_line.price_total')
    def _compute_amount_untaxed_round(self):
        for order in self:
            untaxed = sum(line.price_subtotal for line in order.order_line)
            order.amount_untaxed = round(untaxed, 0)
            _logger.warning(f"# REDONDEO DE amount_untaxed EN SALE ORDER {order.name}: {order.amount_untaxed}")

    @api.depends('order_line.price_total')
    def _compute_amount_tax_round(self):
        for order in self:
            tax = sum(line.price_total - line.price_subtotal for line in order.order_line)
            order.amount_tax = round(tax, 0)
            _logger.warning(f"# REDONDEO DE amount_tax EN SALE ORDER {order.name}: {order.amount_tax}")

    @api.depends('amount_untaxed', 'amount_tax')
    def _compute_amount_total_round(self):
        for order in self:
            order.amount_total = round(order.amount_untaxed + order.amount_tax, 0)
            _logger.warning(f"# REDONDEO DE amount_total EN SALE ORDER {order.name}: {order.amount_total}")

    amount_untaxed = fields.Monetary(
        compute="_compute_amount_untaxed_round",
        store=True,
        readonly=True,
    )
    amount_tax = fields.Monetary(
        compute="_compute_amount_tax_round",
        store=True,
        readonly=True,
    )
    amount_total = fields.Monetary(
        compute="_compute_amount_total_round",
        store=True,
        readonly=True,
    )

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('product_uom_qty', 'discount', 'price_unit', 'tax_id')
    def _compute_amount(self):
        for line in self:
            super(SaleOrderLine, line)._compute_amount()
            line.price_subtotal = round(line.price_subtotal, 0)
            line.price_total = round(line.price_total, 0)
            _logger.warning(f"# REDONDEO DE LINEA price_subtotal: {line.price_subtotal}, price_total: {line.price_total} (SALE ORDER: {line.order_id.name})")

# CLASS LÍNEAS DE INVOICE
class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if line.price_unit:
                line.price_unit = round(line.price_unit, 0)

        return lines

