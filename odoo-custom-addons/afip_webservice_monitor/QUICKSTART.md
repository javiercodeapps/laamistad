# GUÍA RÁPIDA - AFIP/ARCA WebService Monitor

## 🚀 Inicio Rápido (5 minutos)

### 1. Instalar Dependencias
```bash
pip install requests zeep lxml
```

### 2. Copiar Módulo
```bash
cp -r afip_webservice_monitor /path/to/odoo/addons/
```

### 3. Reiniciar Odoo
```bash
sudo systemctl restart odoo
```

### 4. Instalar desde Odoo
1. Aplicaciones → Actualizar Lista
2. Buscar "AFIP"
3. Instalar

### 5. Configurar
1. Contabilidad → Configuración → Ajustes
2. Buscar "AFIP/ARCA WebService Monitor"
3. Seleccionar Environment (Production/Testing)
4. Click en "Initialize Services"
5. Click en "Check Services Now"
6. Guardar

## ✅ Verificación

### Verificar que funciona:
1. Ir a: Contabilidad → Configuración → AFIP Service Status
2. Deberías ver 2 servicios: WSFE y WSAA
3. Ambos deberían estar en verde (Available)

### Probar bloqueo de facturas:
1. Crear una factura con un diario que tenga `l10n_ar_is_pos = True`
2. Si el servicio está caído, verás un banner rojo
3. No podrás confirmar la factura

## 🎯 Funcionalidades Principales

### Banner de Advertencia
- Aparece automáticamente cuando AFIP está caído
- Color rojo con ícono de advertencia
- Botón "Verificar" para refrescar estado
- Se puede cerrar temporalmente

### Bloqueo de Facturas
- Solo afecta a diarios con `l10n_ar_is_pos = True`
- Mensaje de error claro y detallado
- Las facturas normales NO se bloquean

### Monitoreo Automático
- Verifica cada 5 minutos
- Configurable desde Ajustes
- Logs en Odoo

## 📊 Vistas Disponibles

### 1. Estado de Servicios
**Ubicación:** Contabilidad → Configuración → AFIP Service Status

**Muestra:**
- Estado actual (✅ ❌)
- Tiempo de respuesta
- Última verificación
- Fallos consecutivos
- Errores detallados

### 2. Configuración
**Ubicación:** Contabilidad → Configuración → Ajustes

**Opciones:**
- Environment (Testing/Production)
- Timeout (segundos)
- Check Interval (minutos)
- Block on Failure (sí/no)
- Show Banner (sí/no)

### 3. En la Factura
**Ubicación:** En cualquier factura con diario POS argentino

**Muestra:**
- Banner de estado
- Botón "Verificar AFIP"
- Alertas de disponibilidad

## 🔧 Configuración Rápida por Tipo de Uso

### Para Producción
```python
# En Odoo Shell
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.environment', 'production')
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.block_on_failure', 'True')
env.cr.commit()
```

### Para Testing/Desarrollo
```python
# En Odoo Shell
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.environment', 'testing')
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.block_on_failure', 'False')
env.cr.commit()
```

## 🐛 Solución de Problemas Comunes

### Problema: Banner no aparece
**Solución:** Ctrl+Shift+R para limpiar caché

### Problema: Facturas no se bloquean
**Solución:** Verificar que `l10n_ar_is_pos = True` en el diario

### Problema: Error al importar zeep
**Solución:** `pip install zeep lxml`

### Problema: Servicios no se crean
**Solución:** Click en "Initialize Services" en Ajustes

## 📝 Comandos Útiles

### Ver logs en tiempo real
```bash
tail -f /var/log/odoo/odoo-server.log | grep -i afip
```

### Verificar servicios manualmente
```bash
./odoo-bin shell -c odoo.conf -d your_database
env['afip.service.status'].sudo().cron_check_all_services()
```

### Reinicializar servicios
```bash
./odoo-bin shell -c odoo.conf -d your_database
env['afip.service.status'].sudo().search([]).unlink()
env['afip.service.status'].sudo().initialize_services()
env.cr.commit()
```

## 🎨 Personalización

### Cambiar intervalo de verificación
1. Ajustes → Técnico → Automatización → Acciones Programadas
2. Buscar "AFIP: Check Service Status"
3. Cambiar "Interval Number" (default: 5 minutos)

### Deshabilitar bloqueo temporalmente
1. Contabilidad → Configuración → Ajustes
2. AFIP/ARCA WebService Monitor
3. Desmarcar "Block Invoice Confirmation on Service Failure"

### Ocultar banner
1. Contabilidad → Configuración → Ajustes
2. AFIP/ARCA WebService Monitor
3. Desmarcar "Show Status Banner"

## 📞 Soporte

### Logs importantes
- `/var/log/odoo/odoo-server.log` - Logs principales
- Navegador F12 → Console - Errores JavaScript

### Archivos de configuración
- `__manifest__.py` - Configuración del módulo
- `models/afip_service_status.py` - Lógica de monitoreo
- `models/account_move.py` - Bloqueo de facturas

### Testing
```bash
# Ejecutar tests
./odoo-bin -c odoo.conf -d your_database \
  --test-enable --test-tags afip_webservice_monitor \
  --stop-after-init
```

## 🌟 Tips y Trucos

### Verificar rápidamente el estado
Desde cualquier lugar en Odoo:
1. Abrir una factura con POS argentino
2. Click en "Verificar AFIP"
3. Verás el estado actual

### Forzar verificación
Ir a: Contabilidad → Configuración → AFIP Service Status
Click en "Check Now" en cualquier servicio

### Ver historial de verificaciones
Ir a: Contabilidad → Configuración → AFIP Service Status
Ver campo "Consecutive Failures" para fallos seguidos

## 📚 Recursos Adicionales

- `README.md` - Documentación completa
- `INSTALL.md` - Guía de instalación detallada
- `tests/test_afip_monitor.py` - Tests unitarios
- Logs de Odoo para debugging

## 🔐 Permisos

| Grupo | Permisos |
|-------|----------|
| Usuario | Solo lectura |
| Gerente de Contabilidad | Lectura y escritura |
| Administrador | Acceso completo |

## 📦 Estructura Resumida

```
afip_webservice_monitor/
├── models/          # Lógica de negocio
├── views/           # Vistas XML
├── static/src/      # Frontend (JS, CSS, XML)
├── data/            # Cron jobs
├── security/        # Permisos
├── tests/           # Tests unitarios
└── README.md        # Documentación
```

---

**Versión:** 18.0.1.0.0  
**Licencia:** LGPL-3  
**Soporte:** Compatible con Odoo 18
