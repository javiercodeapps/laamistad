from . import models

import odoo
from odoo import api


def post_init_hook(cr, registry):
    """Initialize AFIP service monitors after module installation.

    Firma (cr, registry): es la que usa Odoo <= 16 (los hooks reciben cursor
    y registry, no env; eso recién cambia en 17)."""
    env = api.Environment(cr, odoo.SUPERUSER_ID, {})
    env['afip.service.status'].sudo().initialize_services()
