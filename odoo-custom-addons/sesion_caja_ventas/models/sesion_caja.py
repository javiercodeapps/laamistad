from datetime import datetime


from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class SesionCaja(models.Model):
    _name = "sesion.caja"
    _description = "Sesión de Caja"

    name = fields.Char(
        string="Nombre", 
        required=True, 
        readonly=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('sesion.caja')
    )
    user_id = fields.Many2one('res.users', string="Responsable", default=lambda self: self.env.user)
    fecha_inicio = fields.Datetime(string="Inicio", default=fields.Datetime.now)
    fecha_fin = fields.Datetime(string="Fin")
    efectivo_inicio = fields.Float(string="Efectivo Inicial")
    efectivo_fin = fields.Float(string="Efectivo Final")
    diferencia = fields.Float(string="Diferencia", compute="_compute_diferencia", store=True)
    venta_total = fields.Float(string="Ventas en Efectivo", compute="_compute_venta_total", store=True)
    state = fields.Selection([
        ('abierta', 'Abierta'),
        ('cerrada', 'Cerrada')
    ], default="abierta", string="Estado")
    sale_order_ids = fields.One2many('sale.order', 'sesion_caja_id', string="Órdenes de Venta")

    @api.model_create_multi
    def create(self, vals_list):
        _logger.warning("SESION CAJA CREADA: %s", vals_list)
        return super(type(self), self).create(vals_list)

    # Patch temporal si querés probar rápido en runtime
    # self.env['sesion.caja'].__class__.create = create.__get__(self.env['sesion.caja'], type(self.env['sesion.caja']))
    # self.env['sesion.caja'].create({'efectivo_inicio': 100})


    @api.depends('efectivo_fin', 'efectivo_inicio', 'venta_total')
    def _compute_diferencia(self):
        for rec in self:
            rec.diferencia = rec.efectivo_fin - rec.efectivo_inicio - rec.venta_total

    @api.depends('sale_order_ids')
    def _compute_venta_total(self):
        for rec in self:
            total = 0
            for order in rec.sale_order_ids:
                pagos = order.invoice_ids.mapped('payment_ids')
                efectivo = pagos.filtered(lambda p: 'Efectivo' in p.journal_id.name)
                total += sum(efectivo.mapped('amount'))	
            rec.venta_total = total

    def cerrar_sesion(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cerrar Sesión de Caja',
            'res_model': 'cerrar.sesion.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id}
        }

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    sesion_caja_id = fields.Many2one('sesion.caja', string="Sesión de Caja")
