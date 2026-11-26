#!/bin/bash
# Comandos útiles para desarrollo del módulo AFIP WebService Monitor

# INSTALACIÓN
echo "=== COMANDOS DE INSTALACIÓN ==="

# Instalar dependencias
echo "pip install requests zeep lxml"

# Copiar módulo (ajustar rutas)
echo "cp -r afip_webservice_monitor /path/to/odoo/addons/"

# Reiniciar Odoo
echo "sudo systemctl restart odoo"

# Instalar módulo
echo "./odoo-bin -c odoo.conf -d your_database -i afip_webservice_monitor --stop-after-init"

# DESARROLLO
echo -e "\n=== COMANDOS DE DESARROLLO ==="

# Actualizar módulo
echo "./odoo-bin -c odoo.conf -d your_database -u afip_webservice_monitor --stop-after-init"

# Ver logs en tiempo real
echo "tail -f /var/log/odoo/odoo-server.log | grep -i afip"

# Odoo shell
echo "./odoo-bin shell -c odoo.conf -d your_database"

# TESTING
echo -e "\n=== COMANDOS DE TESTING ==="

# Ejecutar todos los tests
echo "./odoo-bin -c odoo.conf -d your_database --test-enable --test-tags afip_webservice_monitor --stop-after-init"

# Tests con log detallado
echo "./odoo-bin -c odoo.conf -d your_database --test-enable --log-level=test --stop-after-init"

# VERIFICACIÓN
echo -e "\n=== COMANDOS DE VERIFICACIÓN ==="

# Verificar módulo instalado
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> module = env['ir.module.module'].search([('name', '=', 'afip_webservice_monitor')])
>>> print(module.state)
>>> exit()
EOF

# Verificar servicios creados
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> services = env['afip.service.status'].search([])
>>> for s in services: print(f"{s.name}: {s.is_available}")
>>> exit()
EOF

# Forzar verificación
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> env['afip.service.status'].sudo().cron_check_all_services()
>>> exit()
EOF

# CONFIGURACIÓN
echo -e "\n=== COMANDOS DE CONFIGURACIÓN ==="

# Configurar ambiente de producción
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.environment', 'production')
>>> env['ir.config_parameter'].sudo().set_param('afip_webservice_monitor.block_on_failure', 'True')
>>> env.cr.commit()
>>> exit()
EOF

# Inicializar servicios
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> env['afip.service.status'].sudo().initialize_services()
>>> env.cr.commit()
>>> exit()
EOF

# DOCKER
echo -e "\n=== COMANDOS DOCKER ==="

# Construir imagen
echo "docker-compose build"

# Iniciar servicios
echo "docker-compose up -d"

# Ver logs
echo "docker-compose logs -f odoo"

# Acceder al contenedor
echo "docker exec -it odoo_container bash"

# Instalar módulo en Docker
echo "docker exec odoo_container odoo -d your_database -i afip_webservice_monitor --stop-after-init"

# MANTENIMIENTO
echo -e "\n=== COMANDOS DE MANTENIMIENTO ==="

# Reinicializar servicios
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> env['afip.service.status'].sudo().search([]).unlink()
>>> env['afip.service.status'].sudo().initialize_services()
>>> env.cr.commit()
>>> exit()
EOF

# Verificar permisos
echo "ls -la /path/to/odoo/addons/afip_webservice_monitor"
echo "chown -R odoo:odoo /path/to/odoo/addons/afip_webservice_monitor"

# Limpiar caché
echo "find . -name '*.pyc' -delete"
echo "find . -name '__pycache__' -type d -exec rm -rf {} +"

# DEBUG
echo -e "\n=== COMANDOS DE DEBUG ==="

# Odoo con debugger
echo "./odoo-bin -c odoo.conf -d your_database --dev=all"

# Ver configuración actual
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> params = ['environment', 'timeout', 'check_interval', 'block_on_failure', 'show_banner']
>>> for p in params:
...     val = env['ir.config_parameter'].sudo().get_param(f'afip_webservice_monitor.{p}')
...     print(f"{p}: {val}")
>>> exit()
EOF

# Verificar diario POS
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> journal = env['account.journal'].search([('code', '=', 'YOUR_CODE')])
>>> print(f"Journal: {journal.name}")
>>> print(f"l10n_ar_is_pos: {journal.l10n_ar_is_pos}")
>>> exit()
EOF

# DESINSTALACIÓN
echo -e "\n=== COMANDOS DE DESINSTALACIÓN ==="

# Desinstalar módulo
echo "./odoo-bin -c odoo.conf -d your_database --uninstall afip_webservice_monitor"

# O desde shell
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> module = env['ir.module.module'].search([('name', '=', 'afip_webservice_monitor')])
>>> module.button_immediate_uninstall()
>>> exit()
EOF

# PERFORMANCE
echo -e "\n=== COMANDOS DE PERFORMANCE ==="

# Ver tiempo de respuesta
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> import time
>>> start = time.time()
>>> service = env['afip.service.status'].search([('service_type', '=', 'wsfe')], limit=1)
>>> service.check_service_status()
>>> print(f"Tiempo: {time.time() - start:.2f}s")
>>> exit()
EOF

# Ver estadísticas
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> services = env['afip.service.status'].search([])
>>> for s in services:
...     print(f"{s.name}:")
...     print(f"  Available: {s.is_available}")
...     print(f"  Response Time: {s.response_time:.2f}s")
...     print(f"  Failures: {s.consecutive_failures}")
>>> exit()
EOF

# GIT
echo -e "\n=== COMANDOS GIT ==="

# Inicializar repositorio
echo "cd afip_webservice_monitor"
echo "git init"
echo "git add ."
echo "git commit -m 'Initial commit: AFIP WebService Monitor v18.0.1.0.0'"

# Crear tag
echo "git tag -a v18.0.1.0.0 -m 'Version 18.0.1.0.0'"

# Push
echo "git remote add origin your_repo_url"
echo "git push -u origin main"
echo "git push --tags"

# BACKUP
echo -e "\n=== COMANDOS DE BACKUP ==="

# Backup del módulo
echo "tar -czf afip_webservice_monitor_backup_\$(date +%Y%m%d).tar.gz afip_webservice_monitor/"

# Restaurar backup
echo "tar -xzf afip_webservice_monitor_backup_YYYYMMDD.tar.gz -C /path/to/odoo/addons/"

# Backup de configuración
cat << 'EOF'
./odoo-bin shell -c odoo.conf -d your_database
>>> import json
>>> config = {}
>>> params = ['environment', 'timeout', 'check_interval', 'block_on_failure', 'show_banner']
>>> for p in params:
...     config[p] = env['ir.config_parameter'].sudo().get_param(f'afip_webservice_monitor.{p}')
>>> with open('afip_config_backup.json', 'w') as f:
...     json.dump(config, f, indent=2)
>>> exit()
EOF

# PRODUCCIÓN
echo -e "\n=== COMANDOS PARA PRODUCCIÓN ==="

# Deploy
echo "./odoo-bin -c odoo.conf -d production_db -i afip_webservice_monitor --stop-after-init --no-http"

# Verificar en producción
echo "curl -s https://your-odoo.com/web/database/selector | grep afip_webservice_monitor"

# Monitorear logs de producción
echo "tail -f /var/log/odoo/odoo-server.log | grep -i 'afip\|error'"

# Reiniciar servicio en producción
echo "sudo systemctl restart odoo"
echo "sudo systemctl status odoo"

echo -e "\n=== COMANDOS COMPLETADOS ==="
