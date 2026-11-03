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
        processed = False
        try:
            # pay_mp_link valida el pago contra la API de Mercado Pago y
            # devuelve False si no se pudo verificar/registrar: la página de
            # éxito no debe afirmar que el pago se acreditó en ese caso.
            processed = request.env["sale.order"].sudo().pay_mp_link(kw)
        except Exception:
            # El pago puede estar aprobado en Mercado Pago aunque falle el
            # registro: no freno la página, el detalle queda en el log y en el
            # chatter de las órdenes.
            _logger.exception('Error al procesar el pago del link de Mercado Pago')
            request.env.cr.rollback()
        if processed:
            message = """
                <html>
                <head><title>Pago exitoso</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1 style="color: green;">¡Gracias por su compra!</h1>
                    <p>Su pago ha sido aprobado.</p>
                </body>
                </html>
                """
        else:
            message = """
                <html>
                <head><title>Pago en verificación</title></head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1 style="color: #e67e22;">Estamos verificando su pago</h1>
                    <p>En este momento no pudimos confirmar la acreditación del pago.</p>
                    <p>Si el cobro se realizó, quedará registrado en el comercio.
                       Ante cualquier duda, comuníquese con nosotros.</p>
                </body>
                </html>
                """
        return message

    @http.route("/mercadopago_point_payment/failure", auth="public", type="http")
    def payment_failure(self, **kw):
        _logger.info('queue failure %s' % kw)
        message = """
            <html>
            <head><title>Pago rechazado</title></head>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: #c0392b;">El pago no se pudo procesar</h1>
                <p>Puede intentar nuevamente con otro medio de pago.</p>
            </body>
            </html>
            """
        return message

    @http.route("/mercadopago_point_payment/pending", auth="public", type="http")
    def payment_pending(self, **kw):
        _logger.info('queue pending %s' % kw)
        message = """
            <html>
            <head><title>Pago pendiente</title></head>
            <body style="font-family: Arial; text-align: center; padding: 50px;">
                <h1 style="color: #e67e22;">Su pago está pendiente</h1>
                <p>Le avisaremos cuando se acredite.</p>
            </body>
            </html>
            """
        return message
