#-*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import logging
_logger = logging.getLogger(__name__)

class MercadopagoPointPaymemnt(http.Controller):
    @http.route("/mercadopago_point_payment", auth="public", type="json")
    def ipn(self, **kw):
        params = request.httprequest.full_path.split("?")[1].split("&")
        data = {}
        # TODO esto es feo pero por ahora resuelvo asi
        # el problema envian variables por GET
        # mediante un POST de JSON
        for p in params:
            i = p.split("=")
            data[i[0]] = i[1]
        request.env["payment.transaction"].sudo()._handle_notification_data(
            "mercado_pago_qr", data
        )
        return ""

    @http.route("/mercadopago_point_payment/success", auth="public", type="http")
    def success(self, **kw):
        data = kw
        _logger.info('mercadopago_point_payment/success data: %s' % data)

        # Get the preference to find associated sale orders
        preference_id = data.get('payment_id') or data.get('collection_id')
        external_ref = data.get('external_reference', '')

        # Check if external_reference contains multiple orders (comma separated)
        if external_ref and ',' in external_ref:
            # Multiple orders
            order_names = external_ref.split(',')
            sale_orders = request.env['sale.order'].sudo().search([
                ('name', 'in', order_names)
            ])
            _logger.info('Multi-order payment for: %s' % sale_orders.mapped('name'))

            for so in sale_orders:
                request.env['sale.order'].sudo().pay_mp_link_multi(data, so)
        else:
            # Single order (legacy behavior)
            request.env['sale.order'].sudo().pay_mp_link(data)

        message = """
            <html>
            <head><title>Pago exitoso</title></head>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: green;">¡Gracias por su compra!</h1>
                <p>Su pago ha sido aprobado.</p>
            </body>
            </html>
            """
        return message  
