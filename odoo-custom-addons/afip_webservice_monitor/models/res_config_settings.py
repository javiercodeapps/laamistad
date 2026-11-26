from odoo import models, fields, api, _


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    afip_monitor_environment = fields.Selection([
        ('testing', 'Testing/Homologación'),
        ('production', 'Producción'),
    ], string='AFIP Environment',
        default='production',
        config_parameter='afip_webservice_monitor.environment')
    
    afip_monitor_timeout = fields.Integer(
        string='Connection Timeout (seconds)',
        default=10,
        config_parameter='afip_webservice_monitor.timeout',
        help='Maximum time to wait for AFIP service response')
    
    afip_monitor_check_interval = fields.Integer(
        string='Check Interval (minutes)',
        default=5,
        config_parameter='afip_webservice_monitor.check_interval',
        help='How often to refresh service status automatically')
    
    afip_monitor_block_on_failure = fields.Boolean(
        string='Block Invoice Confirmation on Service Failure',
        default=True,
        config_parameter='afip_webservice_monitor.block_on_failure',
        help='Prevent invoice confirmation when AFIP service is unavailable')
    
    afip_monitor_show_banner = fields.Boolean(
        string='Show Status Banner',
        default=True,
        config_parameter='afip_webservice_monitor.show_banner',
        help='Display a banner at the top when AFIP service is down')

    def action_check_afip_services(self):
        """Manual action to check all AFIP services"""
        AfipStatus = self.env['afip.service.status'].sudo()
        AfipStatus.cron_check_all_services()
        
        # Check if any service failed
        failed_services = AfipStatus.search([
            ('active', '=', True),
            ('is_available', '=', False)
        ])
        
        if failed_services:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Service Check Completed'),
                    'message': _('Warning: %s service(s) are unavailable. Check the status list for details.') % len(failed_services),
                    'type': 'warning',
                    'sticky': True,
                }
            }
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AFIP Services Checked'),
                'message': _('All configured services have been checked and are operational.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_initialize_afip_services(self):
        """Initialize AFIP service records"""
        AfipStatus = self.env['afip.service.status'].sudo()
        AfipStatus.initialize_services()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Services Initialized'),
                'message': _('AFIP service monitors have been initialized.'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_view_afip_services(self):
        """Open AFIP service status view"""
        return {
            'name': _('AFIP Service Status'),
            'type': 'ir.actions.act_window',
            'res_model': 'afip.service.status',
            'view_mode': 'list,form',
            'domain': [('active', '=', True)],
            'context': {'create': False},
        }
