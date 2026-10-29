import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class BalanzaSyncWizard(models.TransientModel):
    _name = 'balanza.sync.wizard'
    _description = 'Asistente de sincronización de balanzas'

    scale_ids = fields.Many2many(
        'balanza.scale', string='Balanzas destino', required=True
    )
    product_ids = fields.Many2many(
        'product.product', string='Productos a sincronizar'
    )
    sync_type = fields.Selection([
        ('product', 'Productos'),
        ('vendor', 'Vendedores'),
    ], string='Tipo de sincronización', required=True, default='product')
    state = fields.Selection([
        ('confirm', 'Confirmar'),
        ('done', 'Finalizado'),
    ], string='Estado', default='confirm')
    log = fields.Text('Resultado')
    verify_after_sync = fields.Boolean(
        'Verificar precios después de sincronizar', default=True
    )

    def action_sync(self):
        """Ejecuta la sincronización para cada balanza seleccionada."""
        self.ensure_one()
        all_logs = []

        for scale in self.scale_ids:
            log_record = self.env['balanza.sync.log'].create({
                'scale_id': scale.id,
                'sync_type': self.sync_type,
                'start_time': fields.Datetime.now(),
                'state': 'pending',
                'user_id': self.env.uid,
            })

            try:
                proto = scale._get_protocol()
                with proto:
                    if self.sync_type == 'product':
                        result = self._sync_products(proto, scale, log_record)
                    else:
                        result = self._sync_vendors(proto, scale, log_record)
                log_record.write(result)
            except Exception as e:
                _logger.exception('Error en sincronización %s', scale.name)
                log_record.write({
                    'state': 'error',
                    'end_time': fields.Datetime.now(),
                    'log': f'ERROR de conexión: {str(e)}',
                })

            all_logs.append(log_record)

        # Generar resumen
        summary_lines = []
        for log in all_logs:
            status = '✓' if log.state == 'success' else ('⚠' if log.state == 'partial' else '✗')
            summary_lines.append(
                f'{status} {log.scale_id.name}: '
                f'{log.success_count}/{log.product_count} productos '
                f'({log.state})'
            )

        # Verificación automática post-sync
        if self.verify_after_sync and self.sync_type == 'product':
            summary_lines.append('')
            summary_lines.append('--- VERIFICACIÓN POST-SYNC ---')
            for log in all_logs:
                if log.state in ('success', 'partial'):
                    verify_result = self._verify_prices_post_sync(
                        log.scale_id
                    )
                    summary_lines.append(verify_result)

        self.write({
            'state': 'done',
            'log': '\n'.join(summary_lines),
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'balanza.sync.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': self.id,
        }

    def _get_plu_type(self, product):
        """Infierde P (pesable) / N (unidad) según la UoM del producto.

        Categoría de peso (kg, g, t...) → P; cualquier otra (unidad, docena...) → N.
        """
        weight_categ = self.env.ref('uom.product_uom_categ_kgm', raise_if_not_found=False)
        if weight_categ and product.uom_id.category_id == weight_categ:
            return 'P'
        return 'N'

    def _sync_products(self, proto, scale, log_record):
        """Sincroniza productos a una balanza."""
        # Determinar productos a sincronizar
        if self.product_ids:
            products = self.product_ids
        elif scale.sync_all_products:
            products = self.env['product.product'].search([
                ('default_code', '!=', False),
                ('default_code', '!=', ''),
            ])
        else:
            products = scale.product_ids

        success = 0
        errors = 0
        lines = []

        for product in products:
            try:
                if not product.default_code or not product.default_code.isdigit():
                    errors += 1
                    lines.append(f'SALTADO {product.default_code}: no numérico')
                    continue

                plu_data = {
                    'number': int(product.default_code),
                    'dept_code': scale.department_code,
                    'family_code': scale.family_code,
                    'name': (product.name or '')[:26],
                    'description': (product.name or '')[:26],
                    'plu_type': self._get_plu_type(product),
                    'price': product.list_price or 0.0,
                    'price_decimals': scale.price_decimals,
                    'label_code': scale.label_code,
                }

                raw_price = scale._price_to_scale_raw(plu_data['price'])
                if not scale._price_fits(raw_price):
                    errors += 1
                    lines.append(
                        f'ERROR {product.default_code}: precio '
                        f'{plu_data["price"]:.{scale.price_decimals}f} no entra '
                        f'en 6 dígitos con {scale.price_decimals} decimales'
                    )
                    continue

                ok, code, msg = proto.upsert_plu(plu_data)
                if ok:
                    success += 1
                else:
                    errors += 1
                    lines.append(f'ERROR {product.default_code}: {msg}')
            except Exception as e:
                errors += 1
                lines.append(f'EXCEPCIÓN {product.default_code}: {str(e)}')

        total = len(products)
        state = 'success' if errors == 0 else ('partial' if success > 0 else 'error')

        scale.write({'last_sync_product': fields.Datetime.now()})

        return {
            'product_count': total,
            'success_count': success,
            'error_count': errors,
            'state': state,
            'end_time': fields.Datetime.now(),
            'log': '\n'.join(lines) if lines else 'Sin errores',
        }

    def _sync_vendors(self, proto, scale, log_record):
        """Sincroniza vendedores a una balanza."""
        partners = self.env['res.partner'].search([
            ('kretz_vendor_code', '>', 0),
            ('kretz_vendor_code', '<=', 36),
        ])

        success = 0
        errors = 0
        lines = []

        for partner in partners:
            try:
                vendor_data = {
                    'code': partner.kretz_vendor_code,
                    'name': (partner.name or '')[:20],
                }
                ok, code, msg = proto.upsert_vendor(vendor_data)
                if ok:
                    success += 1
                else:
                    errors += 1
                    lines.append(f'ERROR {partner.name}: {msg}')
            except Exception as e:
                errors += 1
                lines.append(f'EXCEPCIÓN {partner.name}: {str(e)}')

        total = len(partners)
        state = 'success' if errors == 0 else ('partial' if success > 0 else 'error')

        scale.write({'last_sync_vendor': fields.Datetime.now()})

        return {
            'product_count': total,
            'success_count': success,
            'error_count': errors,
            'state': state,
            'end_time': fields.Datetime.now(),
            'log': '\n'.join(lines) if lines else 'Sin errores',
        }

    def _verify_prices_post_sync(self, scale):
        """Verifica precios después de sincronizar (método interno)."""
        try:
            proto = scale._get_protocol()
            slot_map = scale._get_slot_map()
            with proto:
                products = self.env['product.product'].search([
                    ('default_code', '!=', False),
                    ('default_code', '!=', ''),
                ])

                mismatches = 0
                checked = 0

                for product in products:
                    if not product.default_code or not product.default_code.isdigit():
                        continue

                    try:
                        ok, _code, data = scale._read_plu(
                            proto, int(product.default_code), slot_map
                        )
                        if not ok or not data or len(data) < 83:
                            continue

                        # La balanza almacena el precio como entero escalado
                        # según los decimales configurados en la balanza
                        scale_price = int(data[77:83])
                        odoo_price = scale._price_to_scale_raw(
                            product.list_price
                        )
                        checked += 1

                        if scale_price != odoo_price:
                            mismatches += 1
                    except Exception:
                        pass

            if slot_map != scale._get_slot_map():
                scale.write({
                    'plu_slot_map': slot_map,
                    'plu_slot_map_date': fields.Datetime.now(),
                })

            if mismatches == 0:
                return f'{scale.name}: ✓ {checked} verificados, sin diferencias'
            else:
                return f'{scale.name}: ⚠ {mismatches} diferencias de {checked} verificados'

        except Exception as e:
            return f'{scale.name}: ✗ Error en verificación: {str(e)}'
