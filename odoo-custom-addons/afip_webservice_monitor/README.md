# AFIP/ARCA WebService Monitor for Odoo 18

## Descripción

Módulo para Odoo 18 que monitorea la disponibilidad del servicio web de facturación electrónica de AFIP/ARCA y bloquea la confirmación de facturas cuando el servicio no está disponible.

## Características

- ✅ Monitoreo automático del servicio web de AFIP/ARCA
- ✅ Banner de advertencia visible cuando el servicio está caído
- ✅ Bloqueo de confirmación de facturas electrónicas cuando el servicio no está disponible
- ✅ Solo afecta a diarios con `l10n_ar_is_pos = True`
- ✅ Verificación manual del estado del servicio
- ✅ Configuración de ambiente (Testing/Producción)
- ✅ Verificaciones automáticas programadas cada 5 minutos
- ✅ Soporte para ambos servicios: WSFE y WSAA

## Requisitos

### Dependencias Python
```bash
pip install requests zeep lxml
```

### Módulos Odoo
- `account`
- `l10n_ar` (Localización Argentina)

## Instalación

1. Copiar el módulo a la carpeta de addons de Odoo:
```bash
cp -r afip_webservice_monitor /path/to/odoo/addons/
```

2. Instalar las dependencias Python:
```bash
pip install requests zeep lxml
```

3. Actualizar la lista de aplicaciones en Odoo

4. Instalar el módulo "AFIP/ARCA WebService Monitor"

## Configuración

### Configuración Inicial

Ir a: **Contabilidad → Configuración → Ajustes**

Buscar la sección **AFIP/ARCA WebService Monitor** y configurar:

1. **Environment**: Seleccionar Testing o Producción
2. **Connection Timeout**: Tiempo máximo de espera (por defecto: 10 segundos)
3. **Check Interval**: Intervalo de verificación automática (por defecto: 5 minutos)
4. **Block Invoice Confirmation**: Habilitar/deshabilitar bloqueo de facturas
5. **Show Status Banner**: Mostrar/ocultar banner de estado

### Inicialización de Servicios

Después de la instalación, el módulo automáticamente inicializa los servicios. También puedes hacerlo manualmente:

1. Ir a **Contabilidad → Configuración → Ajustes**
2. En la sección AFIP/ARCA WebService Monitor
3. Hacer clic en **"Initialize Services"**

## Uso

### Visualización del Estado

#### Banner de Advertencia
Cuando el servicio de AFIP está caído, aparece un banner rojo en la parte superior de la pantalla con:
- Mensaje de advertencia
- Fecha de última verificación
- Botón para verificar manualmente
- Mensaje de error (si está disponible)

#### Vista de Estado de Servicios
Ir a: **Contabilidad → Configuración → AFIP Service Status**

Aquí puedes ver:
- Estado actual de cada servicio (WSFE, WSAA)
- Tiempo de respuesta
- Última verificación
- Fallos consecutivos
- Detalles de errores

### Confirmación de Facturas

#### Con Servicio Disponible ✅
- Las facturas con diarios de POS argentinos se confirman normalmente
- Banner verde indica que el servicio está disponible

#### Con Servicio No Disponible ❌
- Aparece un banner rojo de advertencia en la factura
- El botón "Confirmar" ejecuta pero lanza un error UserError
- Mensaje detallado con información del error
- No se permite la confirmación hasta que el servicio esté disponible

#### Facturas que NO requieren AFIP
Las facturas que **NO** usan diarios con `l10n_ar_is_pos = True` se confirman normalmente sin verificar el servicio de AFIP.

### Verificación Manual

#### Desde la Factura
1. Abrir una factura en borrador
2. Si requiere AFIP, verás un botón **"Verificar AFIP"**
3. Hacer clic para verificar el estado actual del servicio

#### Desde Configuración
1. Ir a **Contabilidad → Configuración → Ajustes**
2. En la sección AFIP/ARCA WebService Monitor
3. Hacer clic en **"Check Services Now"**

#### Desde Vista de Servicios
1. Ir a **Contabilidad → Configuración → AFIP Service Status**
2. Hacer clic en el botón **"Check Now"** de cualquier servicio

## Cron Jobs

El módulo incluye un trabajo programado que verifica automáticamente el estado de los servicios cada 5 minutos.

Para ajustar la frecuencia:
1. Ir a **Ajustes → Técnico → Automatización → Acciones Programadas**
2. Buscar "AFIP: Check Service Status"
3. Ajustar el intervalo según necesidad

## Estructura del Módulo

```
afip_webservice_monitor/
├── __init__.py
├── __manifest__.py
├── README.md
├── INSTALL.md
├── models/
│   ├── __init__.py
│   ├── afip_service_status.py
│   ├── account_move.py
│   └── res_config_settings.py
├── views/
│   ├── afip_service_status_views.xml
│   ├── account_move_views.xml
│   └── res_config_settings_views.xml
├── data/
│   └── ir_cron_data.xml
├── security/
│   └── ir.model.access.csv
├── static/
│   └── src/
│       ├── js/
│       │   └── afip_status_banner.js
│       ├── xml/
│       │   └── afip_status_banner.xml
│       └── css/
│           └── afip_status_banner.css
└── tests/
    ├── __init__.py
    └── test_afip_monitor.py
```

## Permisos

- **Usuario**: Puede ver el estado de los servicios
- **Gerente de Contabilidad**: Puede ver, crear, editar y eliminar registros de estado
- **Administrador del Sistema**: Acceso completo

## Troubleshooting

### El servicio siempre aparece como no disponible

1. Verificar que las librerías estén instaladas:
```bash
pip install requests zeep lxml
```

2. Verificar conectividad con AFIP:
```bash
curl "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL"
```

3. Revisar logs de Odoo para errores específicos

### Las facturas se bloquean incorrectamente

1. Verificar que el diario tenga `l10n_ar_is_pos = True`
2. Verificar la configuración en Ajustes
3. Revisar que el ambiente (Testing/Producción) sea el correcto

### El banner no aparece

1. Verificar que "Show Status Banner" esté habilitado en Ajustes
2. Limpiar caché del navegador
3. Actualizar la aplicación (F5)

## Soporte y Contribuciones

Para reportar bugs o solicitar mejoras, contactar al equipo de desarrollo.

## Licencia

LGPL-3

## Changelog

### Version 18.0.1.0.0
- Primera versión
- Monitoreo de servicios WSFE y WSAA
- Bloqueo de confirmación de facturas
- Banner de advertencia
- Configuración flexible
- Soporte para Testing y Producción
