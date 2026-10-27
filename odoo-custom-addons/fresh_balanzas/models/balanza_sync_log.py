from odoo import fields, models


class BalanzaSyncLog(models.Model):
    _name = 'balanza.sync.log'
    _description = 'Log de sincronización de balanza'
    _order = 'create_date desc'

    scale_id = fields.Many2one('balanza.scale', string='Balanza', required=True, ondelete='cascade')
    sync_type = fields.Selection([
        ('product', 'Productos'),
        ('vendor', 'Vendedores'),
    ], string='Tipo', required=True)
    product_count = fields.Integer('Total registros', default=0)
    success_count = fields.Integer('Exitosos', default=0)
    error_count = fields.Integer('Errores', default=0)
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('success', 'Exitoso'),
        ('partial', 'Parcial'),
        ('error', 'Error'),
    ], string='Estado', default='pending')
    start_time = fields.Datetime('Inicio')
    end_time = fields.Datetime('Fin')
    log = fields.Text('Detalle')
    user_id = fields.Many2one('res.users', string='Usuario')
