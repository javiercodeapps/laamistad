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

        # El IPN de Mercado Pago llega DUPLICADO (reintentos + evento por orden
        # y por pago) y puede coincidir con el botón 'Check order' del wizard.
        # Sin lock, dos requests procesan el mismo pago en paralelo: ambos leen
        # state != 'done' antes de que el otro haga commit, ambos confirman el
        # pedido/facturan, y el segundo revienta con violaciones de unique
        # (p.ej. 'duplicate key ... mail_followers ... already exists'). El row
        # lock serializa: el segundo request espera a que el primero haga
        # commit, relee el estado y sale sin reprocesar.
        self.env.cr.execute(
            "SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE",
            [self.id],
        )
        # La fila pudo cambiar mientras esperábamos el lock: re-leerla.
        self.invalidate_recordset(['state', 'amount'])

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
        elif status == "paid" or status_detail == 'accredited':
            # Otro request (IPN duplicado o Check order concurrente) ya
            # procesó este pago: nada que confirmar ni facturar de nuevo.
            if self.state == 'done':
                _logger.info(
                    "MP QR %s: pago ya procesado por otro request; se ignora.",
                    self.reference)
                return resp
            # Recién acá se confirma el presupuesto y se factura (cuando
            # scan_qr está instalado). Antes de marcar 'done' se revalidan el
            # importe y la referencia contra la respuesta de la API: si falla,
            # NO se factura, NO se registra el cobro y la transacción sigue
            # pendiente para poder reintentar.
            prepare = getattr(self, '_mp_qr_prepare_documents', None)
            if prepare:
                try:
                    prepared = prepare(resp, expected_amount=self.amount)
                except Exception:
                    _logger.exception(
                        "MP QR %s: error al preparar los documentos de venta", self.reference)
                    prepared = False
                if prepared is False:
                    _logger.warning("MP QR %s: pago no verificado; no se factura.",
                                    self.reference)
                    return resp
            total_paid = resp.get("total_amount")
            if total_paid:
                self.amount = float(total_paid)
            self._set_done()
            self._reconcile_after_done()
        elif status == "cancelled":
            # Ya cancelado por otro request (IPN de vencimiento duplicado o
            # botón 'Cancel order'): no volver a revertir el pedido.
            if self.state == 'cancel':
                return resp
            self._set_canceled("The order was cancelled")

        return resp

    def mp_payment_order_cancel(self):
        self.ensure_one()
        if not self.provider_reference:
            _logger.warning("mp_payment_order_cancel() called without provider_reference")
            return {}

        # Mismo lock que mp_payment_order_get(): el botón 'Cancel order' y un
        # IPN de vencimiento/cancelación pueden llegar a la vez. Ambos toman el
        # lock de la fila ANTES de tocar cualquier otro registro, por lo que no
        # hay deadlock; el segundo request ve la transacción ya cancelada.
        self.env.cr.execute(
            "SELECT id FROM payment_transaction WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(['state'])

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
