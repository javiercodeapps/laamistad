# -*- coding: utf-8 -*-
"""Recálculo del descuento cuando cambian las líneas del presupuesto.

Odoo edita las líneas de un pedido escribiendo DIRECTAMENTE en
``sale.order.line`` (no siempre pasa por ``sale.order.write({'order_line': ...})``),
y ``compute_discount()`` está condicionado a ``not order.is_admin``. Este hook
usa el cálculo determinístico de ``scan_qr`` (que no depende de is_admin) para
que el descuento se actualice siempre, sin agregar códigos de descuento al
presupuesto.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Campos que cambian el importe del pedido y, por tanto, el descuento.
RECALC_FIELDS = {
    'product_id', 'product_uom', 'product_uom_qty',
    'price_unit', 'discount', 'tax_id',
}


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _mp_qr_is_discount_line(self):
        """¿Es un código de descuento/redondeo generado automáticamente?

        Esas líneas se crean al confirmar; no deben disparar un recálculo que
        las volvería a eliminar.
        """
        self.ensure_one()
        name = (self.product_id.name or '').upper()
        if name.startswith('DESCUENTO') or name == 'REDONDEO':
            return True
        try:
            products = self.env['sale.order.discount'].sudo().search([]).mapped('product_id')
        except KeyError:
            products = self.env['product.product']
        return self.product_id in products

    def _mp_qr_recalc_orders(self, orders, lines):
        """Recalcula el descuento de los pedidos afectados (sólo presupuestos)."""
        if self.env.context.get('mp_qr_no_discount_recalc'):
            return True
        relevant = lines.filtered(lambda l: not l._mp_qr_is_discount_line())
        if not relevant:
            return True
        orders = orders.filtered(lambda o: o.state in ('draft', 'sent'))
        if not orders:
            return True
        try:
            # mp_qr_line_change: autoriza el recálculo AUNQUE is_admin sea
            # True. Sólo se pone acá (modificación de líneas); generar el QR,
            # confirmar y revertir NO lo llevan.
            orders.with_context(
                mp_qr_no_discount_recalc=True,
                mp_qr_line_change=True,
            )._mp_qr_recalc_discount()
        except Exception:
            _logger.exception(
                'MP QR: no se pudo recalcular el descuento tras cambiar líneas '
                'de los pedidos %s', ', '.join(orders.mapped('name')))
        return True

    def write(self, vals):
        res = super().write(vals)
        if RECALC_FIELDS.intersection(vals):
            self._mp_qr_recalc_orders(self.mapped('order_id'), self)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._mp_qr_recalc_orders(lines.mapped('order_id'), lines)
        return lines

    def unlink(self):
        orders = self.mapped('order_id')
        lines = self
        # Calcular ANTES de borrar: luego los registros ya no son legibles.
        relevant = lines.filtered(lambda l: not l._mp_qr_is_discount_line())
        res = super().unlink()
        if relevant and not self.env.context.get('mp_qr_no_discount_recalc'):
            try:
                orders.filtered(
                    lambda o: o.state in ('draft', 'sent')
                ).with_context(
                    mp_qr_no_discount_recalc=True,
                    mp_qr_line_change=True,
                )._mp_qr_recalc_discount()
            except Exception:
                _logger.exception(
                    'MP QR: no se pudo recalcular el descuento tras borrar líneas')
        return res
