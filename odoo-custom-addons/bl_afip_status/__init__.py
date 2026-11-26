from . import models

import odoo
from odoo import api


def post_init_hook(cr, registry):
    """Firma (cr, registry): la que usa Odoo <= 16 (los hooks reciben cursor y
    registry, no env; eso recién cambia en 17)."""
    env = api.Environment(cr, odoo.SUPERUSER_ID, {})
    env["bl.afip.status"]._ensure_statuses()
