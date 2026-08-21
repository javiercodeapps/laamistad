from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
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

    def _compute_mpld3_chart(self):
        for rec in self:
            # Design your mpld3 figure:
            plt.scatter([1, 10], [5, 9])
            figure = plt.figure()
            rec.mpld3_chart = self.convert_figure_to_json(figure)

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


    def compute_sale_ids(self):
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
        ids = {}
        cids = {}
        gtotales = {}
        gcantidad = {}
        ttotales = {}
        tcantidad = {}
        self.env['account.cashbox.sale.line'].search([('cashbox_id','=',self.id)]).unlink()
        logs = ' '
        if self.closing_date:
            moves=self.env['account.payment'].search([('company_id','=',self.company_id.id),('state','=','posted'),('date','>=',self.opening_date),('date','<=',self.closing_date)])
        else:
            moves=self.env['account.payment'].search([('company_id','=',self.company_id.id),('state','=','posted'),('date','>=',self.opening_date)])
        for pay in moves:
            if 'OP-X' in '%s' % pay.name:
                if pay.journal_id.name not in gtotales:
                    gtotales[pay.journal_id.name] = {}
                    gcantidad[pay.journal_id.name] = {}
                if pay.partner_id.name not in gtotales[pay.journal_id.name]:
                    gtotales[pay.journal_id.name][pay.partner_id.name] = 0
                    gcantidad[pay.journal_id.name][pay.partner_id.name] = 0
                gtotales[pay.journal_id.name][pay.partner_id.name] += pay.amount_signed
                gcantidad[pay.journal_id.name][pay.partner_id.name] += 1
            if 'Central' in '%s' % pay.journal_id.name or 'Banco' in '%s' % pay.journal_id.name:
                if pay.journal_id.name not in ttotales:
                    ttotales[pay.journal_id.name] = 0
                    tcantidad[pay.journal_id.name] = 0
                ttotales[pay.journal_id.name] += pay.amount_signed
                tcantidad[pay.journal_id.name] += 1
            if 'RE' in '%s' % pay.name:
                # Busco si el pago corresponde a un pedido de fecha anterior a hoy
                ctacte=False
                for line in pay.reconciled_invoice_ids:
                    for so in line.line_ids.sale_line_ids:
                        if so.create_date.date() < self.opening_date:
                            ctacte=True
                if ctacte:
                    if pay.journal_id.name not in totales:
                        totales[pay.journal_id.name]=0
                        cantidad[pay.journal_id.name]=0
                        ids[pay.journal_id.name]=[]
                    totales[pay.journal_id.name]+=pay.amount_signed
                    cantidad[pay.journal_id.name]+=1
                    ids[pay.journal_id.name].append(so.order_id.id)
                else:
                    if pay.journal_id.name not in cobros:
                        cobros[pay.journal_id.name]=0
                        ccobros[pay.journal_id.name]=0
                        cids[pay.journal_id.name]=[]
                    cobros[pay.journal_id.name]+=pay.amount_signed
                    ccobros[pay.journal_id.name]+=1
                    cids[pay.journal_id.name].append(so.order_id.id)


        for t in totales:
            type_orden = '1-'
            for o in orden:
                if o in t:
                    type_orden='%s' % orden[o]

            self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' % (type_orden,t),
                                                              'count':cantidad[t],
                                                              'amount':totales[t],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'CTACTE'})
        for t in cobros:
            type_orden = '1-'
            for o in orden:
                if o in t:
                    type_orden='%s' % orden[o]
            self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' % (type_orden,t),
                                                              'count':ccobros[t],
                                                              'amount':cobros[t],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'COBROS',})
        for j in gtotales:
            type_orden = '1-'
            for o in orden:
                if o in j:
                    type_orden='%s' % orden[o]
            for t in gtotales[j]:
                self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s %s' % (type_orden,j,t),'count':gcantidad[j][t],'amount':gtotales[j][t],'cashbox_id':self.id,'type_pay_id':'GASTOS'})
        for t in ttotales:
            type_orden = '1-'
            for o in orden:
                if o in t:
                    type_orden='%s' % orden[o]
            self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' %(type_orden,t),'count':tcantidad[t],'amount':ttotales[t],'cashbox_id':self.id,'type_pay_id':'RECAUDACION'})
        if True:
            totales = {}
            cantidad = {}
            descuentos = {}
            descuentosc= {}
            fecha_desde = self.opening_date + timedelta(hours=6)
            # Busco las ventas
            if self.closing_date:
                fecha_hasta = self.closing_date + timedelta(days=1)
                #ventas=self.env['sale.order'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('create_date','>=',self.opening_date),('create_date','<=',self.closing_date)])
                ventas=self.env['sale.order'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('create_date','>=',fecha_desde),('create_date','<=',fecha_hasta)])
            else:
                ventas=self.env['sale.order'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('create_date','>=',fecha_desde)])
            if ventas:
                ids={}
                for v in ventas:
                    # Unificar Tipo MP como uno solo
                    if v.create_date.date() < self.opening_date:
                        continue
                    fecha_venta =  v.create_date - timedelta(hours=6)
                    if fecha_venta.date() > self.closing_date:
                        continue
                    if v.invoice_status == 'to invoice':
                        continue
                    if v.type_id.name not in totales:
                        totales[v.type_id.name]=0
                        cantidad[v.type_id.name]=0
                        ids[v.type_id.name]=[]
                    totales[v.type_id.name]+=v.amount_total
                    cantidad[v.type_id.name]+=1
                    ids[v.type_id.name].append(v.id)
                    # Busco descuentos en la orden
                    _logger.info('VENTAS %s %s %s %s ' % (v.type_id.name,v.create_date,v.name,v.amount_total ) )
                    logs +='VENTAS %s %s %s %s ' % (v.type_id.name,v.create_date,v.name,v.amount_total)
                    for line in v.order_line:
                        if line.product_id.name and 'DESCUENTO' in line.product_id.name:
                            totales[v.type_id.name]+=(line.price_total * -1)
                            k = '%s %s' % (v.type_id.name,line.product_id.name[:9])
                            if k not in descuentos:
                                descuentos[k] = 0
                                descuentosc[k] = 0
                            descuentos[k] -= line.price_total 
                            descuentosc[k]+=1
                            _logger.info('DESCUENTO %s %s %s %s ' % (v.type_id.name,line.product_id.name[:9],line.price_total,v.name ) )

            v = []
            for t in totales:
                type_orden = '1-'
                for o in orden:
                    if o in '%s' % t:
                        type_orden='%s' % orden[o]
                self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' % (type_orden,t),
                                                              'count':cantidad[t],
                                                              'amount':totales[t],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'VENTAS',})
        # Preparo gastos desde los asientos contables VENTAS
        gastos = {}
        gastosr = {}
        for i in self.env['account.cashbox.resumen.config'].search([('tipo_resumen','!=','resumen'),('tipo_fecha','=','ventas')]):
            tipo = i.type_pay_id
            gasto = i.type_id
            cuenta = i.cuentas
            if tipo != 'COMPRAS':
                gastos['%s-%s-%s' % (tipo,gasto,cuenta)] = 0
                gastosr['%s-%s' % (tipo,gasto)] = 0
        if self.closing_date:
            moves=self.env['account.move'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date','>=',self.opening_date),('date','<=',self.closing_date)])
        else:
            moves=self.env['account.move'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date','>=',self.opening_date)])
        gastos2 = {}
        for ac in moves:
            for m in ac.line_ids:
                for gg in gastos:
                    (tipo,gasto,cuenta)=gg.split('-')
                    if m.account_id.code.startswith(cuenta):
                        if tipo == 'SUELDOS':
                            gg2='%s-%s-%s' % (tipo,m.account_id.name,m.account_id.code)
                            gastosr['%s-%s' % (tipo,m.account_id.name)] = 0
                        else:
                            gg2='%s-%s-%s' % (tipo,gasto,cuenta)
                        gastos2[gg2] = 0

        gastos = gastos2
        _logger.info('GASTOS %s' % gastos)
        for ac in moves:
            for m in ac.line_ids:
                for gg in gastos:
                    (tipo,gasto,cuenta)=gg.split('-')
                    if gasto != 'SUELDOS':
                        if m.account_id.code.startswith(cuenta):
                            _logger.info('%s %s %s %s %s %s %s' % (tipo,m.account_id.name,cuenta,m.debit,m.credit,m,m.date) )
                            logs +=      '%s %s %s %s %s %s %s' % (tipo,m.account_id.name,cuenta,m.debit,m.credit,m,m.date)
                            if m.price_unit > 0:
                                if m.debit > 0:
                                    gastos[gg] += m.price_unit * m.quantity
                                    gastosr['%s-%s' % (tipo,gasto) ] += m.price_unit * m.quantity
                                else:
                                    gastos[gg] -= m.price_unit * m.quantity
                                    gastosr['%s-%s' % (tipo,gasto) ] -= m.price_unit * m.quantity
                            else:
                                if '9900000' in m.account_id.code:
                                    gastos[gg] += m.credit - m.debit
                                    gastosr['%s-%s' % (tipo,gasto) ] += m.credit - m.debit
                                else:
                                    gastos[gg] += m.debit - m.credit
                                    gastosr['%s-%s' % (tipo,gasto) ] += m.debit - m.credit
        _logger.info('DESCUENTOS %s' % descuentos)
        gastosr['GASTOS GENERALES-01_DESCUENTOS']  = 0
        for k in descuentos:
            gastosr['GASTOS GENERALES-01_DESCUENTOS'] += descuentos[k]
        _logger.info('DESCUENTOS %s' % gastosr)
        for gg in gastosr:
             (tipo,gasto)=gg.split('-')
             self.env['account.cashbox.sale.line'].create({'type_id':gasto,
                                                              'count':0,
                                                              'amount':gastosr[gg],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':tipo,
                                                              }
                                                              )
        # Preparo gastos desde los asientos contables COMPRAS
        descuentos = {}
        gastos = {}
        gastosr = {}
        for i in self.env['account.cashbox.resumen.config'].search([('tipo_resumen','!=','resumen'),('tipo_fecha','=','compras')]):
            tipo = i.type_pay_id
            gasto = i.type_id
            cuenta = i.cuentas
            if tipo != 'COMPRAS':
                gastos['%s-%s-%s' % (tipo,gasto,cuenta)] = 0
                gastosr['%s-%s' % (tipo,gasto)] = 0
        if self.closing_date:
            moves=self.env['account.move'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date','>=',self.opening_compra),('date','<=',self.closing_compra)])
        else:
            moves=self.env['account.move'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date','>=',self.opening_compra)])
        gastos2 = {}
        for ac in moves:
            for m in ac.line_ids:
                for gg in gastos:
                    (tipo,gasto,cuenta)=gg.split('-')
                    if m.account_id.code.startswith(cuenta):
                        if tipo == 'SUELDOS':
                            gg2='%s-%s-%s' % (tipo,m.account_id.name,m.account_id.code)
                            gastosr['%s-%s' % (tipo,m.account_id.name)] = 0
                        else:
                            gg2='%s-%s-%s' % (tipo,gasto,cuenta)
                        gastos2[gg2] = 0

        gastos = gastos2
        _logger.info('GASTOS %s' % gastos)
        for ac in moves:
            for m in ac.line_ids:
                for gg in gastos:
                    (tipo,gasto,cuenta)=gg.split('-')
                    #if gasto != 'SUELDOS':
                    if m.account_id.code.startswith(cuenta):
                        _logger.info('%s %s %s %s %s %s %s' % (tipo,m.account_id.name,cuenta,m.debit,m.credit,m,m.date) )
                        logs +=      '%s %s %s %s %s %s %s' % (tipo,m.account_id.name,cuenta,m.debit,m.credit,m,m.date)
                        if m.price_unit > 0:
                            if m.debit > 0:
                                gastos[gg] += m.price_unit * m.quantity
                                gastosr['%s-%s' % (tipo,gasto) ] += m.price_unit * m.quantity
                            else:
                                gastos[gg] -= m.price_unit * m.quantity
                                gastosr['%s-%s' % (tipo,gasto) ] -= m.price_unit * m.quantity
                        else:
                            gastos[gg] += m.debit - m.credit
                            gastosr['%s-%s' % (tipo,gasto) ] += m.debit - m.credit
       #for k in descuentos:
       #    gastosr['GASTOS GENERALES-01_DESCUENTOS'] += descuentos[k]
        for gg in gastosr:
             (tipo,gasto)=gg.split('-')
             self.env['account.cashbox.sale.line'].create({'type_id':gasto,
                                                              'count':0,
                                                              'amount':gastosr[gg],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':tipo,
                                                              }
                                                              )

        # Preparo gastos desde los asientos contables
        gastos = {}
        gastosr = {}
        #for i in open('/tmp/cuentas.txt').readlines():
        #    (tipo,gasto,cuenta)=i.strip().split('	')
        for i in self.env['account.cashbox.resumen.config'].search([('tipo_resumen','!=','resumen')]):
            tipo = i.type_pay_id
            gasto = i.type_id
            cuenta = i.cuentas
            if tipo == 'COMPRAS':
                gastos['%s-%s-%s' % (tipo,gasto,cuenta)] = 0
                gastosr['%s-%s' % (tipo,gasto)] = 0
        if self.closing_compra:
            moves=self.env['account.move'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date','>=',self.opening_compra),('date','<=',self.closing_compra)])
        else:
            moves=self.env['account.move'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date','>=',self.opening_compra)])
        for ac in moves:
            _logger.info('%s %s ' % (ac.date,ac.name) )
            for m in ac.line_ids:
                for gg in gastos:
                    (tipo,gasto,cuenta)=gg.split('-')
                    if m.account_id.code.startswith(cuenta):
                        _logger.info('%s %s %s %s %s %s %s ' % (tipo,m.account_id.name,cuenta,m.debit,m.credit,m.price_unit,m.date) )
                        logs +=      '%s %s %s %s %s %s %s ' % (tipo,m.account_id.name,cuenta,m.debit,m.credit,m.price_unit,m.date)
                        if m.debit > 0:
                            gastos[gg] += m.price_unit * m.quantity
                            gastosr['%s-%s' % (tipo,gasto) ] += m.price_unit * m.quantity
                        else:
                            gastos[gg] -= m.price_unit * m.quantity
                            gastosr['%s-%s' % (tipo,gasto) ] -= m.price_unit * m.quantity
        for gg in gastosr:
             (tipo,gasto)=gg.split('-')
             self.env['account.cashbox.sale.line'].create({'type_id':gasto,
                                                              'count':0,
                                                              'amount':gastosr[gg],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':tipo,
                                                              }
                                                              )

        self.resumen_ids = self.env['account.cashbox.sale.line'].search([('cashbox_id','=',self.id)])
        # Preparo el resumen desde las lineas anteriores
        resumen = {}
        resumen['CTACTE'] = 0
        resumen['VENTAS'] = 0
        resumen['COBROS'] = 0
        for i in self.env['account.cashbox.resumen.config'].search([('tipo_resumen','!=','resumen')]):
            resumen[i.type_pay_id] = 0
            resumen[i.type_id] = 0
        cantidad = {}
        # Preparo Resumen
        for r in self.resumen_ids:
            if r.type_pay_id == 'COMPRAS':
                type_pay_id = r.type_id
            else:
                type_pay_id = r.type_pay_id
            if type_pay_id not in resumen:
                resumen[type_pay_id]  = 0
            resumen[type_pay_id] += r.amount
        _logger.info('%s' % resumen)
        for i in self.env['account.cashbox.resumen.config'].search([('tipo_resumen','=','resumen')],order='type_pay_id'):
            try:
                resumen[i.type_pay_id] = eval(i.valor)
            except:
                resumen[i.type_pay_id] = 0
            cantidad[i.type_pay_id] = i.color if i.color else 0


        for i in self.env['account.cashbox.resumen.config'].search([('tipo_resumen','=','resumen')]):
            self.env['account.cashbox.sale.line'].create({'type_id':'%s' % i.type_pay_id,
                                                              'amount':resumen[i.type_pay_id],
                                                              'count':cantidad[i.type_pay_id],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'TOTALES',
                                                              }
                                                              )

      # lines =  ['01-VENTAS','02-VENTAS PERCIBIDAS','10-COMPRAS MERCADERIAS VARIAS','11-MERCADO','19-TOTAL COMPRAS','30-INSUMOS','20-DIFERENCIA','21-COMERCIALIZACION %','31-SUELDOS','32-GASTOS GENERALES','39-TOTAL GASTOS','50-GANANCIA']
      # for l in lines:
      #     resumen[l] = 0
      #     cantidad[l] = 0
      # for r in self.resumen_ids:
      #     if 'VENTAS' in r.type_pay_id:
      #         resumen['01-VENTAS'] += r.amount
      #     if 'RECAUDACION' in r.type_pay_id:
      #         resumen['02-VENTAS PERCIBIDAS'] += r.amount
      #     if 'COMPRAS' in r.type_pay_id:
      #         if 'VARIAS' in r.type_id:
      #             resumen['10-COMPRAS MERCADERIAS VARIAS'] += r.amount
      #         if 'MERCADO' in r.type_id:
      #             resumen['11-MERCADO'] += r.amount
      #         if 'INSUMOS' in r.type_id:
      #             resumen['30-INSUMOS'] += r.amount
      #         if 'VACIOS' in r.type_id:
      #             resumen['32-GASTOS GENERALES'] += r.amount
      #     if 'GASTOS GENERALES' in r.type_pay_id:
      #         resumen['32-GASTOS GENERALES'] += r.amount
      #     if 'SUELDOS' in r.type_pay_id:
      #         resumen['31-SUELDOS'] += r.amount 
      # # Resumen
      # cantidad['01-VENTAS'] = 1
      # cantidad['02-VENTAS PERCIBIDAS'] = 1
      # resumen['19-TOTAL COMPRAS'] = resumen['10-COMPRAS MERCADERIAS VARIAS'] + resumen['11-MERCADO'] 
      # cantidad['19-TOTAL COMPRAS'] = 1
      # resumen['20-DIFERENCIA'] = resumen['01-VENTAS'] - resumen['19-TOTAL COMPRAS']
      # cantidad['20-DIFERENCIA'] = 1
      # if resumen['19-TOTAL COMPRAS'] != 0:
      #     resumen['21-COMERCIALIZACION %'] = (resumen['20-DIFERENCIA'] / resumen['19-TOTAL COMPRAS']) * 100
      # cantidad['21-COMERCIALIZACION %'] = 1
      # resumen['39-TOTAL GASTOS'] = resumen['30-INSUMOS'] + resumen['31-SUELDOS'] + resumen['32-GASTOS GENERALES']
      # cantidad['39-TOTAL GASTOS'] = 1
      # resumen['50-GANANCIA'] = resumen['20-DIFERENCIA'] - resumen['39-TOTAL GASTOS']
      # cantidad['50-GANANCIA'] = 2
      # for l in lines:
      #     self.env['account.cashbox.sale.line'].create({'type_id':'%s' % l,
      #                                                       'amount':resumen[l],
      #                                                       'count':cantidad[l],
      #                                                       'cashbox_id':self.id,
      #                                                       'type_pay_id':'TOTALES',
      #                                                       }
      #                                                       )

        self.logs = logs


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


