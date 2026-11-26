# bl_afip_status

Repositorio BlackLabs para soporte y monitoreo de disponibilidad ARCA/AFIP en Odoo 18.

## Modulos incluidos

- bl_afip_status: modulo principal (estado ARCA, incidentes, degradacion controlada, systray).
- bl_afip_status_settings: puente de Ajustes para mostrar la configuracion en el app BlackLabs.
- bl_afip_status_sale: puente opcional para sondeo reactivo en creacion de orden de venta.

## Requisitos funcionales

- Odoo 18.
- Dependencia fiscal: l10n_ar_afipws_fe (adhoc).

## Se puede replicar en cualquier Odoo?

Si. El modulo es replicable en cualquier Odoo 18 con sus dependencias.

Detalle importante:

- Modo normal y modo de prueba soft: funcionan solo con instalar/actualizar los modulos.
- Modo de prueba firewall: requiere instalacion manual de script + sudoers con root.

Es decir: sin permisos manuales, el modulo funciona completo excepto la variante firewall.

## Modos de prueba de caida ARCA

El modulo tiene dos modos de simulacion:

- soft (default): simula HTTP 503 sin tocar la red.
- firewall: bloquea salida HTTPS hacia ARCA/AFIP con script del sistema.

Guardas obligatorias implementadas:

- Solo base.group_system puede activar/desactivar.
- El modo de prueba debe estar habilitado por configuracion (test_mode_enabled).
- Todo bloqueo tiene expiracion automatica (test_block_minutes).
- Los incidentes de prueba se marcan con test_mode=True.
- Si falta el script firewall, se rechaza con UserError y no cae a soft en silencio.

## Instalacion manual obligatoria para modo firewall (root)

Los archivos versionados en el modulo son:

- bl_afip_status/scripts/bl_afip_firewall_block.sh
- bl_afip_status/scripts/sudoers-bl-afip-firewall

Instalacion (una sola vez por servidor):

1. Copiar script:
	cp /opt/odoo18/sources/BlackLabs/bl_afip_status/bl_afip_status/scripts/bl_afip_firewall_block.sh /usr/local/bin/bl_afip_firewall_block.sh
2. Asegurar owner del script:
	chown root:root /usr/local/bin/bl_afip_firewall_block.sh
3. Asegurar permisos del script:
	chmod 755 /usr/local/bin/bl_afip_firewall_block.sh
4. Copiar sudoers:
	cp /opt/odoo18/sources/BlackLabs/bl_afip_status/bl_afip_status/scripts/sudoers-bl-afip-firewall /etc/sudoers.d/bl-afip-firewall
5. Asegurar owner de sudoers:
	chown root:root /etc/sudoers.d/bl-afip-firewall
6. Asegurar permisos de sudoers:
	chmod 440 /etc/sudoers.d/bl-afip-firewall
7. Validar sintaxis sudoers (obligatorio):
	visudo -c
8. Verificar ejecucion sin password desde usuario de servicio:
	sudo -u odoo18 -H sudo -n /usr/local/bin/bl_afip_firewall_block.sh unblock

### Advertencia de seguridad (critica)

El sudoers permite que odoo18 ejecute ese script como root sin password.

Por eso los pasos de owner/permisos no son cosmeticos:

- Si el script quedara escribible por odoo18, ese usuario podria escalar a root modificando su contenido.
- Si sudoers no queda root:root 440, se abre riesgo de manipulacion o de ruptura de sudo.

## Ajustes (estructura actual)

En la configuracion se separo en dos bloques:

- BlackLabs - Estado ARCA:
  - bl_afip_probe_on_sale_order
  - bl_afip_precheck_on_invoice
  - bl_afip_block_invoice_when_down
  - bl_afip_probe_ttl_seconds
  - bl_afip_http_timeout
- BlackLabs - Estado ARCA: modo de prueba:
  - bl_afip_test_mode_enabled
  - bl_afip_test_block_mode (visible solo si test_mode_enabled)
  - bl_afip_test_block_minutes (visible solo si test_mode_enabled)

El gate del boton de bloqueo NO se relaja: solo aparece cuando test_mode_enabled esta activo y el usuario tiene permisos de administrador de sistema.

## Ultimas mejoras agregadas

### Soporte transaccional y concurrencia

- Refactor de registro de estado/incidente con isolated condicional:
  - isolated=True solo donde se necesita cursor separado (lectura de comprobantes y pedido de CAE).
  - isolated=False en toggle, probe_now, cron y sondeo reactivo para evitar colisiones entre transacciones.
- response_time se persiste en el mismo write de estado (se elimino el escritor separado que causaba colisiones).
- Eliminacion de commits manuales en el flujo del modulo para no romper transacciones de negocio.

### Toggle de prueba idempotente

- bl_toggle_test_block ahora acepta destino explicito blocked.
- Si ya esta en el estado pedido, no hace cambios (idempotencia ante retries de Odoo).
- El systray envia el estado deseado (target) en lugar de flip ciego.

### Puente de ajustes y visibilidad

- Se corrigio la invisibilidad del modo de prueba en BlackLabs.
- En este entorno, la estrategia move fallo por ParseError en herencia de vistas;
  por eso se dejo fallback estable con remove-native + redeclaracion en bridge.
- Se documenta deuda tecnica: cualquier nuevo setting del bloque original debe replicarse en el bridge mientras se mantenga ese fallback.

### Logging operativo

- Las lineas de MODO PRUEBA ACTIVADO/DESACTIVADO/VENCIDO pasaron a INFO.
- Se conservaron en WARNING solo las anomalias reales (locks de cron y contingencias).

### Firewall listo para produccion

- Script y sudoers instalados con hardening (root:root + 755/440).
- Validacion de sudoers con visudo -c y ejecucion sudo -n verificada.

## Instalacion/upgrade de modulos

Secuencia recomendada:

1. stop del servicio Odoo.
2. upgrade con stop-after-init de los modulos involucrados.
3. start del servicio Odoo.

No usar reload en caliente para cambios Python/OWL: puede dejar desfasajes entre backend y frontend.
