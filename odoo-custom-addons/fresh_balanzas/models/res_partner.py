from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    kretz_vendor_code = fields.Integer(
        'Código de vendedor balanza',
        help='Código numérico de 2 dígitos para la balanza (1-36)',
    )
