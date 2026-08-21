import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class MercadopagoQrPayment(http.Controller):

    @http.route("/mercadopago_qr_payment/ipn", auth="public", type="json", methods=["POST"])
    def ipn(self, **kw):
        data = request.jsonrequest or {}

        _logger.info("MercadoPago IPN received: %s", data)

        if not data:
            params = request.httprequest.full_path.split("?")
            if len(params) > 1:
                for p in params[1].split("&"):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        data[k] = v

        resource = data.get("resource", "")
        if resource and "/v1/orders/" in resource:
            order_id = resource.split("/v1/orders/")[-1].split("?")[0]
            data["id"] = order_id
            data["resource"] = order_id

        if not data.get("id") and not data.get("resource"):
            _logger.warning("MercadoPago IPN: no order ID found in data: %s", data)
            return ""

        request.env["payment.transaction"].sudo()._handle_notification_data(
            "mercado_pago_qr", data
        )
        return ""
