from werkzeug import urls

from odoo import _, fields, models


class PaymentQrWizard(models.TransientModel):
    _name = "payment.qr.wizard"
    _description = "Payment QR"

    tx_id = fields.Many2one("payment.transaction")
    state = fields.Selection(
        string="Status",
        selection=[
            ("draft", "Draft"),
            ("pending", "Pending"),
            ("authorized", "Authorized"),
            ("done", "Confirmed"),
            ("cancel", "Canceled"),
            ("error", "Error"),
        ],
        related="tx_id.state",
    )
    amount = fields.Monetary(
        string="Amount", currency_field="currency_id", related="tx_id.amount"
    )
    currency_id = fields.Many2one(
        string="Currency", comodel_name="res.currency", related="tx_id.currency_id"
    )

    provider_id = fields.Many2one("payment.provider", related="tx_id.provider_id")
    mp_qr_image = fields.Binary(
        string="QR", attachment=True, related="provider_id.mp_qr_image"
    )

    def action_check_status(self):
        self.tx_id.sudo().mp_payment_order_get()
        if self.state == "done":
            return {"type": "ir.actions.act_window_close"}
        if self.state in ("cancel", "error"):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Mercado Pago QR"),
                    "message": _("El QR venció, fue cancelado o el pago fue rechazado. "
                                 "El pedido sigue en presupuesto y sin factura: puede "
                                 "elegir otro medio de pago o generar un QR nuevo."),
                    "type": "warning",
                    "sticky": True,
                    "next": {"type": "ir.actions.act_window_close"},
                },
            }
        return self.tx_id.sudo().action_mp_open_qr()

    def action_cancel_order(self):
        self.tx_id.sudo().mp_payment_order_cancel()
        self.tx_id.sudo()._set_canceled(f"Canceled by user {self.env.user.name}")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Mercado Pago QR"),
                "message": _("Se canceló el código QR. El pedido sigue en presupuesto "
                             "y sin factura; puede continuar con otro medio de pago."),
                "type": "info",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
