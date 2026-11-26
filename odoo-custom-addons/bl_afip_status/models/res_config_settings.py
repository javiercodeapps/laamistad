from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    bl_afip_probe_on_sale_order = fields.Boolean(
        string="Sondear ARCA al crear orden de venta",
        config_parameter="bl_afip_status.probe_on_sale_order",
        default=True,
    )
    bl_afip_precheck_on_invoice = fields.Boolean(
        string="Verificar ARCA antes de pedir CAE",
        config_parameter="bl_afip_status.precheck_on_invoice",
        default=True,
    )
    bl_afip_block_invoice_when_down = fields.Boolean(
        string="Bloquear emision cuando ARCA este caido",
        config_parameter="bl_afip_status.block_invoice_when_down",
        default=True,
    )
    bl_afip_probe_ttl_seconds = fields.Integer(
        string="TTL de sondeo (segundos)",
        config_parameter="bl_afip_status.probe_ttl_seconds",
        default=300,
    )
    bl_afip_http_timeout = fields.Integer(
        string="Timeout HTTP (segundos)",
        config_parameter="bl_afip_status.http_timeout",
        default=8,
    )
    bl_afip_test_mode_enabled = fields.Boolean(
        string="Habilitar modo de prueba de caida ARCA",
        config_parameter="bl_afip_status.test_mode_enabled",
        default=False,
    )
    bl_afip_test_block_mode = fields.Selection(
        [("soft", "soft"), ("firewall", "firewall")],
        string="Modo de bloqueo de prueba",
        config_parameter="bl_afip_status.test_block_mode",
        default="soft",
    )
    bl_afip_test_block_minutes = fields.Integer(
        string="Expiracion automatica (minutos)",
        config_parameter="bl_afip_status.test_block_minutes",
        default=15,
    )
