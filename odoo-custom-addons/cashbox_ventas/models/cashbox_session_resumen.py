from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
from odoo.osv import expression
import logging
import matplotlib.pyplot as plt

_logger = logging.getLogger(__name__)

class CashBoxResumen(models.Model):
    _name = 'account.cashbox.resumen'
    _inherit = ['abstract.mpld3.parser']

    name = fields.Char(string='Name')
    opening_date=fields.Date(string='Fecha de Apertura')
    closing_date=fields.Date(string='Fecha de Cierre')
    opening_compra=fields.Date(string='Fecha de Apertura Compra')
    closing_compra=fields.Date(string='Fecha de Cierre Compra')
    resumen_ids = fields.One2many('account.cashbox.sale.line','cashbox_id')#,compute='_compute_sale_ids')
    totales_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','=','TOTALES')])
    sueldos_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','=','SUELDOS')])
    ventas_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','=','VENTAS'),('type_id','!=','')])
    ctacte_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','in',['CTACTE'])])
    transf_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','in',['RECAUDACION','TRANSFERENCIAS'])])
    gastos_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','=','GASTOS GENERALES')])
    compras_ids= fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','in',['CAJON','COMPRAS'])])
    #cashbox_ids= fields.Char(string='Cajas resumidas')
    #cashbox_ids= fields.One2many('account.cashbox.session','resumen_id',string='Cajas resumidas')#,domain=[('resumen_id','=','')])
    total_ventas = fields.Float('Total Ventas' ,compute='_compute_total')
    total_cobros = fields.Float('Total Cobros')
    total_gastos = fields.Float('Total Gastos')
    total_compras= fields.Float('Total Compras')
    total_recaudacion = fields.Float('Total Recaudacion')
    company_id = fields.Many2one('res.company', 'Company')
    logs = fields.Text(string='Log')

    mpld3_chart = fields.Json( string='Mpld3 Chart', compute='_compute_mpld3_chart',)

    # Tope del log que se guarda en el resumen (evita strings gigantes en memoria)
    MAX_LOGS = 200000
    MAX_LOG_LINES = 20000

    def _compute_mpld3_chart(self):
        for rec in self:
            # La figura se cierra siempre: matplotlib mantiene una referencia a
            # cada figura creada, así que sin close() se acumulan en memoria
            # cada vez que se muestra el resumen.
            figure = plt.figure()
            try:
                figure.add_subplot(111).scatter([1, 10], [5, 9])
                rec.mpld3_chart = self.convert_figure_to_json(figure)
            finally:
                plt.close(figure)

    def _compute_total(self):
        self.total_ventas = 0
        self.total_cobros = 0
        self.total_gastos = 0
        self.total_compras = 0
        self.total_recaudacion = 0
        for i in self.ventas_ids:
            self.total_ventas+=i.amount
        for i in self.ctacte_ids:
            self.total_cobros+=i.amount
        for i in self.compras_ids:
            self.total_compras+=i.amount
        for i in self.gastos_ids:
            self.total_gastos+=i.amount
        for i in self.transf_ids:
            self.total_recaudacion+=i.amount

    # ------------------------------------------------------------------
    # Helpers del resumen
    # ------------------------------------------------------------------

    def _log_domain(self, lines, label, model, domain):
        """Registra un dominio de búsqueda en el log del resumen y del servidor.

        Se agrega a ``lines`` para que aparezca (agrupado al principio) en el
        campo ``logs`` y además se envía al logger de Odoo, así se puede
        depurar el cálculo aunque el texto del campo se trunque.
        """
        line = 'DOMINIO | %s | %s | %s' % (label, model, list(domain))
        lines.append(line)
        _logger.info('[RESUMEN %s] %s', self.ids, line)

    def _cashbox_type_orden(self, name, orden):
        """Código de orden (1 a 4) según el nombre de la forma de pago."""
        type_orden = '1-'
        for o, codigo in orden.items():
            if o in '%s' % name:
                type_orden = codigo
        return type_orden

    def _cashbox_create_lines(self, vals):
        """Crea de una sola vez las líneas del resumen."""
        vals = [v for v in vals if v]
        if vals:
            self.env['account.cashbox.sale.line'].create(vals)

    def _cashbox_create_group(self, group, type_pay_id, orden, counts=None):
        """Crea una línea por cada clave de ``group`` (importe acumulado).

        ``counts`` es opcional: diccionario clave -> cantidad.
        """
        counts = counts or {}
        self._cashbox_create_lines([
            {
                'type_id': '%s-%s' % (self._cashbox_type_orden(key, orden), key),
                'count': counts.get(key, 0),
                'amount': amount,
                'cashbox_id': self.id,
                'type_pay_id': type_pay_id,
            }
            for key, amount in group.items()
        ])

    def _cashbox_create_gastos(self, gastosr):
        """Crea las líneas de gastos/compras a partir de 'TIPO-DETALLE'."""
        self._cashbox_create_lines([
            {
                'type_id': key.split('-', 1)[1],
                'count': 0,
                'amount': amount,
                'cashbox_id': self.id,
                'type_pay_id': key.split('-', 1)[0],
            }
            for key, amount in gastosr.items()
        ])

    def _cashbox_account_domain(self, date_from, date_to, prefixes):
        """Dominio de los apuntes de las cuentas configuradas en el período.

        El filtro por código de cuenta se hace en SQL: traer todos los asientos
        del período (y después todas sus líneas) es lo que agotaba la memoria.
        """
        domain = [
            ('company_id', '=', self.company_id.id),
            ('move_id.state', '!=', 'cancel'),
            ('move_id.date', '>=', date_from),
        ]
        if date_to is not None:
            domain.append(('move_id.date', '<=', date_to))
        prefixes = [p for p in prefixes if p is not None]
        # Si alguna cuenta configurada no tiene código, no se puede filtrar por
        # prefijo en SQL (esa regla haría match con todo) y se dejan todas las
        # líneas del período.
        # OJO: expression.OR/AND reciben una lista de DOMINIOS (cada uno una
        # lista de hojas), no una lista de hojas sueltas.
        if prefixes and all(prefixes):
            prefix_domains = [
                [('account_id.code', '=like', '%s%%' % p)] for p in prefixes]
            domain = expression.AND([domain, expression.OR(prefix_domains)])
        return domain

    def _cashbox_gastos(self, configs, date_from, date_to=None, compras_mode='exclude',
                        price_unit_mode='conditional', special_9900000=False,
                        domain_log=None, label=''):
        """Suma los apuntes de las cuentas configuradas.

        Devuelve ``{'TIPO-DETALLE': importe}`` (incluye los detalles que no
        tuvieron movimientos, en 0, igual que antes) y el log del bloque.

        Los apuntes se leen en lotes para no cargar todo el período en memoria.

        ``compras_mode``: 'exclude' ignora las configuraciones de tipo COMPRAS
        (gastos de ventas y compras) y 'only' toma sólo esas (total compras).

        Si se pasa ``domain_log`` (lista), se registra allí el dominio usado en
        la búsqueda de ``account.move.line`` con la etiqueta ``label``.
        """
        gastosr = {}
        rules = []
        for i in configs:
            tipo, gasto, cuenta = i.type_pay_id, i.type_id, (i.cuentas or '')
            if compras_mode == 'exclude' and tipo == 'COMPRAS':
                continue
            if compras_mode == 'only' and tipo != 'COMPRAS':
                continue
            gastosr.setdefault('%s-%s' % (tipo, gasto), 0.0)
            rules.append((tipo, gasto, cuenta))
        if not rules:
            if domain_log is not None:
                domain_log.append(
                    'DOMINIO | %s | account.move.line | SIN REGLAS (no se ejecuta la busqueda)'
                    % (label or 'Apuntes contables'))
            return gastosr, []
        domain = self._cashbox_account_domain(
            date_from, date_to, [cuenta for (_t, _g, cuenta) in rules])
        if domain_log is not None:
            self._log_domain(domain_log, label or 'Apuntes contables',
                             'account.move.line', domain)
        log = []
        offset = 0
        batch = 2000
        while True:
            lines = self.env['account.move.line'].search(
                domain, order='id', limit=batch, offset=offset)
            if not lines:
                break
            for m in lines:
                code = m.account_id.code or ''
                for (tipo, gasto, cuenta) in rules:
                    if not code.startswith(cuenta):
                        continue
                    if tipo == 'SUELDOS':
                        # Los sueldos se agrupan por nombre de cuenta
                        key = '%s-%s' % (tipo, m.account_id.name or '')
                        gastosr.setdefault(key, 0.0)
                    else:
                        key = '%s-%s' % (tipo, gasto)
                    price_unit = m.price_unit or 0.0
                    amount = price_unit * (m.quantity or 0.0)
                    if price_unit_mode == 'signed':
                        # Total compras: siempre precio x cantidad, signo por débito
                        if m.debit <= 0:
                            amount = -amount
                    elif price_unit > 0:
                        if m.debit <= 0:
                            amount = -amount
                    elif special_9900000 and '9900000' in code:
                        amount = (m.credit or 0.0) - (m.debit or 0.0)
                    else:
                        amount = (m.debit or 0.0) - (m.credit or 0.0)
                    gastosr[key] += amount
                    if len(log) < self.MAX_LOG_LINES:
                        log.append('%s %s %s %s %s %s' % (
                            tipo, m.account_id.name, cuenta, m.debit, m.credit, m.date))
            offset += batch
        return gastosr, log

    # ------------------------------------------------------------------
    # Proceso del resumen
    # ------------------------------------------------------------------

    def compute_sale_ids(self):
        if not self.opening_date:
            raise UserError('Debe indicar la fecha de apertura del resumen.')
        orden = {}
        orden['Efectivo'] = '1'
        orden['MP'] = '2'
        orden['Mercado Pago'] = '2'
        orden['Otros'] = '3'
        orden['OTROS'] = '3'
        orden['CTACTE'] = '4'
        cobros = {}
        ccobros = {}
        totales = {}
        cantidad = {}
        gtotales = {}
        gcantidad = {}
        ttotales = {}
        tcantidad = {}
        logs = []
        domain_log = ['=== DOMINIOS DE BUSQUEDA ===']
        line_domain = [('cashbox_id','=',self.id)]
        self._log_domain(domain_log, 'Lineas del resumen (limpieza y lectura)',
                         'account.cashbox.sale.line', line_domain)
        self.env['account.cashbox.sale.line'].search(line_domain).unlink()

        # ------------------------------------------------------------------
        # Pagos: gastos (OP-X), transferencias y cobros
        # ------------------------------------------------------------------
        pay_domain = [('company_id','=',self.company_id.id),('state','=','posted'),('date','>=',self.opening_date)]
        if self.closing_date:
            pay_domain.append(('date','<=',self.closing_date))
        self._log_domain(domain_log, 'Pagos (search_read)', 'account.payment', pay_domain)
        # Los pagos se leen por lotes (search_read trae sólo los campos usados):
        # iterar el recordset completo con el ORM carga en memoria todos los
        # pagos y sus relaciones.
        pay_fields = ['name','journal_id','partner_id','amount_signed']
        pay_offset = 0
        pay_batch = 2000
        old_invoice_domain_logged = False
        while True:
            pays = self.env['account.payment'].search_read(
                pay_domain, pay_fields, order='id', limit=pay_batch, offset=pay_offset)
            if not pays:
                break
            # Facturas conciliadas de los pagos 'RE' del lote
            re_pays = self.env['account.payment'].browse(
                [p['id'] for p in pays if 'RE' in str(p['name'])])
            pay_invoices = {}
            old_invoices = set()
            if re_pays:
                # El campo es computado: se fuerza un único cálculo para el lote
                re_pays.mapped('reconciled_invoice_ids')
                all_invoice_ids = set()
                for pay in re_pays:
                    pay_invoices[pay.id] = pay.reconciled_invoice_ids.ids
                    all_invoice_ids.update(pay_invoices[pay.id])
                if all_invoice_ids:
                    # Facturas con líneas de pedidos anteriores a la apertura
                    old_invoice_domain = [
                        ('move_id','in',list(all_invoice_ids)),
                        ('sale_line_ids.create_date','<',self.opening_date),
                    ]
                    if not old_invoice_domain_logged:
                        self._log_domain(
                            domain_log,
                            'Facturas de pedidos anteriores (primer lote con RE)',
                            'account.move.line', old_invoice_domain)
                        old_invoice_domain_logged = True
                    old_invoices = set(self.env['account.move.line'].search(
                        old_invoice_domain).mapped('move_id').ids)
            for p in pays:
                journal = p['journal_id'][1] if p['journal_id'] else False
                partner = p['partner_id'][1] if p['partner_id'] else False
                amount = p['amount_signed'] or 0.0
                if 'OP-X' in str(p['name']):
                    gtotales.setdefault(journal, {})
                    gcantidad.setdefault(journal, {})
                    gtotales[journal][partner] = gtotales[journal].get(partner, 0.0) + amount
                    gcantidad[journal][partner] = gcantidad[journal].get(partner, 0) + 1
                if 'Central' in str(journal) or 'Banco' in str(journal):
                    ttotales[journal] = ttotales.get(journal, 0.0) + amount
                    tcantidad[journal] = tcantidad.get(journal, 0) + 1
                if 'RE' in str(p['name']):
                    # Pago de un pedido de fecha anterior a la apertura -> CTACTE
                    if any(i in old_invoices for i in pay_invoices.get(p['id'], [])):
                        totales[journal] = totales.get(journal, 0.0) + amount
                        cantidad[journal] = cantidad.get(journal, 0) + 1
                    else:
                        cobros[journal] = cobros.get(journal, 0.0) + amount
                        ccobros[journal] = ccobros.get(journal, 0) + 1
            pay_offset += pay_batch

        self._cashbox_create_group(totales, 'CTACTE', orden, cantidad)
        self._cashbox_create_group(cobros, 'COBROS', orden, ccobros)
        gastos_vals = []
        for j in gtotales:
            type_orden = self._cashbox_type_orden(j, orden)
            for t in gtotales[j]:
                gastos_vals.append({
                    'type_id':'%s-%s %s' % (type_orden,j,t),
                    'count':gcantidad[j][t],
                    'amount':gtotales[j][t],
                    'cashbox_id':self.id,
                    'type_pay_id':'GASTOS'})
        self._cashbox_create_lines(gastos_vals)
        self._cashbox_create_group(ttotales, 'RECAUDACION', orden, tcantidad)

        # ------------------------------------------------------------------
        # Ventas
        # ------------------------------------------------------------------
        totales = {}
        cantidad = {}
        descuentos = {}
        order_domain = [
            ('company_id','=',self.company_id.id),
            ('state','!=','cancel'),
            ('invoice_status','!=','to invoice'),
            ('create_date','>=',self.opening_date),
        ]
        if self.closing_date:
            order_domain.append(('create_date','<=',self.closing_date + timedelta(days=1)))
        self._log_domain(domain_log, 'Ventas (read_group)', 'sale.order', order_domain)
        # read_group agrega en SQL: no se cargan los pedidos ni sus líneas
        grupos = self.env['sale.order'].read_group(
            order_domain, ['amount_total:sum','__count'], ['type_id'], lazy=False)
        for g in grupos:
            tipo = g['type_id'][1] if g['type_id'] else False
            totales[tipo] = g['amount_total'] or 0.0
            cantidad[tipo] = g['__count']
        # Descuentos: sólo las líneas de productos de descuento (con el mismo
        # dominio de pedidos, sin traer las líneas de todos los pedidos)
        disc_domain = [
            ('order_id.company_id','=',self.company_id.id),
            ('order_id.state','!=','cancel'),
            ('order_id.invoice_status','!=','to invoice'),
            ('order_id.create_date','>=',self.opening_date),
            ('product_id.name','like','DESCUENTO'),
        ]
        if self.closing_date:
            disc_domain.append(('order_id.create_date','<=',self.closing_date + timedelta(days=1)))
        self._log_domain(domain_log, 'Descuentos (search_read)', 'sale.order.line', disc_domain)
        disc_lines = self.env['sale.order.line'].search_read(
            disc_domain, ['order_id','product_id','price_total'])
        if disc_lines:
            order_ids = list({l['order_id'][0] for l in disc_lines if l['order_id']})
            order_types = {}
            for row in self.env['sale.order'].browse(order_ids).read(['type_id']):
                order_types[row['id']] = row['type_id'][1] if row['type_id'] else False
            for line in disc_lines:
                tipo = order_types.get(line['order_id'][0]) if line['order_id'] else False
                product_name = line['product_id'][1] if line['product_id'] else ''
                # Busco descuentos en la orden
                totales[tipo] = totales.get(tipo, 0.0) - line['price_total']
                k = '%s %s' % (tipo, product_name[:9])
                descuentos[k] = descuentos.get(k, 0.0) - line['price_total']
                if len(logs) < self.MAX_LOG_LINES:
                    logs.append('DESCUENTO %s %s %s' % (tipo, product_name[:9], line['price_total']))
        for t in totales:
            logs.append('VENTAS %s %s %s' % (t, cantidad.get(t, 0), totales[t]))
        self._cashbox_create_group(totales, 'VENTAS', orden, cantidad)

        # ------------------------------------------------------------------
        # Gastos desde los asientos contables (ventas)
        # ------------------------------------------------------------------
        configs = self.env['account.cashbox.resumen.config']
        cfg_ventas_domain = [('tipo_resumen','!=','resumen'),('tipo_fecha','=','ventas')]
        self._log_domain(domain_log, 'Config cuentas (gastos ventas)',
                         'account.cashbox.resumen.config', cfg_ventas_domain)
        gastosr, glog = self._cashbox_gastos(
            configs.search(cfg_ventas_domain),
            self.opening_date, self.closing_date or None,
            compras_mode='exclude', price_unit_mode='conditional', special_9900000=True,
            domain_log=domain_log, label='Apuntes contables (gastos ventas)')
        logs.extend(glog)
        gastosr['GASTOS GENERALES-01_DESCUENTOS'] = 0
        for k in descuentos:
            gastosr['GASTOS GENERALES-01_DESCUENTOS'] += descuentos[k]
        self._cashbox_create_gastos(gastosr)

        # ------------------------------------------------------------------
        # Gastos desde los asientos contables (compras)
        # ------------------------------------------------------------------
        cfg_compras_domain = [('tipo_resumen','!=','resumen'),('tipo_fecha','=','compras')]
        self._log_domain(domain_log, 'Config cuentas (gastos compras)',
                         'account.cashbox.resumen.config', cfg_compras_domain)
        gastosr, glog = self._cashbox_gastos(
            configs.search(cfg_compras_domain),
            self.opening_compra, self.closing_compra if self.closing_date else None,
            compras_mode='exclude', price_unit_mode='conditional',
            domain_log=domain_log, label='Apuntes contables (gastos compras)')
        logs.extend(glog)
        self._cashbox_create_gastos(gastosr)

        # ------------------------------------------------------------------
        # Total compras desde los asientos contables
        # ------------------------------------------------------------------
        cfg_all_domain = [('tipo_resumen','!=','resumen')]
        self._log_domain(domain_log, 'Config cuentas (todas / total compras)',
                         'account.cashbox.resumen.config', cfg_all_domain)
        gastosr, glog = self._cashbox_gastos(
            configs.search(cfg_all_domain),
            self.opening_compra, self.closing_compra if self.closing_compra else None,
            compras_mode='only', price_unit_mode='signed',
            domain_log=domain_log, label='Apuntes contables (total compras)')
        logs.extend(glog)
        self._cashbox_create_gastos(gastosr)

        # Preparo el resumen desde las lineas anteriores
        resumen_lines = self.env['account.cashbox.sale.line'].search(line_domain)
        resumen = {}
        resumen['CTACTE'] = 0
        resumen['VENTAS'] = 0
        resumen['COBROS'] = 0
        for i in configs.search(cfg_all_domain):
            resumen[i.type_pay_id] = 0
            resumen[i.type_id] = 0
        cantidad = {}
        # Preparo Resumen
        for r in resumen_lines:
            if r.type_pay_id == 'COMPRAS':
                type_pay_id = r.type_id
            else:
                type_pay_id = r.type_pay_id
            if type_pay_id not in resumen:
                resumen[type_pay_id]  = 0
            resumen[type_pay_id] += r.amount
        _logger.info('%s' % resumen)
        cfg_resumen_domain = [('tipo_resumen','=','resumen')]
        self._log_domain(domain_log, 'Config resumen (formulas)',
                         'account.cashbox.resumen.config', cfg_resumen_domain)
        for i in configs.search(cfg_resumen_domain, order='type_pay_id'):
            try:
                resumen[i.type_pay_id] = eval(i.valor)
            except:
                resumen[i.type_pay_id] = 0
            cantidad[i.type_pay_id] = i.color if i.color else 0

        totales_vals = []
        for i in configs.search(cfg_resumen_domain):
            totales_vals.append({
                'type_id':'%s' % i.type_pay_id,
                'amount':resumen[i.type_pay_id],
                'count':cantidad[i.type_pay_id],
                'cashbox_id':self.id,
                'type_pay_id':'TOTALES',
            })
        self._cashbox_create_lines(totales_vals)

        # Los dominios van al principio para que no se pierdan si el detalle
        # del log se trunca por MAX_LOG_LINES / MAX_LOGS.
        all_logs = domain_log + ['=== DETALLE DEL CALCULO ==='] + logs
        log_text = '\n'.join(all_logs[:self.MAX_LOG_LINES])
        if len(log_text) > self.MAX_LOGS:
            log_text = log_text[:self.MAX_LOGS] + '\n... (log truncado)'
        self.logs = log_text


class CashBoxResumenConfig(models.Model):
    _name='account.cashbox.resumen.config'
    _order='type_id'
    type_pay_id = fields.Char(string='Tipo')
    type_id = fields.Char(string='Detalle')
    tipo_resumen = fields.Selection([('cuentas','Cuentas'),('ventas_ordenes','Ventas Ordenes'),('ventas','Ventas'),('compras_ordenes','Compras Ordenes'),('compras','Compras'),('resumen','Resumen')],string='Tipo')
    tipo_fecha = fields.Selection([('compras','Compras'),('ventas','Ventas')])
    #cuentas = fields.Many2many('account.account')
    cuentas = fields.Char('Cuentas')
    color = fields.Selection([('2','Rosa'),('1','Celeste')])
    valor = fields.Char(string='Valor')
