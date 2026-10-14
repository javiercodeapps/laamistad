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
    def payment_success(self, **kw):
        _logger.info('queue %s' % kw)
        try:
            request.env["sale.order"].sudo().pay_mp_link(kw)
        except Exception:
            # El pago ya está aprobado en Mercado Pago, no freno la página de
            # éxito: el detalle del error queda en el log y en el chatter.
            _logger.exception('Error al procesar el pago del link de Mercado Pago')
            request.env.cr.rollback()
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
