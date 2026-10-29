import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def action_send_to_scales(self):
        """Envía las variantes seleccionadas al wizard de precios de balanzas."""
        return self.env['balanza.verify.wizard'].action_open_for_products(self)
