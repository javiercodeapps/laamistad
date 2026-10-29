import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

MAX_PRICE_DIGITS = 6


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
    price_decimals = fields.Integer(
        'Decimales de precio', default=2, required=True,
        help='Cantidad de decimales con la que la balanza almacena el precio '
             '(0 a 4). El precio se envía como entero: precio × 10^decimales. '
             'Ej: con 2 decimales, 19.99 se envía como 019900.'
    )
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

    @api.constrains('price_decimals')
    def _check_price_decimals(self):
        for scale in self:
            if not 0 <= scale.price_decimals <= 4:
                raise ValidationError(
                    'Los decimales de precio deben estar entre 0 y 4.'
                )

    def _get_price_factor(self):
        """Factor de escala del precio en la balanza (10^decimales)."""
        self.ensure_one()
        return 10 ** self.price_decimals

    def _price_to_scale_raw(self, price):
        """Convierte un precio de Odoo al entero que almacena la balanza."""
        self.ensure_one()
        return int(round(float(price or 0.0) * self._get_price_factor()))

    def _raw_to_price_string(self, raw_price):
        """Formatea un precio crudo de la balanza para mostrarlo en logs."""
        self.ensure_one()
        raw_price = int(raw_price or 0)
        sign = '-' if raw_price < 0 else ''
        raw_price = abs(raw_price)
        if self.price_decimals == 0:
            return f'{sign}{raw_price}'
        factor = self._get_price_factor()
        return (
            f'{sign}{raw_price // factor}'
            f'.{raw_price % factor:0{self.price_decimals}d}'
        )

    def _price_fits(self, raw_price):
        """Indica si el precio crudo entra en el campo de 6 dígitos."""
        return 0 <= raw_price < 10 ** MAX_PRICE_DIGITS

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
