#-*- coding: utf-8 -*-
from urllib.parse import urlencode

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

    def _mp_link_payment(self, payment_id):
        """Pago de Mercado Pago por id, probando cada configuración.

        El webhook no sabe a qué compañía pertenece el pago, así que se prueba
        con cada configuración hasta que una lo devuelva. Siempre se consulta
        la API con nuestro token: un aviso falsificado no puede inventar un
        pago, sólo provoca una consulta que no encuentra nada.
        """
        payment_id = str(payment_id or '').strip()
        if not payment_id or not payment_id.isdigit():
            return {}
        configs = request.env['payment_mercadopago_point.mercadopago'].sudo().search([])
        for config in configs:
            try:
                payment = config.get_payment(payment_id) or {}
            except Exception:
                _logger.exception('MP link IPN: no se pudo consultar el pago %s',
                                  payment_id)
                continue
            if payment:
                return payment
        return {}

    @http.route("/mercadopago_point_payment/ipn", auth="public", type="http",
                methods=["GET", "POST"], csrf=False)
    def link_ipn(self, **kw):
        """Webhook de Mercado Pago para los links de pago (Checkout Pro).

        Es la vía que NO depende de que el cliente vuelva al comercio: si paga
        y cierra el navegador, Mercado Pago avisa igual acá y el pago se
        registra. El estado real se consulta siempre a la API (no se confía en
        el contenido del aviso) y `pay_mp_link()` vuelve a validar estado,
        referencia, moneda e importe antes de facturar.
        """
        try:
            data = request.httprequest.get_json(silent=True) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        # Formato nuevo: {"action": "payment.updated", "data": {"id": "123"}}
        # Formato IPN:   ?topic=payment&id=123  /  ?type=payment&data.id=123
        payment_id = None
        inner = data.get('data')
        if isinstance(inner, dict):
            payment_id = inner.get('id')
        elif inner:
            payment_id = inner
        if not payment_id:
            params = request.params or kw
            payment_id = (params.get('data.id') or params.get('id')
                          or params.get('payment_id'))
        _logger.info('MP link IPN recibido: %s (payment_id=%s)', data or kw, payment_id)
        payment = self._mp_link_payment(payment_id)
        if not payment:
            _logger.info('MP link IPN: Mercado Pago no devolvió el pago %s', payment_id)
            return ''
        reference = payment.get('external_reference') or ''
        if not reference:
            _logger.warning('MP link IPN: el pago %s no trae external_reference',
                            payment_id)
            return ''
        status = payment.get('status')
        if status != 'approved':
            # Mercado Pago avisa también los intentos rechazados/pendientes.
            # Sólo se registra el cobro acreditado; el resto se ignora (no se
            # ensucia el chatter del pedido con cada intento).
            _logger.info('MP link IPN: el pago %s está en estado %s; se ignora.',
                         payment_id, status or '-')
            return ''
        try:
            request.env['sale.order'].sudo().pay_mp_link({
                'payment_id': payment_id,
                'external_reference': reference,
            })
        except Exception:
            _logger.exception('MP link IPN: error al registrar el pago %s con '
                              'referencia %s', payment_id, reference)
            request.env.cr.rollback()
        return ''

    @http.route("/mercadopago_point_payment/success", auth="public", type="http")
    def payment_success(self, **kw):
        _logger.info('queue %s' % kw)
        processed = False
        reason = {}
        try:
            # La back_url de success lleva ?ref=<referencia> con NUESTRO formato
            # (el mismo que history.name y el que usa "Verificar pago"). Se
            # prefiere sobre el external_reference que reenvía MP, que a veces
            # no llega o llega con otro formato y hacía que pay_mp_link()
            # devolviera False mostrando "Estamos verificando su pago".
            if kw.get('ref'):
                kw['external_reference'] = kw['ref']
            # pay_mp_link valida el pago contra la API de Mercado Pago y
            # devuelve False si no se pudo verificar/registrar: la página de
            # éxito no debe afirmar que el pago se acreditó en ese caso.
            processed = request.env["sale.order"].sudo().pay_mp_link(kw, reason=reason)
            _logger.info('MP link success: processed=%s payment_id=%s ref=%s motivo=%s',
                         processed,
                         kw.get('payment_id') or kw.get('collection_id'),
                         kw.get('external_reference'),
                         reason.get('message'))
        except Exception:
            # El pago puede estar aprobado en Mercado Pago aunque falle el
            # registro: no freno la página, el detalle queda en el log y en el
            # chatter de las órdenes.
            _logger.exception('Error al procesar el pago del link de Mercado Pago')
            request.env.cr.rollback()
        try:
            attempt = int(kw.get('attempt') or 0)
        except (TypeError, ValueError):
            attempt = 0
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
        elif reason.get('retry') and attempt < 6:
            # Primera pasada: Mercado Pago puede tardar unos segundos en
            # devolver el pago por API (o en pasarlo a 'approved'). Se recarga
            # sola unas pocas veces; el registro es idempotente.
            params = dict(kw)
            params.pop('attempt', None)
            params['attempt'] = attempt + 1
            retry_url = '%s?%s' % (request.httprequest.base_url, urlencode(params))
            message = """
                <html>
                <head>
                    <title>Confirmando el pago</title>
                    <meta http-equiv="refresh" content="5;url=%s">
                </head>
                <body style="font-family: Arial; text-align: center; padding: 50px;">
                    <h1 style="color: #e67e22;">Estamos confirmando su pago</h1>
                    <p>Mercado Pago todavía no nos informó la acreditación.</p>
                    <p>Esta página se actualiza sola en unos segundos (intento %s de 6).
                       No cierre el navegador.</p>
                </body>
                </html>
                """ % (retry_url.replace('&', '&amp;'), attempt + 2)
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
