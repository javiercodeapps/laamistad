from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging
import ssl
import os
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

# Configure SSL at module level to allow weaker DH keys for AFIP
# This is necessary because AFIP servers use older SSL configurations
os.environ['OPENSSL_CONF'] = '/dev/null'

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # Patch SSL default context
    urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'
except Exception as e:
    _logger.warning(f"Could not configure urllib3 SSL: {e}")

try:
    # Patch requests SSL
    requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS = 'ALL:@SECLEVEL=1'
except Exception as e:
    _logger.warning(f"Could not configure requests SSL: {e}")

try:
    from zeep import Client
    from zeep.transports import Transport
    from zeep.exceptions import Fault, TransportError
    ZEEP_AVAILABLE = True
except ImportError:
    _logger.warning('zeep library not found. Please install it: pip install zeep')
    ZEEP_AVAILABLE = False


def create_ssl_session():
    """Create a requests session with relaxed SSL settings for AFIP"""
    session = requests.Session()
    
    # Create adapter with custom SSL context
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.ssl_ import create_urllib3_context
        
        class AFIPSSLAdapter(HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                ctx = create_urllib3_context(ciphers='ALL:@SECLEVEL=1')
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                kwargs['ssl_context'] = ctx
                return super().init_poolmanager(*args, **kwargs)
        
        session.mount('https://', AFIPSSLAdapter())
    except Exception as e:
        _logger.warning(f"Could not create custom SSL adapter: {e}")
    
    session.verify = False
    return session


class AfipServiceStatus(models.Model):
    _name = 'afip.service.status'
    _description = 'AFIP/ARCA Service Status Monitor'
    _order = 'check_date desc'

    name = fields.Char(string='Service Name', required=True)
    service_type = fields.Selection([
        ('wsfe', 'Web Service Facturación Electrónica'),
        ('wsaa', 'Web Service Autenticación y Autorización'),
    ], string='Service Type', required=True)
    
    environment = fields.Selection([
        ('testing', 'Testing/Homologación'),
        ('production', 'Producción'),
    ], string='Environment', required=True, default='production')
    
    url = fields.Char(string='Service URL', required=True)
    is_available = fields.Boolean(string='Available', default=False)
    last_status_code = fields.Integer(string='Last Status Code')
    response_time = fields.Float(string='Response Time (seconds)', digits=(10, 3))
    check_date = fields.Datetime(string='Last Check', default=fields.Datetime.now)
    error_message = fields.Text(string='Error Message')
    consecutive_failures = fields.Integer(string='Consecutive Failures', default=0)
    
    active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        ('unique_service', 'unique(service_type, environment)', 
         'Each service type can only have one record per environment!')
    ]

    @api.model
    def get_service_urls(self):
        """Returns the URLs for AFIP services"""
        return {
            'testing': {
                'wsfe': 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL',
                'wsaa': 'https://wsaahomo.afip.gov.ar/ws/services/LoginCms?wsdl'
            },
            'production': {
                'wsfe': 'https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL',
                'wsaa': 'https://wsaa.afip.gov.ar/ws/services/LoginCms?wsdl'
            }
        }

    @api.model
    def _check_service_with_zeep(self, url, service_type, timeout=10):
        """Check service availability using zeep library with custom SSL"""
        if not ZEEP_AVAILABLE:
            raise Exception("Zeep library not available")
        
        try:
            import time
            start_time = time.time()
            
            # Create session with relaxed SSL
            session = create_ssl_session()
            transport = Transport(session=session, timeout=timeout)
            client = Client(url, transport=transport)
            
            # Check FEDummy for WSFE
            if service_type == 'wsfe':
                status = client.service.FEDummy()
                
                if status.AppServer == 'OK' and status.DbServer == 'OK' and status.AuthServer == 'OK':
                    response_time = time.time() - start_time
                    return {
                        'available': True,
                        'status_code': 200,
                        'response_time': response_time,
                        'error': False
                    }
                else:
                    return {
                        'available': False,
                        'status_code': 200,
                        'response_time': 0,
                        'error': f"AFIP Error: App={status.AppServer}, Db={status.DbServer}, Auth={status.AuthServer}"
                    }
            
            response_time = time.time() - start_time
            return {
                'available': True,
                'status_code': 200,
                'response_time': response_time,
                'error': False
            }
        except TransportError as e:
            return {
                'available': False,
                'status_code': getattr(e, 'status_code', 0),
                'response_time': 0,
                'error': f'Transport Error: {str(e)}'
            }
        except Exception as e:
            return {
                'available': False,
                'status_code': 0,
                'response_time': 0,
                'error': f'Error: {str(e)}'
            }

    @api.model
    def _check_service_with_requests(self, url, timeout=10):
        """Check service availability using requests library"""
        try:
            import time
            start_time = time.time()
            
            session = create_ssl_session()
            response = session.get(url, timeout=timeout)
            response_time = time.time() - start_time
            
            # Map common HTTP error codes to descriptive messages
            error_messages = {
                500: 'Error interno del servidor AFIP',
                502: 'Bad Gateway - Servidor AFIP no disponible',
                503: 'Servicio AFIP temporalmente no disponible (mantenimiento)',
                504: 'Gateway Timeout - Servidor AFIP no responde',
            }
            
            if response.status_code == 200:
                error_msg = False
            else:
                error_msg = error_messages.get(
                    response.status_code, 
                    f'HTTP Error: {response.status_code}'
                )
            
            return {
                'available': response.status_code == 200,
                'status_code': response.status_code,
                'response_time': response_time,
                'error': error_msg
            }
        except requests.exceptions.Timeout:
            return {
                'available': False,
                'status_code': 0,
                'response_time': timeout,
                'error': f'Timeout after {timeout} seconds'
            }
        except requests.exceptions.ConnectionError as e:
            return {
                'available': False,
                'status_code': 0,
                'response_time': 0,
                'error': f'Connection Error: {str(e)}'
            }
        except Exception as e:
            return {
                'available': False,
                'status_code': 0,
                'response_time': 0,
                'error': f'Error: {str(e)}'
            }

    def check_service_status(self):
        """Check the status of the AFIP service"""
        self.ensure_one()
        
        timeout = int(self.env['ir.config_parameter'].sudo().get_param(
            'afip_webservice_monitor.timeout', default=10))
        
        # Try with zeep first, fallback to requests
        try:
            result = self._check_service_with_zeep(self.url, self.service_type, timeout)
        except Exception as e:
            _logger.warning(f"Zeep check failed, falling back to requests: {e}")
            result = self._check_service_with_requests(self.url, timeout)
        
        # Update consecutive failures
        if not result['available']:
            consecutive_failures = self.consecutive_failures + 1
        else:
            consecutive_failures = 0
        
        # Update the record
        self.write({
            'is_available': result['available'],
            'last_status_code': result['status_code'],
            'response_time': result['response_time'],
            'check_date': fields.Datetime.now(),
            'error_message': result['error'] if result['error'] else False,
            'consecutive_failures': consecutive_failures,
        })
        
        _logger.info(f"AFIP Service Check - {self.name}: {'Available' if result['available'] else 'Unavailable'}")
        
        return result

    @api.model
    def cron_check_all_services(self):
        """Cron job to check all active services"""
        services = self.search([('active', '=', True)])
        for service in services:
            try:
                service.check_service_status()
            except Exception as e:
                _logger.error(f"Error checking service {service.name}: {str(e)}")

    @api.model
    def initialize_services(self):
        """Initialize service records if they don't exist"""
        urls = self.get_service_urls()
        environment = self.env['ir.config_parameter'].sudo().get_param(
            'afip_webservice_monitor.environment', default='production')
        
        for service_type in ['wsfe', 'wsaa']:
            existing = self.search([
                ('service_type', '=', service_type),
                ('environment', '=', environment)
            ])
            
            if not existing:
                url = urls[environment][service_type]
                name = f"AFIP {service_type.upper()} - {environment.title()}"
                
                self.create({
                    'name': name,
                    'service_type': service_type,
                    'environment': environment,
                    'url': url,
                })
                _logger.info(f"Created service monitor: {name}")

    @api.model
    def is_afip_available(self, service_type='wsfe'):
        """Check if AFIP service is available for invoice operations"""
        environment = self.env['ir.config_parameter'].sudo().get_param(
            'afip_webservice_monitor.environment', default='production')
        
        service = self.search([
            ('service_type', '=', service_type),
            ('environment', '=', environment),
            ('active', '=', True)
        ], limit=1)
        
        if not service:
            self.initialize_services()
            service = self.search([
                ('service_type', '=', service_type),
                ('environment', '=', environment),
                ('active', '=', True)
            ], limit=1)
        
        if service:
            check_interval = int(self.env['ir.config_parameter'].sudo().get_param(
                'afip_webservice_monitor.check_interval', default=5))
            
            if not service.check_date or \
               (fields.Datetime.now() - service.check_date) > timedelta(minutes=check_interval):
                service.check_service_status()
            
            return service.is_available
        
        return False

    @api.model
    def get_status_info(self):
        """Get status information for all services"""
        environment = self.env['ir.config_parameter'].sudo().get_param(
            'afip_webservice_monitor.environment', default='production')
        
        services = self.search([
            ('environment', '=', environment),
            ('active', '=', True)
        ])
        
        if not services:
            self.initialize_services()
            services = self.search([
                ('environment', '=', environment),
                ('active', '=', True)
            ])
        
        result = {
            'wsfe': None,
            'wsaa': None,
            'all_available': True
        }
        
        for service in services:
            result[service.service_type] = {
                'name': service.name,
                'available': service.is_available,
                'check_date': service.check_date,
                'response_time': service.response_time,
                'error_message': service.error_message,
                'consecutive_failures': service.consecutive_failures,
            }
            if not service.is_available:
                result['all_available'] = False
        
        return result

    def action_refresh_status(self):
        """Manual refresh action"""
        self.ensure_one()
        self.check_service_status()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Service Checked'),
                'message': _('Status: %s') % (_('Available') if self.is_available else _('Unavailable')),
                'type': 'success' if self.is_available else 'warning',
                'sticky': False,
            }
        }
