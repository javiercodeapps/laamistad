import logging
import re

from odoo import models

_logger = logging.getLogger(__name__)


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def get_pyafipws_last_invoice(self, document_type):
        self.ensure_one()
        if not self.afip_ws:
            return super().get_pyafipws_last_invoice(document_type)

        status_model = self.env["bl.afip.status"]
        try:
            if status_model._bl_test_block_active() and status_model._get_param("test_block_mode", "soft") == "soft":
                raise RuntimeError("HTTP 503 simulado por el modo de prueba de BlackLabs")
            result = super().get_pyafipws_last_invoice(document_type)
        except Exception as error:
            fallback = self._bl_afip_local_last_invoice(document_type)
            status_model._register_failure(
                self.company_id,
                self.afip_ws,
                error,
                operation="CompUltimoAutorizado",
                journal=self,
                document_type=document_type,
                degraded=True,
            )
            _logger.warning(
                "ARCA no disponible en get_pyafipws_last_invoice. Se usa fallback local en diario %s: %s",
                self.display_name,
                error,
            )
            return fallback

        status_model._register_success(self.company_id, self.afip_ws, operation="CompUltimoAutorizado")
        return result

    def _bl_afip_local_last_invoice(self, document_type):
        self.ensure_one()
        move = self.env["account.move"].sudo().search(
            [
                ("journal_id", "=", self.id),
                ("l10n_latam_document_type_id", "=", document_type.id),
                ("afip_auth_code", "!=", False),
                ("state", "!=", "cancel"),
                ("name", "!=", "/"),
            ],
            order="id desc",
            limit=1,
        )
        if not move or not move.name:
            return 0
        match = re.search(r"(\d+)\s*$", move.name.strip())
        return int(match.group(1)) if match else 0
