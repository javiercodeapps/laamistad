from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
from io import StringIO

import logging
_logger = logging.getLogger(__name__)
class ProductTemplate(models.Model):
    _inherit = "product.template"

    def pricelist_itegra(self):
        fp = open('/opt/odoo16/odoo-custom-addons/product_itegra/static/CODIGOS_PLU_ODOO.TXT','w')
        for rec in self.env['product.template'].search([]):
            try:
                if rec.default_code and rec.barcode:
                    if rec.barcode[0] == '2':
                        t='P'
                    else:
                        t='N'
                    if float(rec.list_price) > 0:
                        fp.write('%05d%06d%-26s%07.1f%s\n' % (int(rec.default_code),int(rec.default_code),rec.name[:25],float(rec.list_price),t) )
            except:
                continue
        fp.close()
        return {
                'type': 'ir.actions.act_url',
                'url': 'product_itegra/static/CODIGOS_PLU_ODOO.TXT',
                'context': self._context, 
                'target': 'self',
        }
