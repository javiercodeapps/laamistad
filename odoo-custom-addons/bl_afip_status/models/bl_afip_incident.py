from odoo import api, fields, models

from .afip_error import (
    AUTH,
    CONFIG,
    NETWORK,
    SERVICE_UNAVAILABLE,
    SOAP_FAULT,
    SOAP_PARSE,
    TIMEOUT,
    TLS,
    UNKNOWN,
)


class BlAfipIncident(models.Model):
    _name = "bl.afip.incident"
    _description = "Incidente ARCA"
    _order = "create_date desc, id desc"

    status_id = fields.Many2one("bl.afip.status", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True)
    afip_ws = fields.Char(required=True, index=True)
    env_type = fields.Selection(
        [("production", "Produccion"), ("homologation", "Homologacion")], required=True, default="production"
    )
    operation = fields.Char(string="Operacion")
    endpoint = fields.Char(string="Endpoint")
    http_status = fields.Char(string="HTTP status")
    error_type = fields.Selection(
        [
            (SERVICE_UNAVAILABLE, "Servicio no disponible"),
            (SOAP_PARSE, "Respuesta invalida"),
            (TIMEOUT, "Timeout"),
            (NETWORK, "Red"),
            (TLS, "TLS"),
            (AUTH, "Autenticacion"),
            (SOAP_FAULT, "SOAP fault"),
            (CONFIG, "Configuracion"),
            (UNKNOWN, "Desconocido"),
        ],
        required=True,
        default=UNKNOWN,
        index=True,
    )
    user_message = fields.Text(string="Mensaje para usuario")
    error_summary = fields.Char(string="Resumen tecnico", size=255)
    response_excerpt = fields.Text(string="Extracto de respuesta")
    journal_id = fields.Many2one("account.journal", string="Diario", index=True)
    move_id = fields.Many2one("account.move", string="Comprobante", index=True)
    document_type_id = fields.Many2one("l10n_latam.document.type", string="Tipo de comprobante")
    degraded = fields.Boolean(string="Modo degradado")
    test_mode = fields.Boolean(string="Simulacion de prueba", readonly=True, index=True)
    resolved = fields.Boolean(default=False, index=True)
    resolved_at = fields.Datetime(string="Resuelto el")
    downtime_seconds = fields.Integer(string="Duracion en segundos")
    downtime_display = fields.Char(string="Duracion", compute="_compute_downtime_display")

    @api.depends("downtime_seconds")
    def _compute_downtime_display(self):
        for rec in self:
            seconds = max(rec.downtime_seconds or 0, 0)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            rest = seconds % 60
            rec.downtime_display = f"{hours:02d}:{minutes:02d}:{rest:02d}"
