from odoo import _, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def _bl_afip_first_move_with_ws(self):
        for move in self:
            if move.journal_id.afip_ws and move.company_id.country_id.code == "AR":
                return move
        return self[:1]

    def do_pyafipws_request_cae(self):
        status_model = self.env["bl.afip.status"]

        down = status_model._precheck_before_invoicing(self)
        if down and status_model._get_param("block_invoice_when_down", True):
            message = down[0].last_error_message or _(
                "ARCA no esta disponible temporalmente para emitir comprobantes electronicos."
            )
            raise UserError(
                _(
                    "%s\n\nEl comprobante quedo sin emitir. Cuando el indicador ARCA de la barra superior vuelva a estar en verde, reintenta la facturacion."
                )
                % message
            )

        try:
            if status_model._bl_test_block_active() and status_model._get_param("test_block_mode", "soft") == "soft":
                raise RuntimeError("HTTP 503 simulado por el modo de prueba de BlackLabs")
            return super().do_pyafipws_request_cae()
        except UserError as error:
            move = self._bl_afip_first_move_with_ws()
            if not move or not move.journal_id.afip_ws:
                raise
            info = status_model._register_failure(
                move.company_id,
                move.journal_id.afip_ws,
                error,
                operation="CAESolicitar",
                move=move,
            )
            if info.get("error_type") == "unknown":
                raise
            raise UserError("%s\n\n%s" % (info["message"], info["summary"])) from error
        except Exception as error:
            move = self._bl_afip_first_move_with_ws()
            if not move or not move.journal_id.afip_ws:
                raise
            info = status_model._register_failure(
                move.company_id,
                move.journal_id.afip_ws,
                error,
                operation="CAESolicitar",
                move=move,
            )
            raise UserError("%s\n\n%s" % (info["message"], info["summary"])) from error
