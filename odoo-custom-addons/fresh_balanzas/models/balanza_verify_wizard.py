import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class BalanzaVerifyWizard(models.TransientModel):
    _name = 'balanza.verify.wizard'
    _description = 'Actualizar y verificar precios en balanza'

    scale_id = fields.Many2many('balanza.scale', string='Balanza', required=True)
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

    def action_execute(self):
        """Ejecuta el modo elegido: comparar, actualizar, o actualizar y comparar."""
        self.ensure_one()
        scale = self.scale_id

        try:
            proto = scale._get_protocol()
            with proto:
                if self.mode in ('update', 'update_and_compare'):
                    result = self._update_prices(proto, scale)
                    if self.mode == 'update_and_compare':
                        compare = self._compare_prices(proto, scale)
                        result = self._merge_results(result, compare)
                else:
                    result = self._compare_prices(proto, scale)
        except Exception as e:
            result = {
                'state': 'done',
                'log': f'ERROR de conexión: {str(e)}',
                'mismatch_count': 0,
                'total_checked': 0,
                'updated_count': 0,
            }

        self.write(result)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'balanza.verify.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': self.id,
        }

    def _get_products(self):
        """Productos sincronizables: default_code numérico."""
        products = self.env['product.product'].search([
            ('default_code', '!=', False),
            ('default_code', '!=', ''),
        ])
        return products.filtered(lambda p: p.default_code.isdigit())

    def _update_prices(self, proto, scale):
        """Actualiza precios en la balanza.

        Lee cada PLU, reemplaza solo el campo precio (pos 77-83, escalado
        según los decimales configurados en la balanza) y reenvía el registro
        completo. El resto del registro (nombre, depto, impuestos, etc.) queda
        tal como está configurado en la balanza.
        """
        lines = []
        updated = 0
        unchanged = 0
        not_found = 0
        errors = 0

        for product in self._get_products():
            plu_number = int(product.default_code)
            try:
                ok, code, data = proto.read_plu(plu_number)
                if not ok or not data or len(data) < 83:
                    not_found += 1
                    continue

                new_price = scale._price_to_scale_raw(product.list_price)
                if not scale._price_fits(new_price):
                    errors += 1
                    lines.append(
                        f'ERROR PLU {product.default_code}: precio '
                        f'{product.list_price or 0.0:.{scale.price_decimals}f} '
                        f'no entra en 6 dígitos con {scale.price_decimals} '
                        f'decimales'
                    )
                    continue
                try:
                    old_price = int(data[77:83])
                except ValueError:
                    old_price = 0

                if old_price == new_price:
                    unchanged += 1
                    continue

                record = data[:77] + f'{new_price:06d}' + data[83:]
                ok, code, msg = proto.upsert_plu_record(record)
                if ok:
                    updated += 1
                    lines.append(
                        f'ACTUALIZADO PLU {product.default_code}: '
                        f'{scale._raw_to_price_string(old_price)} -> '
                        f'{scale._raw_to_price_string(new_price)} | '
                        f'{product.name}'
                    )
                else:
                    errors += 1
                    lines.append(f'ERROR PLU {product.default_code}: {msg}')
            except Exception as e:
                errors += 1
                lines.append(f'EXCEPCIÓN PLU {product.default_code}: {str(e)}')

        summary = (
            f'Actualización finalizada: {updated} precios actualizados, '
            f'{unchanged} sin cambios, {not_found} no encontrados, {errors} errores.'
        )
        if lines:
            summary += '\n\n' + '\n'.join(lines)

        return {
            'state': 'done',
            'log': summary,
            'updated_count': updated,
            'total_checked': updated + unchanged,
            'mismatch_count': 0,
        }

    def _compare_prices(self, proto, scale):
        """Compara precios de la balanza con Odoo (escala según decimales)."""
        lines = []
        mismatches = 0
        checked = 0
        not_found = 0

        for product in self._get_products():
            plu_number = int(product.default_code)
            try:
                ok, code, data = proto.read_plu(plu_number)
                if not ok or not data or len(data) < 83:
                    not_found += 1
                    continue

                # Precio de la balanza (pos 77-83, entero escalado)
                try:
                    scale_price = int(data[77:83])
                except ValueError:
                    scale_price = 0

                odoo_price = scale._price_to_scale_raw(product.list_price)
                checked += 1

                if scale_price != odoo_price:
                    mismatches += 1
                    lines.append(
                        f'DIFERENCIA PLU {product.default_code}: '
                        f'balanza={scale._raw_to_price_string(scale_price)} | '
                        f'odoo={scale._raw_to_price_string(odoo_price)} | '
                        f'{product.name}'
                    )
            except Exception as e:
                lines.append(f'ERROR PLU {product.default_code}: {str(e)}')

        if mismatches == 0:
            summary = f'Verificación OK: {checked} productos verificados, sin diferencias.'
            if not_found > 0:
                summary += f'\n{not_found} PLUs no encontrados en la balanza.'
        else:
            summary = (
                f'DIFERENCIAS ENCONTRADAS: {mismatches} de {checked} verificados.\n\n'
                + '\n'.join(lines)
            )

        return {
            'state': 'done',
            'log': summary,
            'mismatch_count': mismatches,
            'total_checked': checked,
            'updated_count': 0,
        }

    def _merge_results(self, update_result, compare_result):
        """Une los resultados de actualizar + comparar en un solo log."""
        log = update_result.get('log', '')
        log += '\n\n--- VERIFICACIÓN POST-ACTUALIZACIÓN ---\n'
        log += compare_result.get('log', '')
        return {
            'state': 'done',
            'log': log,
            'updated_count': update_result.get('updated_count', 0),
            'total_checked': compare_result.get('total_checked', 0),
            'mismatch_count': compare_result.get('mismatch_count', 0),
        }
