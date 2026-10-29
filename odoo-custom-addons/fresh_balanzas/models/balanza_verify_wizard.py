import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class BalanzaVerifyWizard(models.TransientModel):
    _name = 'balanza.verify.wizard'
    _description = 'Actualizar y verificar precios en balanza'

    #: Posición del precio dentro del registro PLU (comando 2005/5005).
    PRICE_SLICE = slice(77, 83)

    scale_id = fields.Many2many('balanza.scale', string='Balanzas', required=True)
    product_ids = fields.Many2many(
        'product.product', string='Productos',
        help='Si se indican, solo se procesan estos productos. '
             'Si se deja vacío se procesan todos los productos con código '
             'numérico.'
    )
    mode = fields.Selection([
        ('verify', 'Solo comparar'),
        ('update', 'Actualizar precios'),
        ('update_and_compare', 'Actualizar y comparar'),
    ], string='Modo', default='verify', required=True,
        help='Actualizar: envía el precio de Odoo a la balanza (solo el campo '
             'precio del PLU, sin tocar el resto del registro).\n'
             'Actualizar y comparar: actualiza y luego relee para confirmar '
             'que no queden diferencias.')
    state = fields.Selection([
        ('confirm', 'Confirmar'),
        ('done', 'Finalizado'),
    ], default='confirm')
    log = fields.Text('Resultado')
    mismatch_count = fields.Integer('Diferencias encontradas', default=0)
    total_checked = fields.Integer('Total verificados', default=0)
    updated_count = fields.Integer('Precios actualizados', default=0)

    @api.model
    def action_open_for_products(self, products):
        """Abre el wizard con productos y balanzas activas preseleccionados."""
        if not products:
            raise UserError('Seleccioná al menos un producto.')
        products = products.filtered(
            lambda p: p.default_code and p.default_code.isdigit()
        )
        if not products:
            raise UserError(
                'Los productos seleccionados no tienen código numérico.'
            )
        scales = self.env['balanza.scale'].search([('active', '=', True)])
        if not scales:
            raise UserError(
                'No hay balanzas activas configuradas. '
                'Configurá al menos una balanza activa antes de continuar.'
            )
        wizard = self.create({
            'scale_id': [(6, 0, scales.ids)],
            'product_ids': [(6, 0, products.ids)],
            'mode': 'update',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'balanza.verify.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wizard.id,
        }

    def action_execute(self):
        """Ejecuta el modo elegido: comparar, actualizar, o actualizar y comparar.

        Recorre todas las balanzas seleccionadas y acumula el resultado.
        """
        self.ensure_one()
        logs = []
        total_checked = 0
        total_mismatch = 0
        total_updated = 0
        multi = len(self.scale_id) > 1

        for scale in self.scale_id:
            slot_map = scale._get_slot_map()
            try:
                proto = scale._get_protocol()
                with proto:
                    result = self._process_prices(
                        proto, scale, slot_map,
                        update=self.mode in ('update', 'update_and_compare'),
                        verify_written=self.mode == 'update_and_compare',
                    )
            except Exception as e:
                _logger.exception('Error procesando balanza %s', scale.name)
                result = {
                    'state': 'done',
                    'log': f'ERROR de conexión: {str(e)}',
                    'mismatch_count': 0,
                    'total_checked': 0,
                    'updated_count': 0,
                }
            finally:
                # Guardar lo que se haya aprendido del índice aunque falle.
                if slot_map != scale._get_slot_map():
                    scale.write({
                        'plu_slot_map': slot_map,
                        'plu_slot_map_date': fields.Datetime.now(),
                    })

            total_checked += result.get('total_checked', 0)
            total_mismatch += result.get('mismatch_count', 0)
            total_updated += result.get('updated_count', 0)

            log = result.get('log', '')
            if multi:
                log = f'=== {scale.name} ===\n{log}'
            logs.append(log)

        self.write({
            'state': 'done',
            'log': '\n\n'.join(logs),
            'mismatch_count': total_mismatch,
            'total_checked': total_checked,
            'updated_count': total_updated,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'balanza.verify.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': self.id,
        }

    def _get_products(self):
        """Productos a procesar: los seleccionados o todos los numéricos."""
        products = self.product_ids or self.env['product.product'].search([
            ('default_code', '!=', False),
            ('default_code', '!=', ''),
        ])
        return products.filtered(
            lambda p: p.default_code and p.default_code.isdigit()
        )

    def _process_prices(self, proto, scale, slot_map, update=False,
                        verify_written=False):
        """Recorre los productos en UNA sola pasada.

        Lee cada PLU (resolviendo su posición real en la tabla), compara el
        precio con Odoo y, si ``update`` está activo, reenvía el registro con
        el precio nuevo sin tocar el resto de los campos.

        Antes se leía dos veces cuando el modo era "actualizar y comparar";
        ahora la comparación sale de la misma lectura que ya se necesitaba
        para actualizar, y sólo se releen los PLU efectivamente modificados.

        Args:
            proto: protocolo conectado.
            scale: balanza.
            slot_map: dict número→posición; se completa con lo que falte.
            update: si True escribe el precio cuando difiere.
            verify_written: si True relee los PLU modificados para confirmar.
        """
        lines = []
        updated = 0
        unchanged = 0
        not_found = 0
        errors = 0
        mismatches = 0
        written = []

        for product in self._get_products():
            plu_number = int(product.default_code)
            try:
                ok, code, data = scale._read_plu(proto, plu_number, slot_map)
                if not ok or not data or len(data) < self.PRICE_SLICE.stop:
                    not_found += 1
                    reason = proto.RESPONSES.get(code, '')
                    lines.append(
                        f'NO ENCONTRADO PLU {plu_number}: {reason}'
                    )
                    continue

                try:
                    scale_price = int(data[self.PRICE_SLICE])
                except ValueError:
                    scale_price = 0
                odoo_price = scale._price_to_scale_raw(product.list_price)

                if scale_price == odoo_price:
                    unchanged += 1
                    continue

                mismatches += 1
                if not update:
                    lines.append(
                        f'DIFERENCIA PLU {plu_number}: '
                        f'balanza={scale._raw_to_price_string(scale_price)} | '
                        f'odoo={scale._raw_to_price_string(odoo_price)} | '
                        f'{product.name}'
                    )
                    continue

                if not scale._price_fits(odoo_price):
                    errors += 1
                    lines.append(
                        f'ERROR PLU {plu_number}: precio '
                        f'{product.list_price or 0.0:.{scale.price_decimals}f} '
                        f'no entra en 6 dígitos con {scale.price_decimals} '
                        f'decimales'
                    )
                    continue

                record = (
                    data[:self.PRICE_SLICE.start]
                    + f'{odoo_price:06d}'
                    + data[self.PRICE_SLICE.stop:]
                )
                ok, code, msg = proto.upsert_plu_record(record)
                if ok:
                    updated += 1
                    written.append((plu_number, odoo_price))
                    lines.append(
                        f'ACTUALIZADO PLU {plu_number}: '
                        f'{scale._raw_to_price_string(scale_price)} -> '
                        f'{scale._raw_to_price_string(odoo_price)} | '
                        f'{product.name}'
                    )
                else:
                    errors += 1
                    lines.append(
                        f'ERROR PLU {plu_number}: '
                        f'{proto.RESPONSES.get(code, msg)}'
                    )
            except Exception as e:
                errors += 1
                lines.append(f'EXCEPCIÓN PLU {plu_number}: {str(e)}')

        checked = unchanged + mismatches
        if update:
            summary = (
                f'Actualización finalizada: {updated} precios actualizados, '
                f'{unchanged} sin cambios, {not_found} no encontrados, '
                f'{errors} errores.'
            )
        elif mismatches == 0:
            summary = (
                f'Verificación OK: {checked} productos verificados, '
                f'sin diferencias.'
            )
            if not_found:
                summary += f'\n{not_found} PLUs no encontrados en la balanza.'
        else:
            summary = (
                f'DIFERENCIAS ENCONTRADAS: {mismatches} de {checked} '
                f'verificados.'
            )

        if verify_written and written:
            summary += self._verify_written(proto, scale, slot_map, written)

        if lines:
            summary += '\n\n' + '\n'.join(lines)

        return {
            'state': 'done',
            'log': summary,
            'updated_count': updated,
            'total_checked': checked,
            'mismatch_count': mismatches,
        }

    def _verify_written(self, proto, scale, slot_map, written):
        """Relee sólo los PLU modificados para confirmar que quedó el precio."""
        failures = []
        for plu_number, expected in written:
            ok, _code, data = scale._read_plu(proto, plu_number, slot_map)
            if not ok or not data or len(data) < self.PRICE_SLICE.stop:
                failures.append(f'PLU {plu_number}: no se pudo releer')
                continue
            try:
                got = int(data[self.PRICE_SLICE])
            except ValueError:
                got = -1
            if got != expected:
                failures.append(
                    f'PLU {plu_number}: quedó '
                    f'{scale._raw_to_price_string(got)}, se esperaba '
                    f'{scale._raw_to_price_string(expected)}'
                )
        if not failures:
            return (
                f'\n\n--- VERIFICACIÓN POST-ACTUALIZACIÓN ---\n'
                f'{len(written)} PLUs releídos, todos correctos.'
            )
        return (
            '\n\n--- VERIFICACIÓN POST-ACTUALIZACIÓN ---\n'
            + '\n'.join(failures)
        )

