# Guía de Instalación - AFIP/ARCA WebService Monitor

## Instalación Rápida

### 1. Copiar el módulo

```bash
# Copiar el módulo a la carpeta de addons
cp -r afip_webservice_monitor /path/to/odoo/addons/

# O crear un symlink
ln -s /path/to/afip_webservice_monitor /path/to/odoo/addons/
```

### 2. Instalar dependencias Python

```bash
# Con pip
pip install requests zeep lxml

# O con requirements.txt
pip install -r requirements.txt
```

### 3. Reiniciar Odoo

```bash
# Reiniciar el servicio de Odoo
sudo systemctl restart odoo

# O si estás en desarrollo
./odoo-bin -c odoo.conf --stop-after-init
```

### 4. Actualizar lista de aplicaciones

1. Ir a Aplicaciones
2. Activar el modo desarrollador (si no está activo)
3. Hacer clic en "Actualizar Lista de Aplicaciones"
4. Buscar "AFIP/ARCA WebService Monitor"
5. Instalar

### 5. Configuración Post-Instalación

#### Opción A: Desde la Interfaz Web

1. Ir a **Contabilidad → Configuración → Ajustes**
2. Buscar la sección **AFIP/ARCA WebService Monitor**
3. Configurar:
   - Environment: `production` o `testing`
   - Connection Timeout: `10` segundos
   - Check Interval: `5` minutos
   - Block Invoice Confirmation: `✓` activado
   - Show Status Banner: `✓` activado
4. Hacer clic en **"Initialize Services"**
5. Hacer clic en **"Check Services Now"**
6. Guardar

#### Opción B: Desde la Terminal (Odoo Shell)

```bash
# Acceder al shell de Odoo
./odoo-bin shell -c odoo.conf -d your_database

# En el shell de Python:
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.environment', 'production')
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.timeout', '10')
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.check_interval', '5')
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.block_on_failure', 'True')
env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.show_banner', 'True')

# Inicializar servicios
env['afip.service.status'].sudo().initialize_services()

# Verificar servicios
env['afip.service.status'].sudo().cron_check_all_services()

# Salir
exit()
```

## Verificación de Instalación

### 1. Verificar que el módulo está instalado

```bash
# En el shell de Odoo
./odoo-bin shell -c odoo.conf -d your_database

# Verificar módulo
module = env['ir.module.module'].search([('name', '=', 'afip_webservice_monitor')])
print(f"Estado: {module.state}")
# Debe mostrar: Estado: installed
```

### 2. Verificar servicios creados

Ir a: **Contabilidad → Configuración → AFIP Service Status**

Deberías ver al menos 2 servicios:
- AFIP WSFE - Production/Testing
- AFIP WSAA - Production/Testing

### 3. Probar verificación manual

1. Crear una factura con un diario POS argentino
2. Verificar que aparece el banner de estado
3. Hacer clic en "Verificar AFIP"
4. Confirmar que muestra el estado del servicio

### 4. Verificar logs

```bash
# Ver los últimos logs de Odoo
tail -f /var/log/odoo/odoo-server.log | grep -i afip

# Deberías ver mensajes como:
# INFO your_database odoo.addons.afip_webservice_monitor.models.afip_service_status: AFIP Service Check - AFIP WSFE - Production: Available
```

## Instalación con Docker

Si estás usando Docker y Portainer:

### 1. Dockerfile

Agregar al Dockerfile de Odoo:

```dockerfile
FROM odoo:18.0

USER root

# Instalar dependencias Python
RUN pip3 install --no-cache-dir \
    requests>=2.31.0 \
    zeep>=4.2.1 \
    lxml>=4.9.0

USER odoo
```

### 2. docker-compose.yml

```yaml
version: '3.8'

services:
  odoo:
    build: .
    depends_on:
      - db
    ports:
      - "8069:8069"
    volumes:
      - ./addons:/mnt/extra-addons
      - ./afip_webservice_monitor:/mnt/extra-addons/afip_webservice_monitor
      - odoo-data:/var/lib/odoo
    environment:
      - HOST=db
      - USER=odoo
      - PASSWORD=odoo
    command: --addons-path=/mnt/extra-addons,/usr/lib/python3/dist-packages/odoo/addons

  db:
    image: postgres:15
    environment:
      - POSTGRES_DB=postgres
      - POSTGRES_PASSWORD=odoo
      - POSTGRES_USER=odoo
    volumes:
      - postgres-data:/var/lib/postgresql/data

volumes:
  odoo-data:
  postgres-data:
```

### 3. Construir y ejecutar

```bash
# Construir la imagen
docker-compose build

# Iniciar los servicios
docker-compose up -d

# Ver logs
docker-compose logs -f odoo
```

### 4. Instalar el módulo en Docker

```bash
# Acceder al contenedor
docker exec -it <container_name> bash

# Actualizar la lista de módulos
odoo --addons-path=/mnt/extra-addons -d your_database --update=afip_webservice_monitor --stop-after-init
```

## Docker Swarm

Para Docker Swarm con Portainer:

### stack.yml

```yaml
version: '3.8'

services:
  odoo:
    image: your-registry/odoo:18-afip
    networks:
      - odoo-network
    ports:
      - "8069:8069"
    volumes:
      - type: volume
        source: odoo-data
        target: /var/lib/odoo
      - type: bind
        source: ./afip_webservice_monitor
        target: /mnt/extra-addons/afip_webservice_monitor
    environment:
      - HOST=postgres
      - USER=odoo
      - PASSWORD=${ODOO_PASSWORD}
    deploy:
      replicas: 2
      update_config:
        parallelism: 1
        delay: 10s
      restart_policy:
        condition: on-failure

  postgres:
    image: postgres:15
    networks:
      - odoo-network
    volumes:
      - postgres-data:/var/lib/postgresql/data
    environment:
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_USER=odoo
    deploy:
      placement:
        constraints:
          - node.role == manager

networks:
  odoo-network:
    driver: overlay

volumes:
  odoo-data:
  postgres-data:
```

## Troubleshooting

### Problema: Módulo no aparece en la lista

**Solución:**
```bash
# Reiniciar Odoo con actualización de módulos
./odoo-bin -c odoo.conf -d your_database --update=all --stop-after-init

# O forzar actualización de la lista
./odoo-bin -c odoo.conf -d your_database -u base --stop-after-init
```

### Problema: Error al importar zeep

**Solución:**
```bash
# Verificar instalación
pip show zeep

# Reinstalar si es necesario
pip uninstall zeep
pip install zeep

# En algunos sistemas necesitas también:
pip install python-zeep
```

### Problema: Error de permisos

**Solución:**
```bash
# Dar permisos correctos
chown -R odoo:odoo /path/to/odoo/addons/afip_webservice_monitor

# O si estás usando un usuario diferente
chown -R your_user:your_group /path/to/odoo/addons/afip_webservice_monitor
```

### Problema: Servicios no se inicializan

**Solución:**
```bash
# Desde el shell de Odoo
./odoo-bin shell -c odoo.conf -d your_database

# Forzar inicialización
env['afip.service.status'].sudo().search([]).unlink()
env['afip.service.status'].sudo().initialize_services()
env.cr.commit()
```

### Problema: Banner no aparece

**Solución:**
1. Limpiar caché del navegador (Ctrl+Shift+R)
2. Verificar configuración en Ajustes
3. Verificar que el servicio esté marcado como no disponible
4. Revisar logs del navegador (F12 → Console)

### Problema: Facturas se bloquean incorrectamente

**Solución:**
```bash
# Verificar configuración del diario
./odoo-bin shell -c odoo.conf -d your_database

# Verificar campo l10n_ar_is_pos
journal = env['account.journal'].search([('code', '=', 'YOUR_JOURNAL_CODE')])
print(f"l10n_ar_is_pos: {journal.l10n_ar_is_pos}")

# Si no está configurado correctamente:
journal.write({'l10n_ar_is_pos': True})
env.cr.commit()
```

## Testing

### Ejecutar tests

```bash
# Ejecutar todos los tests del módulo
./odoo-bin -c odoo.conf -d your_database -i afip_webservice_monitor --test-enable --stop-after-init

# Ejecutar tests específicos
./odoo-bin -c odoo.conf -d your_database --test-tags afip_webservice_monitor --stop-after-init

# Ver output detallado
./odoo-bin -c odoo.conf -d your_database --test-enable --log-level=test --stop-after-init
```

## Actualización

### Actualizar el módulo

```bash
# Método 1: Desde Odoo
# Ir a Aplicaciones → Buscar el módulo → Actualizar

# Método 2: Línea de comandos
./odoo-bin -c odoo.conf -d your_database -u afip_webservice_monitor --stop-after-init

# Método 3: Con Docker
docker exec <container_name> odoo -d your_database -u afip_webservice_monitor --stop-after-init
```

## Desinstalación

```bash
# Desde la interfaz: Aplicaciones → Módulo → Desinstalar

# Desde línea de comandos
./odoo-bin shell -c odoo.conf -d your_database

# En el shell:
module = env['ir.module.module'].search([('name', '=', 'afip_webservice_monitor')])
module.button_immediate_uninstall()
```

## Soporte

Para soporte adicional:
- Revisar los logs: `/var/log/odoo/odoo-server.log`
- Consultar la documentación de Odoo 18
- Contactar al equipo de desarrollo
