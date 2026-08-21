import logging
import uuid
import requests
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 10
MERCADO_PAGO_API_ENDPOINT = "https://api.mercadopago.com"


class MercadoPagoRequest:
    def __init__(self, mp_bearer_token):
        self.mercado_pago_bearer_token = mp_bearer_token

    def _build_headers(self, test_scope=False, idempotency_key=True):
        headers = {
            "Authorization": f"Bearer {self.mercado_pago_bearer_token}",
            "Content-Type": "application/json",
        }
        if test_scope:
            headers["x-test-scope"] = "sandbox"
        if idempotency_key:
            headers["X-Idempotency-Key"] = str(uuid.uuid4())
        return headers

    def call_mercado_pago(self, method, endpoint, payload=None, test_scope=False):
        endpoint = MERCADO_PAGO_API_ENDPOINT + endpoint
        headers = self._build_headers(test_scope=test_scope)
        try:
            response = requests.request(
                method, endpoint, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 204:
                return response.ok
            elif response.ok:
                return response.json()
        except requests.exceptions.RequestException as error:
            _logger.warning("Cannot connect with Mercado Pago. Error: %s", error)
            return {"errorMessage": str(error)}
        except ValueError as error:
            _logger.warning("Cannot decode response json. Error: %s", error)
            return {"errorMessage": f"Cannot decode Mercado Pago response. Error: {error}"}
        raise UserError(response.text)
