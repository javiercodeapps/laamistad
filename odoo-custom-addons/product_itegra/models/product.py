# controllers/main.py
from odoo import http
from odoo.http import request, content_disposition
from io import BytesIO


class PritegraController(http.Controller):

    @http.route('/product_itegra/plu.txt', type='http', auth='user')
    def download_plu(self, **kwargs):
        buffer = BytesIO()
        for rec in request.env['product.template'].search([]):
            try:
                if rec.default_code and rec.barcode:
                    t = 'P' if rec.barcode[0] == '2' else 'N'
                    if float(rec.list_price) > 0:
                        line = '%05d%06d%-26s%07.1f%s\n' % (
                            int(rec.default_code), int(rec.default_code),
                            rec.name[:25], float(rec.list_price), t,
                        )
                        buffer.write(line.encode('utf-8'))
            except Exception:
                continue

        return request.make_response(
            buffer.getvalue(),
            headers=[
                ('Content-Type', 'text/plain'),
                ('Content-Disposition', content_disposition('CODIGOS_PLU_ODOO.TXT')),
            ],
        )
