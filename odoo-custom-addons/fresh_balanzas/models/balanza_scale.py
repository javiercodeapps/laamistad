import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class BalanzaScale(models.Model):
    _name = 'balanza.scale'
    _description = 'Balanza comercial'
    _order = 'name'

    name = fields.Char('Nombre', required=True)
    host = fields.Char('Dirección IP', required=True)
    port = fields.Integer('Puerto', default=1001, required=True)
    timeout = fields.Integer('Timeout (seg)', default=10)
    active = fields.Boolean('Activa', default=True)
    brand = fields.Selection([
        ('kretz', 'Kretz'),
        ('systel', 'Systel'),
        ('other', 'Otra'),
    ], string='Marca', default='kretz', required=True)

    department_code = fields.Integer('Código de departamento', default=1)
    family_code = fields.Integer('Código de familia', default=0)
    label_code = fields.Integer('Código de etiqueta', default=1)
    equipment_number = fields.Integer(
        'Número de equipo', default=1,
        help='ID del equipo en la red Kretz (01-32). Debe coincidir con el '
             'número configurado en la balanza (ej: equipo 05 en iTegra).'
    )

    product_ids = fields.Many2many(
        'product.product', 'balanza_scale_product_rel',
        'scale_id', 'product_id', string='Productos a sincronizar'
    )
    sync_all_products = fields.Boolean('Sincronizar todos los productos', default=True)
    sync_vendors = fields.Boolean('Sincronizar vendedores', default=True)

    last_sync_product = fields.Datetime('Última sinc. productos')
    last_sync_vendor = fields.Datetime('Última sinc. vendedores')
    sync_log_ids = fields.One2many('balanza.sync.log', 'scale_id', string='Logs de sincronización')

    _sql_constraints = [
        ('name_unique', 'UNIQUE(name)', 'El nombre de la balanza debe ser único'),
    ]

    def _get_protocol(self):
        """Retorna la instancia del protocolo según la marca."""
        self.ensure_one()
        if self.brand == 'kretz':
            from ..protocols.kretz import KretzProtocol
            return KretzProtocol(
                self.host, self.port, self.timeout,
                equip_id=self.equipment_number,
            )
        raise ValueError(f'Marca no soportada: {self.brand}')

    def test_connection(self):
        """Prueba la conexión con la balanza."""
        self.ensure_one()
        try:
            proto = self._get_protocol()
            with proto:
                ok = proto.test_communication(beep=True)
            if ok:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Éxito',
                        'message': f'Conexión exitosa con {self.name}',
                        'sticky': False,
                        'type': 'success',
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Error',
                        'message': 'La balanza respondió con error',
                        'sticky': False,
                        'type': 'danger',
                    }
                }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error de conexión',
                    'message': str(e),
                    'sticky': False,
                    'type': 'danger',
                }
            }

    def action_sync_products(self):
        """Abre el wizard de sincronización de productos."""
        self.ensure_one()
        wizard = self.env['balanza.sync.wizard'].create({
            'scale_ids': [(6, 0, self.ids)],
            'sync_type': 'product',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'balanza.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wizard.id,
        }

    def action_sync_vendors(self):
        """Abre el wizard de sincronización de vendedores."""
        self.ensure_one()
        wizard = self.env['balanza.sync.wizard'].create({
            'scale_ids': [(6, 0, self.ids)],
            'sync_type': 'vendor',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'balanza.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wizard.id,
        }

    def action_verify_prices(self):
        """Abre el wizard de verificación de precios."""
        self.ensure_one()
        wizard = self.env['balanza.verify.wizard'].create({
            'scale_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'balanza.verify.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wizard.id,
        }

    def cron_sync_products(self):
        """Cron: sincroniza productos en balanzas activas."""
        scales = self.search([
            ('active', '=', True),
            ('sync_all_products', '=', True),
        ])
        for scale in scales:
            scale.action_sync_products()

    def cron_sync_vendors(self):
        """Cron: sincroniza vendedores en balanzas activas."""
        scales = self.search([
            ('active', '=', True),
            ('sync_vendors', '=', True),
        ])
        for scale in scales:
            scale.action_sync_vendors()
