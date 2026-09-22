import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class MpLinkMultiWizard(models.TransientModel):
    _name = 'mp.link.multi.wizard'
    _description = 'Wizard para generar Link de Pago MP'

    order_ids = fields.Many2many('sale.order', string='Pedidos', readonly=True)
    partner_id = fields.Many2one('res.partner', string='Cliente', compute='_compute_partner', store=True)
    total_amount = fields.Monetary('Monto Total', compute='_compute_total', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    mp_link = fields.Char('Link de Pago', readonly=True)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Generado'),
    ], default='draft', string='Estado')

    @api.depends('order_ids.partner_id')
    def _compute_partner(self):
        for wizard in self:
            partners = wizard.order_ids.mapped('partner_id')
            wizard.partner_id = partners[0] if len(partners) == 1 else False

    @api.depends('order_ids.amount_total')
    def _compute_total(self):
        for wizard in self:
            wizard.total_amount = sum(wizard.order_ids.mapped('amount_total'))

    def _validate_orders(self):
        """Validate orders before generating link."""
        self.ensure_one()

        if not self.order_ids:
            raise UserError('No hay pedidos seleccionados.')

        # Validate all orders are in valid state
        invalid_orders = self.order_ids.filtered(lambda s: s.state not in ('draft', 'sent', 'sale'))
        if invalid_orders:
            raise UserError('Los pedidos %s no están en un estado válido.' % ', '.join(invalid_orders.mapped('name')))

        # Validate same company
        companies = self.order_ids.mapped('company_id')
        if len(companies) > 1:
            raise UserError('No se pueden combinar pedidos de diferentes compañías.')

        # Validate no Consumidor Final
        consumidor_final = self.order_ids.filtered(
            lambda s: s.partner_id and 'Consumidor Final' in s.partner_id.name
        )
        if consumidor_final:
            raise UserError(
                'No se pueden generar links de pago para pedidos con Consumidor Final. '
                'Pedidos: %s' % ', '.join(consumidor_final.mapped('name'))
            )

        # Validate all orders have the same partner
        partners = self.order_ids.mapped('partner_id')
        if len(partners) > 1:
            raise UserError(
                'Todos los pedidos deben tener el mismo cliente. '
                'Clientes encontrados: %s' % ', '.join(partners.mapped('name'))
            )

        # Check invoices exist for draft orders
        for so in self.order_ids:
            if not so.invoice_ids and so.state == 'draft':
                raise UserError('El pedido %s no tiene factura asociada. Confirme el pedido primero.' % so.name)

    def action_generate_link(self):
        """Generate the MP payment link for selected orders."""
        self.ensure_one()
        self._validate_orders()

        companies = self.order_ids.mapped('company_id')
        provider = self.env["payment_mercadopago_point.mercadopago"].sudo().search([
            ('company_id.id', '=', companies[0].id)
        ], limit=1)

        if not provider:
            raise UserError('No se encontró el proveedor de pago Mercado Pago para esta compañía.')

        # Use multi method even for single order (simplifies code)
        result = provider.create_order_link_multi(self.order_ids)

        # Store the link in all sale orders
        for so in self.order_ids:
            so.mp_link = result['link']

        self.write({
            'mp_link': result['link'],
            'state': 'done',
        })

        _logger.info('Link MP generado para órdenes: %s' % self.order_ids.mapped('name'))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mp.link.multi.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
