# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrderMpLinkWizard(models.TransientModel):
    _name = 'sale.order.mp.link.wizard'
    _description = 'Wizard para generar link de pago Mercado Pago con múltiples órdenes'

    sale_ids = fields.Many2many('sale.order', string='Órdenes de venta',
                                domain=[('state', 'in', ['sent', 'sale'])],
                                default=lambda self: self._default_sale_ids())
    currency_id = fields.Many2one('res.currency', string='Moneda', compute='_compute_amounts')
    amount_total = fields.Monetary(string='Total', compute='_compute_amounts', currency_field='currency_id')
    state = fields.Selection([('draft', 'Borrador'), ('linked', 'Link generado')],
                             string='Estado', default='draft', required=True)
    mp_link = fields.Char(string='Link de pago', readonly=True, copy=False)

    @api.model
    def _default_sale_ids(self):
        """Carga las órdenes seleccionadas en la lista (active_ids del contexto)."""
        ctx = self.env.context
        if ctx.get('active_model') == 'sale.order' and ctx.get('active_ids'):
            return [(6, 0, ctx['active_ids'])]
        return []

    @api.depends('sale_ids', 'sale_ids.amount_total')
    def _compute_amounts(self):
        for wizard in self:
            wizard.currency_id = wizard.sale_ids[:1].currency_id
            wizard.amount_total = sum(wizard.sale_ids.mapped('amount_total'))

    def _get_orders(self):
        """Devuelve las órdenes del wizard.

        `sale_ids` es un campo de solo lectura en la vista; el cliente web puede
        guardar vacío su valor al crear el wizard en el diálogo. Por eso, si llegó
        vacío, se recuperan las órdenes del contexto (`active_ids` del action, que
        el botón conserva al llamar al método).
        """
        self.ensure_one()
        orders = self.sale_ids
        if not orders:
            ctx = self.env.context
            if ctx.get('active_model') == 'sale.order' and ctx.get('active_ids'):
                orders = self.env['sale.order'].browse(ctx['active_ids'])
        return orders

    def _validate_orders(self):
        self.ensure_one()
        return self._get_orders()._mp_link_validate_orders()

    def action_create_link(self):
        self.ensure_one()
        _logger.info(
            'action_create_link: sale_ids=%s active_ids=%s (active_model=%s)',
            self.sale_ids.ids, self.env.context.get('active_ids'),
            self.env.context.get('active_model'))
        orders = self._validate_orders()
        # Si el cliente descartó sale_ids al guardar (campo readonly), lo
        # restauramos para que el wizard reabierto muestre las órdenes y el total.
        if orders != self.sale_ids:
            self.write({'sale_ids': [(6, 0, orders.ids)]})
        _logger.info('Generando link MP múltiple para órdenes %s' % orders.mapped('name'))
        mp_link = orders[0]._mp_link_generate_for_orders(orders)
        self.write({'state': 'linked', 'mp_link': mp_link})
        # Reabro el wizard para mostrar el link generado con la opción de copiar
        action = self.env['ir.actions.act_window']._for_xml_id('scan_qr.action_mp_link_wizard')
        action['res_id'] = self.id
        action['context'] = dict(self.env.context)
        return action

    def action_check_payment(self):
        """Consulta Mercado Pago desde el wizard (por si no llegó el callback).

        Si el pago se registra, se cierra el wizard; el aviso lo muestra el
        propio método del pedido."""
        self.ensure_one()
        orders = self._get_orders()
        if not orders:
            raise UserError(_("No hay órdenes para verificar."))
        result = orders[:1].action_mp_link_check_payment()
        if isinstance(result, dict) and result.get('tag') == 'display_notification':
            result['params']['next'] = {'type': 'ir.actions.act_window_close'}
        return result
