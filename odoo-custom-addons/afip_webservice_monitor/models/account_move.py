from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    afip_service_available = fields.Boolean(
        string='AFIP Service Available',
        compute='_compute_afip_service_available',
        store=False
    )
    
    requires_afip_check = fields.Boolean(
        string='Requires AFIP Check',
        compute='_compute_requires_afip_check',
        store=False
    )

    @api.depends('journal_id', 'journal_id.l10n_ar_is_pos')
    def _compute_requires_afip_check(self):
        """Determine if this invoice requires AFIP service check"""
        for move in self:
            # Only require check for Argentinian POS journals
            move.requires_afip_check = bool(
                move.journal_id and 
                move.journal_id.l10n_ar_is_pos and
                move.move_type in ('out_invoice', 'out_refund')
            )

    @api.depends('requires_afip_check')
    def _compute_afip_service_available(self):
        """Check if AFIP service is available"""
        AfipStatus = self.env['afip.service.status'].sudo()
        
        for move in self:
            if move.requires_afip_check:
                move.afip_service_available = AfipStatus.is_afip_available('wsfe')
            else:
                move.afip_service_available = True

    afip_status_html = fields.Html(
        string='Estado AFIP',
        compute='_compute_afip_status_html',
        store=False
    )

    @api.depends('afip_service_available', 'requires_afip_check')
    def _compute_afip_status_html(self):
        for move in self:
            if not move.requires_afip_check or move.state != 'draft':
                move.afip_status_html = ''
                continue

            color = 'green' if move.afip_service_available else 'red'
            status_text = 'Servicio de facturacion AFIP/ARCA Operativo' if move.afip_service_available else 'Servicio de facturacion AFIP/ARCA No Disponible'
            
            move.afip_status_html = f'''
                <div class="d-flex align-items-center">
                    <span style="
                        height: 12px;
                        width: 12px;
                        background-color: {color};
                        border-radius: 50%;
                        display: inline-block;
                        margin-right: 8px;
                    "></span>
                    <span class="text-muted">{status_text}</span>
                </div>
            '''

    def _l10n_ar_caea_fallback_ready(self):
        """True si la emisión puede continuar aunque AFIP esté caído
        porque hay contingencia CAEA disponible (módulo `l10n_ar_caea`).

        Guardas con getattr/env-check: este módulo NO depende de
        l10n_ar_caea — si no está instalado, todo devuelve False y el
        comportamiento clásico (bloquear) se mantiene.
        """
        self.ensure_one()
        # El diario ES un PV exclusivo CAEA → nunca necesita AFIP online.
        if getattr(self.journal_id, 'l10n_ar_afip_pos_caea', False):
            return True
        if 'l10n_ar.caea' not in self.env:
            return False
        if not getattr(self.company_id, 'l10n_ar_caea_enabled', False):
            return False
        if not getattr(self.journal_id, 'l10n_ar_caea_journal_id', False):
            return False
        caea = self.env['l10n_ar.caea'].find_active(self.company_id)
        return bool(caea)

    def _check_afip_service_before_post(self):
        """Check AFIP service availability before posting.

        Con CAEA disponible NO bloqueamos: señalizamos y dejamos que
        `l10n_ar_caea` re-rutee el comprobante al PV de contingencia
        (RG 5785/2025). Bloquear solo queda para el caso sin salida
        legal: AFIP caído y sin CAEA vigente.
        """
        self.ensure_one()

        # Get configuration
        block_on_failure = self.env['ir.config_parameter'].sudo().get_param(
            'afip_webservice_monitor.block_on_failure', default='True')

        if block_on_failure == 'False':
            return True

        # Diario PV exclusivo CAEA: emite offline por diseño, sin check.
        if getattr(self.journal_id, 'l10n_ar_afip_pos_caea', False):
            return True

        if self.requires_afip_check:
            AfipStatus = self.env['afip.service.status'].sudo()
            
            # Force a fresh check
            environment = self.env['ir.config_parameter'].sudo().get_param(
                'afip_webservice_monitor.environment', default='production')
            
            service = AfipStatus.search([
                ('service_type', '=', 'wsfe'),
                ('environment', '=', environment),
                ('active', '=', True)
            ], limit=1)
            
            if service:
                service.check_service_status()
                
                if not service.is_available:
                    # Contingencia CAEA disponible → señalizar y seguir.
                    # l10n_ar_caea re-rutea el comprobante al PV CAEA.
                    if self._l10n_ar_caea_fallback_ready():
                        _logger.info(
                            "AFIP caído pero hay CAEA vigente — %s sigue "
                            "en modo contingencia (RG 5785/2025).", self.name,
                        )
                        return True

                    # Log detailed error for admin/debugging
                    _logger.warning(
                        f"Blocked invoice confirmation for {self.name} - "
                        f"AFIP service unavailable. Service: {service.name}, "
                        f"Error: {service.error_message}"
                    )

                    # Show simple user-friendly message
                    raise UserError(_(
                        'AFIP/ARCA Web Service is currently unavailable.\n'
                        'Please try again later.'
                    ))
            else:
                # No service configured, initialize and check
                AfipStatus.initialize_services()
                return self._check_afip_service_before_post()
        
        return True

    def action_post(self):
        """Override action_post to check AFIP service before posting"""
        # Check AFIP service for each invoice that requires it
        for move in self:
            if move.requires_afip_check and move.state == 'draft':
                move._check_afip_service_before_post()
        
        return super(AccountMove, self).action_post()

    def button_draft(self):
        """Override to allow setting back to draft even if service is down"""
        return super(AccountMove, self).button_draft()

    def action_check_afip_status(self):
        """Manual action to check AFIP status"""
        self.ensure_one()
        
        if not self.requires_afip_check:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AFIP Check Not Required'),
                    'message': _('This invoice does not use an Argentinian POS journal.'),
                    'type': 'info',
                    'sticky': False,
                }
            }
        
        AfipStatus = self.env['afip.service.status'].sudo()
        environment = self.env['ir.config_parameter'].sudo().get_param(
            'afip_webservice_monitor.environment', default='production')
        
        service = AfipStatus.search([
            ('service_type', '=', 'wsfe'),
            ('environment', '=', environment),
            ('active', '=', True)
        ], limit=1)
        
        if service:
            service.check_service_status()
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('AFIP Service Status'),
                    'message': _('Status: %s\nResponse time: %.2fs') % (
                        _('Available') if service.is_available else _('Unavailable'),
                        service.response_time
                    ),
                    'type': 'success' if service.is_available else 'danger',
                    'sticky': False,
                }
            }
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Error'),
                'message': _('No AFIP service configured'),
                'type': 'warning',
                'sticky': False,
            }
        }
