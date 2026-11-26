# Ejemplos de Uso - AFIP/ARCA WebService Monitor

## Tabla de Contenidos
1. [Ejemplos Básicos](#ejemplos-básicos)
2. [Configuración por Código](#configuración-por-código)
3. [Verificación Manual](#verificación-manual)
4. [Personalización](#personalización)
5. [Integración con Otros Módulos](#integración-con-otros-módulos)
6. [Casos de Uso Reales](#casos-de-uso-reales)

---

## Ejemplos Básicos

### 1. Verificar si AFIP está disponible desde código Python

```python
# En un método de tu módulo personalizado
def check_afip_before_operation(self):
    """Verificar AFIP antes de realizar una operación"""
    AfipStatus = self.env['afip.service.status'].sudo()
    
    if not AfipStatus.is_afip_available('wsfe'):
        raise UserError(_(
            'Cannot proceed: AFIP service is currently unavailable. '
            'Please try again later.'
        ))
    
    # Continuar con la operación
    return True
```

### 2. Obtener información detallada del estado

```python
# En Odoo Shell o en tu código
status_info = env['afip.service.status'].get_status_info()

print(f"WSFE Available: {status_info['wsfe']['available']}")
print(f"Last Check: {status_info['wsfe']['check_date']}")
print(f"Response Time: {status_info['wsfe']['response_time']}s")
print(f"Error: {status_info['wsfe']['error_message']}")
```

### 3. Forzar verificación de un servicio específico

```python
# En Odoo Shell
service = env['afip.service.status'].search([
    ('service_type', '=', 'wsfe'),
    ('environment', '=', 'production')
], limit=1)

if service:
    result = service.check_service_status()
    print(f"Available: {result['available']}")
    print(f"Status Code: {result['status_code']}")
    print(f"Response Time: {result['response_time']}")
```

---

## Configuración por Código

### 1. Configurar ambiente de producción

```python
# Odoo Shell
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.environment', 'production'
)
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.timeout', '10'
)
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.check_interval', '5'
)
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.block_on_failure', 'True'
)
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.show_banner', 'True'
)
env.cr.commit()

# Inicializar servicios
env['afip.service.status'].sudo().initialize_services()
env.cr.commit()
```

### 2. Configurar ambiente de testing

```python
# Odoo Shell - Para desarrollo/testing
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.environment', 'testing'
)
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.block_on_failure', 'False'
)
env.cr.commit()

# Recrear servicios para testing
env['afip.service.status'].sudo().search([]).unlink()
env['afip.service.status'].sudo().initialize_services()
env.cr.commit()
```

### 3. Cambiar intervalo de verificación

```python
# Cambiar a 10 minutos
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.check_interval', '10'
)

# Cambiar timeout a 15 segundos
env['ir.config_parameter'].sudo().set_param(
    'afip_webservice_monitor.timeout', '15'
)

env.cr.commit()
```

---

## Verificación Manual

### 1. Script para verificar todos los servicios

```python
# verify_afip.py
def verify_all_services():
    """Verificar todos los servicios AFIP"""
    services = env['afip.service.status'].search([('active', '=', True)])
    
    results = []
    for service in services:
        result = service.check_service_status()
        results.append({
            'name': service.name,
            'available': result['available'],
            'response_time': result['response_time'],
            'error': result.get('error', None)
        })
    
    return results

# Ejecutar
results = verify_all_services()
for r in results:
    status = '✓' if r['available'] else '✗'
    print(f"{status} {r['name']}: {r['response_time']:.2f}s")
    if r['error']:
        print(f"  Error: {r['error']}")
```

### 2. Verificar antes de lote de facturas

```python
# En un wizard o método personalizado
def process_invoice_batch(self, invoices):
    """Procesar lote de facturas con verificación AFIP"""
    # Verificar si alguna requiere AFIP
    requires_afip = any(inv.requires_afip_check for inv in invoices)
    
    if requires_afip:
        AfipStatus = self.env['afip.service.status'].sudo()
        if not AfipStatus.is_afip_available('wsfe'):
            raise UserError(_(
                'Cannot process invoices: AFIP service is unavailable.\n'
                '%d invoices require AFIP service.'
            ) % len([inv for inv in invoices if inv.requires_afip_check]))
    
    # Procesar facturas
    for invoice in invoices:
        invoice.action_post()
    
    return True
```

---

## Personalización

### 1. Crear notificación personalizada

```python
# En tu modelo personalizado
from odoo import models, api

class CustomAfipNotification(models.Model):
    _inherit = 'afip.service.status'
    
    def check_service_status(self):
        """Override para agregar notificación personalizada"""
        result = super().check_service_status()
        
        # Si el servicio está caído, enviar email
        if not result['available'] and self.consecutive_failures == 1:
            self._send_afip_down_notification()
        
        # Si el servicio se recupera, enviar email
        if result['available'] and self.consecutive_failures == 0:
            prev_state = self.search([
                ('id', '=', self.id)
            ], limit=1)
            if prev_state and not prev_state.is_available:
                self._send_afip_up_notification()
        
        return result
    
    def _send_afip_down_notification(self):
        """Enviar notificación cuando AFIP está caído"""
        template = self.env.ref('your_module.afip_down_email_template')
        if template:
            template.send_mail(self.id, force_send=True)
    
    def _send_afip_up_notification(self):
        """Enviar notificación cuando AFIP se recupera"""
        template = self.env.ref('your_module.afip_up_email_template')
        if template:
            template.send_mail(self.id, force_send=True)
```

### 2. Webhook personalizado

```python
import requests
import json

class CustomAfipWebhook(models.Model):
    _inherit = 'afip.service.status'
    
    def check_service_status(self):
        """Override para enviar webhook"""
        result = super().check_service_status()
        
        # Enviar webhook a sistema externo
        webhook_url = self.env['ir.config_parameter'].sudo().get_param(
            'custom_module.afip_webhook_url'
        )
        
        if webhook_url:
            try:
                payload = {
                    'service': self.name,
                    'available': result['available'],
                    'response_time': result['response_time'],
                    'timestamp': fields.Datetime.now().isoformat(),
                    'error': result.get('error', None)
                }
                requests.post(webhook_url, json=payload, timeout=5)
            except Exception as e:
                _logger.warning(f"Failed to send webhook: {e}")
        
        return result
```

### 3. Registro de historial extendido

```python
class AfipStatusHistory(models.Model):
    _name = 'afip.status.history'
    _description = 'AFIP Status History'
    _order = 'check_date desc'
    
    service_id = fields.Many2one('afip.service.status', string='Service')
    check_date = fields.Datetime(string='Check Date')
    is_available = fields.Boolean(string='Available')
    response_time = fields.Float(string='Response Time')
    status_code = fields.Integer(string='Status Code')
    error_message = fields.Text(string='Error')

class CustomAfipHistory(models.Model):
    _inherit = 'afip.service.status'
    
    history_ids = fields.One2many(
        'afip.status.history', 'service_id', string='History'
    )
    
    def check_service_status(self):
        """Override para guardar historial"""
        result = super().check_service_status()
        
        # Crear registro de historial
        self.env['afip.status.history'].create({
            'service_id': self.id,
            'check_date': fields.Datetime.now(),
            'is_available': result['available'],
            'response_time': result['response_time'],
            'status_code': result.get('status_code', 0),
            'error_message': result.get('error', False)
        })
        
        return result
```

---

## Integración con Otros Módulos

### 1. Integración con Reportes

```python
# En un reporte personalizado
class CustomInvoiceReport(models.AbstractModel):
    _name = 'report.your_module.invoice_report'
    
    @api.model
    def _get_report_values(self, docids, data=None):
        """Agregar estado AFIP al reporte"""
        docs = self.env['account.move'].browse(docids)
        
        # Verificar AFIP
        afip_status = self.env['afip.service.status'].sudo().get_status_info()
        
        return {
            'docs': docs,
            'afip_available': afip_status['all_available'],
            'afip_wsfe': afip_status['wsfe'],
            'afip_wsaa': afip_status['wsaa'],
        }
```

### 2. Integración con Dashboard

```python
# Widget personalizado para dashboard
class AfipDashboard(models.Model):
    _name = 'afip.dashboard'
    _description = 'AFIP Dashboard'
    
    @api.model
    def get_afip_statistics(self):
        """Obtener estadísticas para dashboard"""
        services = self.env['afip.service.status'].search([
            ('active', '=', True)
        ])
        
        stats = {
            'total_services': len(services),
            'available_services': len([s for s in services if s.is_available]),
            'avg_response_time': sum(s.response_time for s in services) / len(services),
            'services': []
        }
        
        for service in services:
            stats['services'].append({
                'name': service.name,
                'available': service.is_available,
                'response_time': service.response_time,
                'last_check': service.check_date,
                'consecutive_failures': service.consecutive_failures
            })
        
        return stats
```

---

## Casos de Uso Reales

### Caso 1: Empresa con Múltiples Puntos de Venta

```python
# Verificar AFIP antes de procesar ventas del día
class POSDailyClose(models.Model):
    _inherit = 'pos.session'
    
    def action_pos_session_closing_control(self):
        """Verificar AFIP antes de cerrar sesión POS"""
        # Si hay facturas electrónicas pendientes
        pending_invoices = self.order_ids.mapped('account_move').filtered(
            lambda m: m.requires_afip_check and m.state == 'draft'
        )
        
        if pending_invoices:
            AfipStatus = self.env['afip.service.status'].sudo()
            if not AfipStatus.is_afip_available('wsfe'):
                raise UserError(_(
                    'Cannot close POS session: AFIP service is unavailable.\n'
                    'There are %d electronic invoices pending confirmation.'
                ) % len(pending_invoices))
        
        return super().action_pos_session_closing_control()
```

### Caso 2: Exportación Masiva de Facturas

```python
# Wizard para exportación con verificación AFIP
class InvoiceExportWizard(models.TransientModel):
    _name = 'invoice.export.wizard'
    _description = 'Invoice Export Wizard'
    
    def action_export_invoices(self):
        """Exportar facturas verificando AFIP"""
        invoices = self.env['account.move'].browse(
            self.env.context.get('active_ids', [])
        )
        
        # Verificar cuáles requieren AFIP
        afip_invoices = invoices.filtered('requires_afip_check')
        
        if afip_invoices:
            AfipStatus = self.env['afip.service.status'].sudo()
            status_info = AfipStatus.get_status_info()
            
            # Crear reporte de estado
            report = {
                'total': len(invoices),
                'afip_required': len(afip_invoices),
                'afip_available': status_info['all_available'],
                'can_export': status_info['all_available']
            }
            
            if not report['can_export']:
                # Mostrar advertencia pero permitir exportación
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Warning'),
                        'message': _(
                            'AFIP service is unavailable.\n'
                            '%d invoices may need revalidation.'
                        ) % len(afip_invoices),
                        'type': 'warning',
                        'sticky': True,
                    }
                }
        
        # Continuar con exportación
        return self._do_export(invoices)
```

### Caso 3: Monitor de Salud del Sistema

```python
# Reporte de salud del sistema
class SystemHealthReport(models.AbstractModel):
    _name = 'report.your_module.system_health'
    
    @api.model
    def get_health_metrics(self):
        """Obtener métricas de salud del sistema"""
        AfipStatus = self.env['afip.service.status'].sudo()
        
        # Obtener servicios
        services = AfipStatus.search([('active', '=', True)])
        
        # Calcular uptime (últimas 24 horas)
        from datetime import datetime, timedelta
        yesterday = datetime.now() - timedelta(days=1)
        
        metrics = {
            'afip': {
                'status': 'healthy' if all(s.is_available for s in services) else 'unhealthy',
                'services': [],
                'uptime': 0
            }
        }
        
        for service in services:
            # Calcular uptime aproximado
            if service.consecutive_failures == 0:
                uptime = 100.0
            else:
                # Estimar basado en fallos consecutivos
                uptime = max(0, 100 - (service.consecutive_failures * 2))
            
            metrics['afip']['services'].append({
                'name': service.name,
                'available': service.is_available,
                'uptime': uptime,
                'response_time': service.response_time,
                'last_check': service.check_date
            })
        
        # Uptime general
        if metrics['afip']['services']:
            metrics['afip']['uptime'] = sum(
                s['uptime'] for s in metrics['afip']['services']
            ) / len(metrics['afip']['services'])
        
        return metrics
```

---

## Scripts de Utilidad

### Script 1: Reporte Diario por Email

```python
# cron_daily_afip_report.py
def send_daily_afip_report():
    """Enviar reporte diario del estado de AFIP"""
    AfipStatus = env['afip.service.status'].sudo()
    services = AfipStatus.search([('active', '=', True)])
    
    # Preparar datos del reporte
    report_data = {
        'date': fields.Date.today(),
        'services': []
    }
    
    for service in services:
        report_data['services'].append({
            'name': service.name,
            'available': service.is_available,
            'avg_response_time': service.response_time,
            'total_failures': service.consecutive_failures,
            'last_error': service.error_message or 'None'
        })
    
    # Enviar email
    template = env.ref('your_module.daily_afip_report_template')
    template.with_context(report_data=report_data).send_mail(
        env.user.id, force_send=True
    )
```

### Script 2: Limpieza de Datos Antiguos

```python
# cleanup_old_data.py
def cleanup_afip_old_data():
    """Limpiar datos antiguos de AFIP (si usas historial)"""
    from datetime import datetime, timedelta
    
    # Mantener solo últimos 30 días
    cutoff_date = datetime.now() - timedelta(days=30)
    
    # Si tienes modelo de historial
    old_records = env['afip.status.history'].search([
        ('check_date', '<', cutoff_date)
    ])
    
    count = len(old_records)
    old_records.unlink()
    
    _logger.info(f"Cleaned up {count} old AFIP status records")
```

---

**Nota:** Estos ejemplos son punto de partida. Ajústalos según tus necesidades específicas.
