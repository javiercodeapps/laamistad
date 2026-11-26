import logging
import os
import ssl
import subprocess
import time
from collections import defaultdict
from datetime import timedelta

import odoo
import requests
from requests.adapters import HTTPAdapter
from urllib3 import PoolManager

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import UserError

from .afip_error import (
    AUTH,
    CONFIG,
    NETWORK,
    SERVICE_DOWN_TYPES,
    SERVICE_UNAVAILABLE,
    SOAP_FAULT,
    SOAP_PARSE,
    TIMEOUT,
    TLS,
    UNKNOWN,
    classify_afip_error,
)

_logger = logging.getLogger(__name__)


# Severidad para agregar el peor estado de todos los servicios.
LEVEL_SEVERITY = {"ok": 0, "loading": 1, "warning": 2, "error": 3, "down": 4}
TEST_BLOCK_PARAM = "bl_afip_status.test_block_until"
BL_AFIP_FIREWALL_SCRIPT = "/usr/local/bin/bl_afip_firewall_block.sh"


class _CipherAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = ssl.create_default_context()
        context.set_ciphers("DEFAULT:@SECLEVEL=1")
        pool_kwargs["ssl_context"] = context
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs)


class BlAfipStatus(models.Model):
    _name = "bl.afip.status"
    _description = "Estado de servicio ARCA"
    _order = "company_id, afip_ws"
    _rec_name = "name"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", required=True, ondelete="cascade", index=True)
    afip_ws = fields.Char(required=True, index=True)
    env_type = fields.Selection(
        [("production", "Produccion"), ("homologation", "Homologacion")], required=True, default="production"
    )
    state = fields.Selection(
        [("ok", "Operativo"), ("down", "Caido"), ("error", "Error de configuracion"), ("unknown", "Sin verificar")],
        required=True,
        default="unknown",
        index=True,
    )
    endpoint = fields.Char()
    last_check = fields.Datetime(readonly=True)
    last_ok = fields.Datetime(readonly=True)
    down_since = fields.Datetime(readonly=True)
    consecutive_failures = fields.Integer(default=0)
    last_error_type = fields.Selection(
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
        default=UNKNOWN,
    )
    last_error_message = fields.Text(readonly=True)
    last_error_summary = fields.Char(size=255, readonly=True)
    last_operation = fields.Char(readonly=True)
    app_server_status = fields.Char(readonly=True)
    db_server_status = fields.Char(readonly=True)
    auth_server_status = fields.Char(readonly=True)
    response_time = fields.Float(string="Tiempo de respuesta (s)", digits=(10, 3), readonly=True)
    incident_ids = fields.One2many("bl.afip.incident", "status_id")
    incident_count = fields.Integer(compute="_compute_incident_count")

    _sql_constraints = [
        (
            "bl_afip_status_company_ws_env_uniq",
            "unique(company_id, afip_ws, env_type)",
            "Ya existe un estado ARCA para esta compania, webservice y entorno.",
        )
    ]

    @api.depends("company_id", "afip_ws", "env_type")
    def _compute_name(self):
        for rec in self:
            company = rec.company_id.display_name or "Compania"
            ws = rec.afip_ws or "-"
            env = "PROD" if rec.env_type == "production" else "HOMO"
            rec.name = f"{company} - {ws} ({env})"

    @api.depends("incident_ids")
    def _compute_incident_count(self):
        grouped = self.env["bl.afip.incident"].read_group(
            [("status_id", "in", self.ids)], ["status_id"], ["status_id"]
        )
        mapped = {item["status_id"][0]: item["status_id_count"] for item in grouped}
        for rec in self:
            rec.incident_count = mapped.get(rec.id, 0)

    @api.model
    def _get_param(self, key, default):
        value = self.env["ir.config_parameter"].sudo().get_param(f"bl_afip_status.{key}")
        if value in (None, ""):
            return default
        if isinstance(default, bool):
            return str(value).strip().lower() in ("1", "true", "t", "yes", "y", "on")
        if isinstance(default, int):
            try:
                return int(value)
            except Exception:
                return default
        if isinstance(default, float):
            try:
                return float(value)
            except Exception:
                return default
        return value

    @api.model
    def _probe_ttl(self):
        return max(self._get_param("probe_ttl_seconds", 300), 0)

    @api.model
    def _bl_test_block_active(self):
        """True si hay un bloqueo de prueba vigente. Vencido = no bloqueado."""
        raw = self.env["ir.config_parameter"].sudo().get_param(TEST_BLOCK_PARAM)
        if not raw:
            return False
        try:
            until = fields.Datetime.from_string(raw)
        except Exception:
            return False
        return bool(until and until > fields.Datetime.now())

    @api.model
    def _bl_test_block_info(self):
        """Datos del bloqueo vigente para el systray y los mensajes."""
        if not self._bl_test_block_active():
            return {}
        params = self.env["ir.config_parameter"].sudo()
        return {
            "active": True,
            "mode": params.get_param("bl_afip_status.test_block_mode", "soft"),
            "until": params.get_param(TEST_BLOCK_PARAM),
        }

    @api.model
    def _bl_test_error(self):
        """Falla simulada, con la misma firma que una caida real de ARCA."""
        info = classify_afip_error(
            RuntimeError("HTTP 503 simulado por el modo de prueba de BlackLabs"),
            response_excerpt="<h1>Service Unavailable</h1> [SIMULADO - modo de prueba BlackLabs]",
            http_status=503,
        )
        info.update(
            {
                "ok": False,
                "response_excerpt": info.get("excerpt"),
                "http_status": "503",
                "response_time": 0.0,
                "test_mode": True,
            }
        )
        return info

    @api.model
    def _http_timeout(self):
        return max(self._get_param("http_timeout", 8), 1)

    @api.model
    def _status_domain(self, company_id, afip_ws, env_type):
        return [("company_id", "=", company_id), ("afip_ws", "=", afip_ws), ("env_type", "=", env_type)]

    @api.model
    def _get_status(self, company_id, afip_ws, env_type=None):
        company = (
            company_id
            if isinstance(company_id, models.BaseModel)
            else self.env["res.company"].browse(int(company_id))
        )
        if not env_type:
            env_type = self.env["res.company"]._get_environment_type()
        status = self.sudo().search(self._status_domain(company.id, afip_ws, env_type), limit=1)
        if status:
            return status
        endpoint = self._bl_resolve_endpoint(afip_ws, env_type)
        return self.sudo().create(
            {
                "company_id": company.id,
                "afip_ws": afip_ws,
                "env_type": env_type,
                "state": "unknown",
                "endpoint": endpoint,
            }
        )

    @api.model
    def _fe_journals(self, companies=None):
        domain = [("type", "=", "sale"), ("l10n_latam_use_documents", "=", True)]
        if companies:
            company_ids = companies.ids if isinstance(companies, models.BaseModel) else companies
            domain.append(("company_id", "in", company_ids))
        journals = self.env["account.journal"].sudo().search(domain)
        return journals.filtered(lambda journal: bool(journal.afip_ws))

    @api.model
    def _ensure_statuses(self, companies=None):
        statuses = self.browse()
        for journal in self._fe_journals(companies=companies):
            statuses |= self._get_status(journal.company_id, journal.afip_ws)
        # WSAA autentica a todos los webservices: si se cae no hay token y no
        # se puede facturar aunque WSFE responda. Se monitorea por compania.
        for company in statuses.mapped("company_id"):
            statuses |= self._get_status(company, "wsaa")
        return statuses

    @api.model
    def _bl_resolve_endpoint(self, afip_ws, env_type):
        """WSAA no esta en el mapa de webservices de negocio: su URL sale de
        get_afip_login_url y hay que pedirle el WSDL explicitamente."""
        connection = self.env["afipws.connection"].sudo()
        if afip_ws == "wsaa":
            url = connection.get_afip_login_url(env_type)
            if url and "?" not in url:
                url = "%s?wsdl" % url
            return url
        return connection.get_afip_ws_url(afip_ws, env_type)

    def _do_http_probe(self):
        self.ensure_one()
        if self._bl_test_block_active():
            result = self._bl_test_error()
            result["endpoint"] = self.endpoint or self._bl_resolve_endpoint(self.afip_ws, self.env_type)
            return result

        endpoint = self.endpoint or self._bl_resolve_endpoint(self.afip_ws, self.env_type)
        if not endpoint:
            info = classify_afip_error(UserError("No se pudo determinar el endpoint ARCA"))
            info.update({"ok": False, "response_excerpt": "", "http_status": False, "endpoint": False})
            return info

        session = requests.Session()
        session.mount("https://", _CipherAdapter())

        response_excerpt = ""
        http_status = False
        started = time.monotonic()
        elapsed = 0.0
        try:
            response = session.get(endpoint, timeout=self._http_timeout())
            elapsed = time.monotonic() - started
            http_status = response.status_code
            response_excerpt = (response.text or "")[:2000]
            lower_excerpt = response_excerpt.lower()
            is_xml = lower_excerpt.startswith("<?xml") or "<definitions" in lower_excerpt or "<wsdl:" in lower_excerpt
            if response.status_code == 200 and is_xml:
                return {
                    "ok": True,
                    "response_excerpt": response_excerpt,
                    "http_status": str(response.status_code),
                    "endpoint": endpoint,
                    "response_time": elapsed,
                }
            info = classify_afip_error(
                RuntimeError(f"HTTP {response.status_code} al consultar endpoint ARCA"),
                response_excerpt=response_excerpt,
                http_status=response.status_code,
            )
            info.update(
                {
                    "ok": False,
                    "response_excerpt": response_excerpt,
                    "http_status": str(response.status_code),
                    "endpoint": endpoint,
                    "response_time": elapsed,
                }
            )
            return info
        except Exception as error:
            info = classify_afip_error(error, response_excerpt=response_excerpt, http_status=http_status)
            info.update({"ok": False, "response_excerpt": response_excerpt, "http_status": info.get("http_status"), "endpoint": endpoint, "response_time": time.monotonic() - started})
            return info
        finally:
            session.close()

    def _do_dummy_probe(self):
        self.ensure_one()
        if self._bl_test_block_active():
            result = self._bl_test_error()
            result.setdefault(
                "server_status",
                {
                    "app_server_status": "",
                    "db_server_status": "",
                    "auth_server_status": "",
                },
            )
            return result
        if self.afip_ws == "wsaa":
            # WSAA no expone FEDummy: solo se puede validar por HTTP.
            result = self._do_http_probe()
            result.setdefault(
                "server_status",
                {"app_server_status": "", "db_server_status": "", "auth_server_status": ""},
            )
            return result
        try:
            ws = self.company_id.get_connection(self.afip_ws).connect()
            ws.Dummy()
            app = getattr(ws, "AppServerStatus", "")
            db = getattr(ws, "DbServerStatus", "")
            auth = getattr(ws, "AuthServerStatus", "")
            server_status = {
                "app_server_status": app,
                "db_server_status": db,
                "auth_server_status": auth,
            }
            if app == db == auth == "OK":
                return {"ok": True, "server_status": server_status}
            info = classify_afip_error(RuntimeError(f"FEDummy no OK: App={app} Db={db} Auth={auth}"))
            info.update({"ok": False, "server_status": server_status, "response_excerpt": "", "http_status": False})
            return info
        except Exception as error:
            info = classify_afip_error(error)
            info.update(
                {
                    "ok": False,
                    "server_status": {
                        "app_server_status": "",
                        "db_server_status": "",
                        "auth_server_status": "",
                    },
                    "response_excerpt": "",
                    "http_status": info.get("http_status"),
                }
            )
            return info

    def _apply_failure(
        self,
        info,
        operation=None,
        journal_id=False,
        move_id=False,
        document_type_id=False,
        degraded=False,
        response_time=None,
    ):
        self.ensure_one()
        now = fields.Datetime.now()
        previous_state = self.state
        new_state = "down" if info.get("error_type") in SERVICE_DOWN_TYPES else "error"

        response_excerpt = info.get("excerpt") or info.get("response_excerpt") or ""
        http_status = info.get("http_status")

        if previous_state != "down" and new_state == "down" and not response_excerpt:
            evidence = self._probe_http(persist=False)
            response_excerpt = evidence.get("response_excerpt") or evidence.get("excerpt") or response_excerpt
            http_status = evidence.get("http_status") or http_status

        values = {
            "state": new_state,
            "endpoint": self.endpoint or info.get("endpoint") or self.endpoint,
            "last_check": now,
            "last_error_type": info.get("error_type", UNKNOWN),
            "last_error_message": info.get("message") or "",
            "last_error_summary": info.get("summary") or "",
            "last_operation": operation or "",
            "consecutive_failures": (self.consecutive_failures or 0) + 1,
        }
        if response_time is not None:
            values["response_time"] = round(response_time, 3)
        if new_state == "down" and not self.down_since:
            values["down_since"] = now
        if new_state == "error":
            values["down_since"] = False

        self.write(values)

        self.env["bl.afip.incident"].create(
            {
                "status_id": self.id,
                "company_id": self.company_id.id,
                "afip_ws": self.afip_ws,
                "env_type": self.env_type,
                "operation": operation or "",
                "endpoint": self.endpoint,
                "http_status": http_status,
                "error_type": info.get("error_type", UNKNOWN),
                "user_message": info.get("message") or "",
                "error_summary": info.get("summary") or "",
                "response_excerpt": response_excerpt,
                "journal_id": journal_id or False,
                "move_id": move_id or False,
                "document_type_id": document_type_id or False,
                "degraded": degraded,
                "test_mode": bool(info.get("test_mode")),
                "resolved": False,
            }
        )

        if new_state == "down":
            self._set_cron_active(True)

        if previous_state != new_state:
            self._notify_bus(event="down", downtime=False)

    def _apply_success(self, operation=None, server_status=None, response_time=None):
        self.ensure_one()
        previous_state = self.state
        now = fields.Datetime.now()
        down_since = self.down_since

        values = {
            "state": "ok",
            "last_check": now,
            "last_ok": now,
            "down_since": False,
            "consecutive_failures": 0,
            "last_error_type": UNKNOWN,
            "last_error_message": False,
            "last_error_summary": False,
            "last_operation": operation or "",
        }
        if response_time is not None:
            values["response_time"] = round(response_time, 3)
        if server_status:
            values.update(
                {
                    "app_server_status": server_status.get("app_server_status") or "",
                    "db_server_status": server_status.get("db_server_status") or "",
                    "auth_server_status": server_status.get("auth_server_status") or "",
                }
            )
        self.write(values)

        open_incidents = self.env["bl.afip.incident"].search(
            [("status_id", "=", self.id), ("resolved", "=", False)]
        )
        downtime_seconds = 0
        if down_since:
            downtime_seconds = max(int((now - down_since).total_seconds()), 0)
        for incident in open_incidents:
            incident.write(
                {
                    "resolved": True,
                    "resolved_at": now,
                    "downtime_seconds": downtime_seconds,
                }
            )

        if previous_state in ("down", "error"):
            self._notify_bus(event="recovered", downtime=downtime_seconds)

        if not self.search_count([("state", "=", "down")]):
            self._set_cron_active(False)

    def _probe_http(self, persist=True):
        self.ensure_one()
        result = self._do_http_probe()
        if not persist:
            return result
        if result.get("ok"):
            self._register_success(
                self.company_id,
                self.afip_ws,
                operation="HTTPProbe",
                server_status={
                    "app_server_status": self.app_server_status or "",
                    "db_server_status": self.db_server_status or "",
                    "auth_server_status": self.auth_server_status or "",
                },
                response_time=result.get("response_time"),
                isolated=False,
            )
        else:
            self._register_failure(
                self.company_id,
                self.afip_ws,
                RuntimeError(result.get("summary") or "HTTP probe error"),
                operation="HTTPProbe",
                response_excerpt=result.get("response_excerpt"),
                http_status=result.get("http_status"),
                degraded=False,
                response_time=result.get("response_time"),
                isolated=False,
            )
        return result

    def _probe_dummy(self):
        self.ensure_one()
        result = self._do_dummy_probe()
        if result.get("ok"):
            self._register_success(
                self.company_id,
                self.afip_ws,
                operation="FEDummy",
                server_status=result.get("server_status") or {},
                response_time=result.get("response_time"),
                isolated=False,
            )
        else:
            self._register_failure(
                self.company_id,
                self.afip_ws,
                RuntimeError(result.get("summary") or "FEDummy error"),
                operation="FEDummy",
                response_excerpt=result.get("response_excerpt"),
                http_status=result.get("http_status"),
                degraded=False,
                response_time=result.get("response_time"),
                isolated=False,
            )
        return result

    def probe(self, level="http"):
        if level not in ("http", "dummy"):
            raise UserError(_("Nivel de verificacion no soportado: %s") % level)
        results = []
        for status in self:
            if level == "dummy":
                results.append(status._probe_dummy())
            else:
                results.append(status._probe_http(persist=True))
        return results

    @api.model
    def _register_failure(
        self,
        company,
        afip_ws,
        error,
        operation=False,
        journal=None,
        move=None,
        document_type=None,
        response_excerpt=None,
        http_status=None,
        degraded=False,
        response_time=None,
        isolated=True,
    ):
        info = classify_afip_error(error, response_excerpt=response_excerpt, http_status=http_status)
        if self._bl_test_block_active():
            info["test_mode"] = True

        company_id = company.id if isinstance(company, models.BaseModel) else int(company)
        journal_id = journal.id if journal else False
        move_id = move.id if move else False
        document_type_id = document_type.id if document_type else False
        values = {
            "operation": operation,
            "journal_id": journal_id,
            "move_id": move_id,
            "document_type_id": document_type_id,
            "degraded": degraded,
            "response_time": response_time,
        }

        try:
            if isolated:
                with odoo.registry(self.env.cr.dbname).cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env_type = env["res.company"]._get_environment_type()
                    status = env["bl.afip.status"]._get_status(company_id, afip_ws, env_type=env_type)
                    status._apply_failure(info, **values)
            else:
                env_type = self.env["res.company"]._get_environment_type()
                status = self._get_status(company_id, afip_ws, env_type=env_type)
                status._apply_failure(info, **values)
        except Exception:
            _logger.exception("No se pudo registrar incidente ARCA sin afectar el flujo")

        return info

    @api.model
    def _register_success(
        self,
        company,
        afip_ws,
        operation=False,
        server_status=None,
        response_time=None,
        isolated=True,
    ):
        company_id = company.id if isinstance(company, models.BaseModel) else int(company)
        values = {
            "operation": operation,
            "server_status": server_status or {},
            "response_time": response_time,
        }
        try:
            if isolated:
                with odoo.registry(self.env.cr.dbname).cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    env_type = env["res.company"]._get_environment_type()
                    status = env["bl.afip.status"]._get_status(company_id, afip_ws, env_type=env_type)
                    now = fields.Datetime.now()
                    throttle_seconds = max(status._get_param("success_throttle", 120), 0)
                    if (
                        status.state == "ok"
                        and status.last_check
                        and throttle_seconds
                        and (now - status.last_check) < timedelta(seconds=throttle_seconds)
                    ):
                        return True
                    status._apply_success(**values)
                    return True

            env_type = self.env["res.company"]._get_environment_type()
            status = self._get_status(company_id, afip_ws, env_type=env_type)
            now = fields.Datetime.now()
            throttle_seconds = max(status._get_param("success_throttle", 120), 0)
            if (
                status.state == "ok"
                and status.last_check
                and throttle_seconds
                and (now - status.last_check) < timedelta(seconds=throttle_seconds)
            ):
                return True
            status._apply_success(**values)
            return True
        except Exception:
            _logger.exception("No se pudo registrar recuperacion ARCA sin afectar el flujo")
            return False

    @api.model
    def _probe_if_stale(self, companies=None, ttl=None):
        ttl_seconds = self._probe_ttl() if ttl is None else max(int(ttl), 0)
        statuses = self._ensure_statuses(companies=companies)
        now = fields.Datetime.now()
        for status in statuses:
            try:
                stale = not status.last_check or (now - status.last_check) >= timedelta(seconds=ttl_seconds)
                if stale:
                    status._probe_http(persist=True)
            except Exception:
                _logger.exception("Error de sondeo stale ARCA")
        return statuses

    @api.model
    def _precheck_before_invoicing(self, moves):
        if not self._get_param("precheck_on_invoice", True):
            return self.browse()

        grouped = defaultdict(lambda: self.env["account.move"])
        for move in moves:
            if (
                move.company_id.country_id.code == "AR"
                and move.is_invoice()
                and move.move_type in ("out_invoice", "out_refund")
                and move.journal_id.afip_ws
            ):
                grouped[(move.company_id.id, move.journal_id.afip_ws)] |= move

        results = self.browse()
        ttl = self._probe_ttl()
        now = fields.Datetime.now()
        for (company_id, afip_ws), grouped_moves in grouped.items():
            status = self._get_status(company_id, afip_ws)
            stale = not status.last_check or (now - status.last_check) >= timedelta(seconds=ttl)
            if stale:
                status._probe_http(persist=True)
                status = self._get_status(company_id, afip_ws)
            if status.state in ("down", "error"):
                results |= status
        return results

    @api.model
    def _set_cron_active(self, active):
        cron = self.env.ref("bl_afip_status.ir_cron_bl_afip_status_recovery", raise_if_not_found=False)
        if not cron:
            return False
        if bool(cron.active) == bool(active):
            return True
        vals = {"active": bool(active)}
        if active:
            vals["nextcall"] = fields.Datetime.now()
        try:
            cron.sudo().write(vals)
        except Exception:
            # ir.cron._try_lock usa NOWAIT. La fila puede estar tomada porque el
            # cron se esta ejecutando, o porque otra transaccion acaba de tocarla.
            # Se reintenta solo en la proxima verificacion.
            _logger.warning(
                "bl_afip_status: no se pudo %s el cron de recuperacion (fila bloqueada). Se reintenta en la proxima verificacion.",
                "activar" if active else "desactivar",
            )
            return False
        _logger.info("bl_afip_status: cron de verificacion %s", "activado" if active else "desactivado")
        return True

    @api.model
    def _cron_check_recovery(self):
        params = self.env["ir.config_parameter"].sudo()
        raw = params.get_param(TEST_BLOCK_PARAM)
        if raw and not self._bl_test_block_active():
            # El bloqueo de prueba vencio: se levanta solo.
            if self._get_param("test_block_mode", "soft") == "firewall":
                try:
                    self._bl_apply_firewall(False)
                except Exception:
                    _logger.exception("bl_afip_status: no se pudo levantar el bloqueo de firewall vencido")
            params.set_param(TEST_BLOCK_PARAM, "")
            _logger.info("bl_afip_status: MODO PRUEBA vencido y levantado automaticamente")

        down_statuses = self.sudo().search([("state", "=", "down")])
        if not down_statuses:
            self._set_cron_active(False)
            return

        for status in down_statuses:
            http_result = status._probe_http(persist=False)
            if not http_result.get("ok"):
                status._register_failure(
                    status.company_id,
                    status.afip_ws,
                    RuntimeError(http_result.get("summary") or "HTTP probe error"),
                    operation="CronRecoveryHTTP",
                    response_excerpt=http_result.get("response_excerpt"),
                    http_status=http_result.get("http_status"),
                )
                continue

            dummy_result = status._do_dummy_probe()
            if dummy_result.get("ok"):
                status._register_success(
                    status.company_id,
                    status.afip_ws,
                    operation="CronRecoveryDummy",
                    server_status=dummy_result.get("server_status") or {},
                )
            else:
                status._register_failure(
                    status.company_id,
                    status.afip_ws,
                    RuntimeError(dummy_result.get("summary") or "FEDummy error"),
                    operation="CronRecoveryDummy",
                    response_excerpt=dummy_result.get("response_excerpt"),
                    http_status=dummy_result.get("http_status"),
                )

        # Reevaluacion final desde la transaccion del cron: el cursor secundario
        # de _apply_success no puede tocar ir_cron mientras el job corre (la fila
        # esta tomada por el runner), asi que el apagado se decide aca.
        if not self.sudo().search_count([("state", "=", "down")]):
            self._set_cron_active(False)

    def _notify_bus(self, event, downtime=False):
        self.ensure_one()
        payload = {
            "refresh": True,
            "event": event,
            "afip_ws": self.afip_ws,
            "company_id": self.company_id.id,
            "downtime": downtime,
        }
        self.env["bus.bus"]._sendone("bl_afip_status", "bl_afip_status/update", payload)

    def _bl_level(self):
        """Traduce el state del registro al vocabulario de niveles del chip POS."""
        self.ensure_one()
        if self.state == "ok":
            servers = [self.app_server_status, self.db_server_status, self.auth_server_status]
            if any(value and value != "OK" for value in servers):
                return "warning"
            threshold = self._get_param("slow_threshold_seconds", 5)
            if threshold and self.response_time and self.response_time > threshold:
                return "warning"
            return "ok"
        if self.state == "down":
            return "down"
        if self.state == "error":
            return "error"
        return "loading"

    def _systray_payload(self):
        statuses = self.sudo().search([("company_id", "in", self.env.companies.ids)])
        state_labels = dict(self._fields["state"]._description_selection(self.env))
        test_mode_enabled = self._get_param("test_mode_enabled", False)
        test_info = self._bl_test_block_info()
        test_mode = test_info.get("mode") or self._get_param("test_block_mode", "soft")
        test_until = test_info.get("until") or ""
        level = "ok" if statuses else "loading"
        worst = self.browse()
        services = []
        for status in statuses:
            status_level = status._bl_level()
            if LEVEL_SEVERITY[status_level] >= LEVEL_SEVERITY[level]:
                level = status_level
                worst = status
            services.append(
                {
                    "id": status.id,
                    "name": status.name,
                    "afip_ws": (status.afip_ws or "").upper(),
                    "company": status.company_id.name,
                    "level": status_level,
                    "state_label": state_labels.get(status.state, status.state),
                    "endpoint": status.endpoint or "",
                    "last_check": fields.Datetime.to_string(status.last_check) or "",
                    "last_ok": fields.Datetime.to_string(status.last_ok) or "",
                    "down_since": fields.Datetime.to_string(status.down_since) or "",
                    "message": status.last_error_message or "",
                    "failures": status.consecutive_failures,
                }
            )
        if worst and level != "ok":
            title = worst.name
            message = worst.last_error_message or _("Revisa el detalle del servicio.")
            app = worst.app_server_status or ""
            db = worst.db_server_status or ""
            auth = worst.auth_server_status or ""
            checked = fields.Datetime.to_string(worst.last_check) or ""
        elif worst:
            title = _("Servicio ARCA operativo")
            message = _("La ultima verificacion fue correcta.")
            app = worst.app_server_status or ""
            db = worst.db_server_status or ""
            auth = worst.auth_server_status or ""
            checked = fields.Datetime.to_string(worst.last_check) or ""
        else:
            title = _("Verificando ARCA")
            message = _("Todavia no hay servicios ARCA verificados.")
            app = db = auth = checked = ""
        if test_info.get("active"):
            message = _("MODO PRUEBA (%s) - vence %s\n%s") % (test_mode, test_until or "-", message)
        return {
            "visible": True,
            "level": level,
            "title": title,
            "message": message,
            "app_status": app,
            "db_status": db,
            "auth_status": auth,
            "checked_at": checked,
            "services": services,
            "can_manage": self.env.user.has_group("account.group_account_manager"),
            "can_test": self.env.user.has_group("base.group_system"),
            "test_mode_enabled": test_mode_enabled,
            "test_block_active": bool(test_info.get("active")),
            "test_block_mode": test_mode,
            "test_block_until": test_until,
        }

    @api.model
    def get_systray_state(self):
        if not self.env.user._is_internal():
            return {"visible": False, "level": "loading", "services": []}
        return self._systray_payload()

    @api.model
    def probe_now(self):
        self._probe_if_stale(companies=self.env.companies, ttl=0)
        return self._systray_payload()

    @api.model
    def _bl_apply_firewall(self, blocked):
        action = "block" if blocked else "unblock"
        if not os.path.exists(BL_AFIP_FIREWALL_SCRIPT):
            raise UserError(
                _("No se encontro el script %s. Instalalo en el servidor para usar el modo firewall.")
                % BL_AFIP_FIREWALL_SCRIPT
            )
        try:
            subprocess.run(
                ["sudo", BL_AFIP_FIREWALL_SCRIPT, action],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError as error:
            raise UserError(
                _("No se encontro el script %s. Instalalo en el servidor para usar el modo firewall.")
                % BL_AFIP_FIREWALL_SCRIPT
            ) from error
        except subprocess.TimeoutExpired as error:
            raise UserError(
                _("Timeout al aplicar el bloqueo por firewall. Revisa la conectividad y los permisos de sudo.")
            ) from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or "").strip()[:300]
            raise UserError(
                _("No se pudo aplicar el bloqueo por firewall (%s): %s") % (action, detail)
            ) from error

    @api.model
    def bl_toggle_test_block(self, blocked=None):
        """Activa o desactiva el bloqueo de prueba. Solo administrador.

        `blocked` es el estado deseado, no un flip.
        """
        if not self.env.user.has_group("base.group_system"):
            raise UserError(_("Solo un administrador puede simular una caida de ARCA."))
        if not self._get_param("test_mode_enabled", False):
            raise UserError(_("El modo de prueba esta deshabilitado. Activalo en Ajustes antes de usarlo."))

        params = self.env["ir.config_parameter"].sudo()
        currently_blocked = self._bl_test_block_active()
        target_blocked = (not currently_blocked) if blocked is None else bool(blocked)

        # Idempotencia: si ya esta en el estado pedido, no cambia nada.
        if target_blocked == currently_blocked:
            return self._systray_payload()

        mode = self._get_param("test_block_mode", "soft")

        if mode == "firewall":
            self._bl_apply_firewall(target_blocked)

        if target_blocked:
            minutes = self._get_param("test_block_minutes", 15) or 15
            until = fields.Datetime.now() + timedelta(minutes=minutes)
            params.set_param(TEST_BLOCK_PARAM, fields.Datetime.to_string(until))
            _logger.info(
                "bl_afip_status: MODO PRUEBA ACTIVADO (%s) por %s hasta %s",
                mode,
                self.env.user.login,
                until,
            )
        else:
            params.set_param(TEST_BLOCK_PARAM, "")
            _logger.info("bl_afip_status: MODO PRUEBA DESACTIVADO por %s", self.env.user.login)

        self._ensure_statuses()
        for status in self.sudo().search([]):
            status._probe_http(persist=True)
        return self._systray_payload()

    def action_probe_http(self):
        self.ensure_one()
        self._probe_http(persist=True)
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_probe_dummy(self):
        self.ensure_one()
        self._probe_dummy()
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_view_incidents(self):
        self.ensure_one()
        action = self.env.ref("bl_afip_status.action_bl_afip_incident").read()[0]
        action["domain"] = [("status_id", "=", self.id)]
        return action
