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

    def _get_tax_breakdown(self):
        """Return tax breakdown for Type A or Transparencia Fiscal for Type B/NC/ND."""
        self.ensure_one()
        if not self.invoice_line_ids:
            return {}

        letter = self.l10n_latam_document_type_id.l10n_ar_letter

        # Type A (Factura, NC, ND): show discriminated taxes
        if letter == 'A':
            sign = -1 if self.move_type in ('out_refund', 'in_refund') else 1

            tax_groups = {}
            for line in self.invoice_line_ids:
                vat_tax = line.tax_ids.filtered(lambda t: t.tax_group_id.l10n_ar_vat_afip_code)
                if not vat_tax:
                    continue
                afip_code = vat_tax[0].tax_group_id.l10n_ar_vat_afip_code
                if afip_code not in tax_groups:
                    tax_groups[afip_code] = {'base': 0.0, 'tax_amount': 0.0, 'name': vat_tax[0].tax_group_id.name}
                tax_groups[afip_code]['base'] += line.price_subtotal

            tax_lines = self.line_ids.filtered('tax_line_id')
            for tax_line in tax_lines:
                if tax_line.tax_line_id.tax_group_id.l10n_ar_vat_afip_code:
                    afip_code = tax_line.tax_line_id.tax_group_id.l10n_ar_vat_afip_code
                    if afip_code in tax_groups:
                        tax_groups[afip_code]['tax_amount'] += tax_line.amount_currency

            afip_code_labels = {
                '0': 'No Gravado', '1': 'Exento', '2': 'IVA 0%', '3': 'IVA 0%',
                '4': 'IVA 10,5%', '5': 'IVA 21%', '6': 'IVA 27%',
                '8': 'IVA 5%', '9': 'IVA 2,5%',
            }

            total_base = sign * sum(data['base'] for data in tax_groups.values())
            taxes = []
            for afip_code in sorted(tax_groups.keys()):
                data = tax_groups[afip_code]
                taxes.append({
                    'name': afip_code_labels.get(afip_code, data['name']),
                    'base': sign * data['base'],
                    'tax_amount': sign * data['tax_amount'],
                })

            return {
                'type': 'tax_breakdown',
                'total_base': total_base,
                'taxes': taxes,
            }

        # Type B (Factura, NC, ND): show Transparencia Fiscal
        if letter == 'B':
            iva_contenido = self.amount_total - self.amount_untaxed
            return {
                'type': 'transparencia_fiscal',
                'iva_contenido': iva_contenido,
            }

        return {}
