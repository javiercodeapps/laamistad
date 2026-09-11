import base64
import logging
from io import StringIO

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    def pricelist_itegra(self):
        # 1. Generar el contenido en memoria
        buffer = StringIO()
        for rec in self.env['product.template'].search([]):
            try:
                if rec.default_code and rec.barcode:
                    t = 'P' if rec.barcode[0] == '2' else 'N'
                    if float(rec.list_price) > 0:
                        buffer.write('%05d%06d%-26s%07.1f%s\n' % (
                            int(rec.default_code),
                            int(rec.default_code),
                            rec.name[:25],
                            float(rec.list_price),
                            t,
                        ))
            except Exception as e:
                _logger.warning("Error procesando producto %s: %s", rec.id, e)
                continue

        file_content = buffer.getvalue()
        buffer.close()

        # 2. Crear un attachment con el contenido (en base64)
        attachment = self.env['ir.attachment'].create({
            'name': 'CODIGOS_PLU_ODOO.TXT',
            'type': 'binary',
            'datas': base64.b64encode(file_content.encode('utf-8')),
            'mimetype': 'text/plain',
        })

        # 3. Devolver acción URL al endpoint de descarga de Odoo
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
