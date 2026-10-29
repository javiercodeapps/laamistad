import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def action_send_to_scales(self):
        """Envía los productos seleccionados al wizard de precios de balanzas."""
        return self.env['balanza.verify.wizard'].action_open_for_products(
            self.mapped('product_variant_ids')
        )
