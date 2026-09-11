# -*- coding: utf-8 -*-
import base64
from odoo import models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _get_afip_qr_image_data_uri(self):
        self.ensure_one()
        if not self.afip_qr_code:
            return ''
        barcode = self.env['ir.actions.report'].barcode(
            barcode_type='QR', value=self.afip_qr_code,
            width=300, height=300,
        )
        return 'data:image/png;base64,' + base64.b64encode(barcode).decode()
