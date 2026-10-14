# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrderMpLinkWizard(models.TransientModel):
    _name = 'sale.order.mp.link.wizard'
    _description = 'Wizard para generar link de pago Mercado Pago con múltiples órdenes'

    sale_ids = fields.Many2many('sale.order', string='Órdenes de venta',
                                domain=[('state', '=', 'sent')],
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

    def _is_consumidor_final(self, partner):
        """Detecta clientes Consumidor Final (AFIP responsable tipo 5 o por nombre)."""
        return 'Consumidor Final' in (partner.name or '')

    def _validate_orders(self):
        self.ensure_one()
        orders = self.sale_ids
        if not orders:
            raise UserError(_("Debe seleccionar al menos una orden de venta."))
        not_sent = orders.filtered(lambda o: o.state != 'sent')
        if not_sent:
            raise UserError(_("Solo se pueden agrupar órdenes enviadas (estado 'Sent'). "
                              "Revise: %s") % ", ".join(not_sent.mapped('name')))
        if len(orders.partner_id) > 1:
            raise UserError(_("Todas las órdenes deben ser del mismo cliente. "
                              "Clientes encontrados: %s") % ", ".join(orders.partner_id.mapped('display_name')))
        partner = orders.partner_id
        if self._is_consumidor_final(partner):
            raise UserError(_("No se puede generar un link de pago para un cliente Consumidor Final (%s). "
                              "Debe seleccionar un cliente con nombre.") % partner.display_name)
        if len(orders.currency_id) > 1:
            raise UserError(_("Todas las órdenes deben tener la misma moneda."))
        if len(orders.company_id) > 1:
            raise UserError(_("Todas las órdenes deben pertenecer a la misma compañía."))
        return orders

    def action_create_link(self):
        self.ensure_one()
        orders = self._validate_orders()
        provider = self.env["payment_mercadopago_point.mercadopago"].sudo().search([
            ('company_id', '=', orders.company_id.id)], limit=1)
        if not provider:
            raise UserError(_("No se encontró la configuración de Mercado Pago Point "
                              "para la compañía %s.") % orders.company_id.name)
        _logger.info('Generando link MP múltiple para órdenes %s' % orders.mapped('name'))
        mp_link = provider.create_order_link(orders)
        orders.sudo().write({'mp_link': mp_link})
        self.write({'state': 'linked', 'mp_link': mp_link})
        # Reabro el wizard para mostrar el link generado con la opción de copiar
        action = self.env['ir.actions.act_window']._for_xml_id('scan_qr.action_mp_link_wizard')
        action['res_id'] = self.id
        action['context'] = dict(self.env.context)
        return action
