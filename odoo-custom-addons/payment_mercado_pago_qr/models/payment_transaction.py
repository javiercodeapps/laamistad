import json
import logging

from odoo import models, _
from odoo.tools.float_utils import json_float_round
from odoo.exceptions import ValidationError
from .mercado_pago_request import MercadoPagoRequest


_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):

    _inherit = "payment.transaction"

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != "mercado_pago_qr":
            return tx
        order_id = notification_data.get("resource") or notification_data.get("id")
        if not order_id:
            raise ValidationError(
                _("No order reference found in notification data.")
            )
        tx = self.search(
            [
                ("provider_reference", "=", str(order_id)),
                ("provider_code", "=", "mercado_pago_qr"),
            ]
        )
        if not tx:
            raise ValidationError(
                _("No transaction found matching reference %s.", order_id)
            )
        return tx

    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != "mercado_pago_qr":
            return
        order_id = notification_data.get("resource") or notification_data.get("id")
        if order_id and not self.provider_reference:
            self.provider_reference = str(order_id)
        self.mp_payment_order_get()

    def mp_payment_order_create(self):
        self.ensure_one()
        base_url = self.get_base_url()
        if "localhost" in base_url:
            base_url = "https://test2.frutasyverduraslaamistad.com/"

        amount_str = str(json_float_round(self.amount, 2))

        data = {
            "type": "qr",
            "total_amount": amount_str,
            "description": self.company_id.display_name or self.reference,
            "external_reference": self.reference,
            "expiration_time": "PT30M",
            "config": {
                "qr": {
                    "external_pos_id": self.provider_id.mp_external_pos_id,
                    "mode": "static",
                }
            },
            "transactions": {
                "payments": [
                    {
                        "amount": amount_str,
                    }
                ]
            },
            "items": [
                {
                    "title": self.reference,
                    "unit_price": amount_str,
                    "quantity": 1,
                    "unit_measure": "unit",
                }
            ],
        }

        mercado_pago = MercadoPagoRequest(self.provider_id.mercado_pago_qr_access_token)
        resp = mercado_pago.call_mercado_pago("post", "/v1/orders", data)
        _logger.debug("mp_payment_order_create(), response from Mercado Pago: %s", resp)

        if resp and resp.get("id"):
            self.provider_reference = resp["id"]
        elif resp and resp.get("error"):
            _logger.error("Error creating MP order: %s", resp)

        return resp

    def mp_payment_order_get(self):
        self.ensure_one()
        if not self.provider_reference:
            _logger.warning("mp_payment_order_get() called without provider_reference")
            return {}

        mercado_pago = MercadoPagoRequest(self.provider_id.mercado_pago_qr_access_token)
        resp = mercado_pago.call_mercado_pago(
            "get", f"/v1/orders/{self.provider_reference}"
        )
        _logger.info("mp_payment_order_get(), response from Mercado Pago: %s", resp)

        if not resp or resp.get("errorMessage"):
            return resp

        status = resp.get("status")
        status_detail = resp.get("status_detail", "")

        if status in ("created", "ready_to_process"):
            self._set_pending()
        elif status == "expired" or status_detail == "expired":
            self._set_canceled("The order is expired")
        elif status == "paid":
            total_paid = resp.get("total_amount")
            if total_paid:
                self.amount = float(total_paid)
            self._set_done()
            self._reconcile_after_done()
        elif status == "cancelled":
            self._set_canceled("The order was cancelled")

        return resp

    def mp_payment_order_cancel(self):
        self.ensure_one()
        if not self.provider_reference:
            _logger.warning("mp_payment_order_cancel() called without provider_reference")
            return {}

        mercado_pago = MercadoPagoRequest(self.provider_id.mercado_pago_qr_access_token)
        resp = mercado_pago.call_mercado_pago(
            "post", f"/v1/orders/{self.provider_reference}/cancel"
        )
        _logger.info("mp_payment_order_cancel(), response from Mercado Pago: %s", resp)
        return resp

    def action_mp_open_qr(self):
        view_id = self.env.ref("payment_mercado_pago_qr.payment_qr_wizard_view_form").id
        view = {
            "name": self.provider_id.display_name,
            "view_mode": "form",
            "view_id": view_id,
            "view_type": "form",
            "res_model": "payment.qr.wizard",
            "res_id": False,
            "type": "ir.actions.act_window",
            "target": "new",
            "context": {"default_tx_id": self.id},
        }
        return view
