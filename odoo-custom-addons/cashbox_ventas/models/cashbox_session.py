from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import openpyxl
from io import BytesIO
from base64 import b64decode
import logging
_logger = logging.getLogger(__name__)
# Modificaciones
# Unificar los tipos de pago de Mercado Pago y MP en uno solo y CTACTE
# Solo tener en cuenta los pedidos de venta totalmente facturas,  y los pedidos enviados a CTACTE, para el resumen de caja. Los pedidos de venta que no esten facturados ni enviados a CTACTE no se tienen en cuenta.

# RESUMEN CTACTE , incoportar en la apertura de la caja, las ctasctes pendientes de cobro, y agregar al cierre las ventas y las combranzas del dia, para obtener un saldo final
# Para el calculo de inicio de la cuenta corriente, busco el resumen de la anterior si es que lo tengo
# Esto lo vamos a definir un nuevo tipo  como RESUMENCTACTE

# Separar Tipo Varios en los tipos de pago, como Efectivo, MP, Otros, CTACTE, Transferencias, Recaudacion, Descuentos y Gastos

# Revisar los cobras de cuenta corriente y fijar en el detalle si tienen descuento e imporcorporarlos a los del dia

# Vamos a controlar el inicio y fin del diario de MP, pero la carga del saldo final  tiene que ser automatica, cuando se preciona el boton de control


class CashBoxSale(models.Model):
    _inherit = ['account.cashbox.session']

    resumen_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',compute='_compute_sale_ids')
    ventas_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','=','VENTAS'),('type_id','!=','')])
    ctacte_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','in',['CTACTE'])])
    transf_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','in',['TRANSFERENCIAS','RECAUDACION'])])
    gastos_ids = fields.One2many('account.cashbox.sale.line','cashbox_id',domain=[('type_pay_id','in',['DESCUENTOS','GASTOS'])])
    total_ventas = fields.Float('Total Ventas',compute='_compute_total')
    total_cobros = fields.Float('Total Cobros')
    total_gastos = fields.Float('Total Gastos')
    total_recaudacion = fields.Float('Total Recaudacion')

    def _compute_total(self):
        self.total_ventas = 0
        self.total_cobros = 0
        self.total_gastos = 0
        self.total_recaudacion = 0
        for i in self.ventas_ids:
            self.total_ventas+=i.amount
        for i in self.ctacte_ids:
            self.total_cobros+=i.amount
        for i in self.gastos_ids:
            self.total_gastos+=i.amount
        for i in self.transf_ids:
            self.total_recaudacion+=i.amount

    def _compute_sale_ids(self,forzar=False):
        orden = {}
        orden['Efectivo'] = '1'
        orden['MP'] = '2'
        orden['Mercado Pago'] = '2'
        orden['Otros'] = '3'
        orden['CTACTE'] = '4'
        if self.state in ['draft','opened']:
            payments = self.env['account.payment'].search([
                           ('journal_id', 'in', self.cashbox_id.journal_ids.ids),
                           ('create_date', '>', self.opening_date),
                           ('state', '=', 'posted'),
                           ('cashbox_session_id', '=', False),
                           ])
            for payment in payments:
                payment.write({"cashbox_session_id": self.id})
        if self.state in ['draft','opened'] or forzar:
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
            descuentos = {}
            descuentosc= {}
            self.env['account.cashbox.sale.line'].search([('cashbox_id','=',self.id)]).unlink()
            # Armar resumen de gasto de la caja y detectar pagos de pedidos de otros dias
            for payids in self.payment_ids:
                for pay in payids:
                    if 'OP-X' in '%s' % pay.name:
                        if pay.state == 'posted':
                            if pay.journal_id.name not in gtotales:
                                gtotales[pay.journal_id.name] = {}
                                gcantidad[pay.journal_id.name] = {}
                            if pay.partner_id.name not in gtotales[pay.journal_id.name]:
                                gtotales[pay.journal_id.name][pay.partner_id.name] = 0
                                gcantidad[pay.journal_id.name][pay.partner_id.name] = 0
                            gtotales[pay.journal_id.name][pay.partner_id.name] += pay.amount_signed
                            gcantidad[pay.journal_id.name][pay.partner_id.name] += 1
                    if 'central' in '%s' % pay.journal_id.name or 'Central' in '%s' % pay.journal_id.name or 'Banco' in '%s' % pay.journal_id.name:
                        if pay.state == 'posted':
                            _logger.info('TRANS %s %s %s' % (pay,pay.name,pay.state))
                            if pay.journal_id.name not in ttotales:
                                ttotales[pay.journal_id.name] = 0
                                tcantidad[pay.journal_id.name] = 0
                            ttotales[pay.journal_id.name] += pay.amount_signed
                            tcantidad[pay.journal_id.name] += 1
                    if 'RE' in '%s' % pay.name:
                        # Busco si el pago corresponde a un pedido de fecha anterior a hoy
                        if pay.state == 'posted':
                            ctacte=False
                            so=False
                            for line in pay.reconciled_invoice_ids:
                                for so in line.line_ids.sale_line_ids:
                                    if so.create_date < self.opening_date:
                                        ctacte=True
                            if ctacte:
                                pay_name = pay.journal_id.name 
                                if pay_name not in totales:
                                    totales[pay_name]=0
                                    cantidad[pay_name]=0
                                    ids[pay_name]=[]
                                totales[pay_name]+=pay.amount_signed
                                cantidad[pay_name]+=1
                                ids[pay_name].append(so.order_id.id)
                                # Reviso si tiene descuento y lo agrego al total de descuentos
                                for line in so.order_id.order_line:
                                    if 'Mercado Pago' in pay_name or 'MP' in pay_name:
                                        pay_name = 'MP CTACTE'
                                    if 'Efectivo' in pay_name:
                                        pay_name = 'Efectivo CTACTE'
                                    if 'DESCUENTO' in line.product_id.name:
                                        _logger.info('DESCUENTO %s %s' % (so.order_id.name,line.price_total))
                                        # Hago la proporcion del descuento segun el tipo de pago, y lo agrego al total de descuentos
                                        if pay_name not in totales:
                                            totales[pay_name]=0
                                        totales[pay_name]+=(line.price_total * -1) * (pay.amount_total / so.order_id.amount_total)
                                        k = '%s %s' % (pay_name,line.product_id.name)
                                        if k not in descuentos:
                                            descuentos[k] = 0
                                            descuentosc[k] = 0
                                        descuentos[k] += line.price_total  * (pay.amount_total / so.order_id.amount_total)
                                        descuentosc[k]+=1
                            else:
                                if pay.journal_id.name not in cobros:
                                    cobros[pay.journal_id.name]=0
                                    ccobros[pay.journal_id.name]=0
                                    cids[pay.journal_id.name]=[]
                                cobros[pay.journal_id.name]+=pay.amount_signed
                                ccobros[pay.journal_id.name]+=1
                                if so:
                                    cids[pay.journal_id.name].append(so.order_id.id)

            for t in totales:
                type_orden = '1-'
                for o in orden:
                    if o in t:
                        type_orden='%s' % orden[o]

                self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' % (type_orden,t),
                                                              'count':cantidad.get(t,0),
                                                              'amount':totales[t],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'CTACTE',
                                                              'ventas_ids':[(6,0,ids[t])]})
                                    
            # Busco todas las ventas de cuentas corrientes pendientes de cobro a la fecha de aperturura si la caja anteriorio no tiene un RESUEMENCTACTE, sino busco el resumen de la caja anterior y lo agrego al cierre de la caja actual
            # Busco resumen anterior
            last_session = self.env['account.cashbox.session'].sudo().search([('cashbox_id', '=', rec.cashbox_id.id), ('state', '=', 'closed')], order="closing_date desc", limit=1)
            resumen = False
            if last_session:
                # Con esta session busco el detalle de la caja anterior y lo agrego al cierre de la caja actual
                # y sumar los totales de CTACTERESUMEN + VENTAS CTACTE + VENTAS CTACTE Factura - CTACTE 
                for line in last_session.resumen_ids:
                    ctactereumen = 0
                    if 'CTACTE' in line.type_id:
                        ctactereumen += line.amount
                    if 'CTACTE' in line.type_pay_id:
                        if 'RESUMEN' in line.type_id:
                            resumen = True
                            ctactereumen += line.amount
                        else:
                            ctactereumen -= line.amount
                if not reumen:
                    # Si no hay resumen, busco las ventas de CTACTE pendientes de cobro a la fecha de apertura de la caja
                    ventas=self.env['sale.order'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date_order','<',self.opening_date)])
                    for v in ventas:
                        if 'CTACTE' in v.type_id.name:
                            ctactereumen += v.amount_total

                self.env['account.cashbox.sale.line'].create({'type_id':'RESUMEN',
                                                              'count':0,
                                                              'amount':ctactereumen,
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'CTACTE',
                                                              'ventas_ids':[]})
            for t in cobros:
                type_orden = '1-'
                for o in orden:
                    if o in t:
                        type_orden='%s' % orden[o]
                self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' % (type_orden,t),
                                                              'count':ccobros[t],
                                                              'amount':cobros[t],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'COBROS',
                                                              'ventas_ids':[(6,0,cids[t])]})
                _logger.info('%s' % {'type_id':t,
                              'count':ccobros[t],
                              'amount':cobros[t],
                              'cashbox_id':self.id,
                              'type_pay_id':'COBROS',
                              'ventas_ids':[(6,0,cids[t])]})
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
            totales = {}
            cantidad = {}
            # Busco las ventas
            if self.closing_date:
                fecha_cierre =  self.closing_date + timedelta(hours=6)
                ventas=self.env['sale.order'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date_order','>=',self.opening_date),('date_order','<=',fecha_cierre)])
            else:
                ventas=self.env['sale.order'].search([('company_id','=',self.company_id.id),('state','!=','cancel'),('date_order','>=',self.opening_date)])
            if ventas:
                ids={}
                for v in ventas:
                    _logger.info('%s %s' % (v.id,v.name))
                    # Unificar Tipo MP como uno solo
                    if v.create_date < self.opening_date:
                        continue
                    type_name = v.type_id.name
                    if 'Mercado Pago' in type_name or 'MP' in type_name:
                        type_name = 'MP'
                    if type_name not in totales:
                        totales[type_name]=0
                        cantidad[type_name]=0
                        ids[type_name]=[]
                    # Si el tipo de venta es Varios, tenemos que revisar el detalle del pago, y separar los montos seugn el diario de pago
                    if 'Varios' in type_name:
                        for pay in v.payment_ids:
                            if pay.state == 'posted':
                                pay_name = pay.journal_id.name
                                if 'Mercado Pago' in pay.journal_id.name:
                                    pay_name = 'MP'
                                totales[pay_name]+=pay.amount_total
                                cantidad[pay_name]+=1
                                ids[pay_name].append(v.id)
                                for line in v.order_line:
                                    if 'DESCUENTO' in line.product_id.name:
                                        _logger.info('DESCUENTO %s %s' % (v.name,line.price_total))
                                        # Hago la proporcion del descuento segun el tipo de pago, y lo agrego al total de descuentos
                                        totales[pay_name]+=(line.price_total * -1) * (pay.amount_total / v.amount_total)
                                        k = '%s %s' % (pay_name,line.product_id.name)
                                        if k not in descuentos:
                                            descuentos[k] = 0
                                            descuentosc[k] = 0
                                        descuentos[k] += line.price_total  * (pay.amount_total / v.amount_total)
                                        descuentosc[k]+=1
                    else:
                        totales[type_name]+=v.amount_total
                        cantidad[type_name]+=1
                        ids[type_name].append(v.id)
                        # Busco descuentos en la orden
                        for line in v.order_line:
                            if 'DESCUENTO' in line.product_id.name:
                                _logger.info('DESCUENTO %s %s' % (v.name,line.price_total))
                                totales[type_name]+=(line.price_total * -1)
                                k = '%s %s' % (type_name,line.product_id.name)
                                if k not in descuentos:
                                    descuentos[k] = 0
                                    descuentosc[k] = 0
                                descuentos[k] += line.price_total 
                                descuentosc[k]+=1

            v = []
            for t in totales:
                type_orden = '1-'
                for o in orden:
                    if o in t:
                        type_orden='%s' % orden[o]
                self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' % (type_orden,t),
                                                              'count':cantidad[t],
                                                              'amount':totales[t],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'VENTAS',
                                                              'ventas_ids': [(6, 0, ids[t])] })
            for k in descuentos:
                type_orden = '1-'
                for o in orden:
                    if o in k:
                        type_orden='%s' % orden[o]
                self.env['account.cashbox.sale.line'].create({'type_id':'%s-%s' % (type_orden,k),
                                                              'count':descuentosc[k],
                                                              'amount':descuentos[k],
                                                              'cashbox_id':self.id,
                                                              'type_pay_id':'DESCUENTOS',
                                                              }
                                                              )

            totales = {}
            cantidad = {}
            # Busco las ventas
            if self.closing_date:
                fecha_cierre =  self.closing_date + timedelta(hours=6)
                ventas=self.env['sale.order'].search([('state','!=','cancel'),('create_date','>=',self.opening_date),('effective_date','=',None),('create_date','<=',fecha_cierre)])
            else:
                ventas=self.env['sale.order'].search([('state','!=','cancel'),('create_date','>=',self.opening_date),('effective_date','=',None)])
            if ventas:
                ids= {}
                for v in ventas:
                    # Verifico que el pedido este facturado o si es de CTACTE, que este enviado a CTACTE, sino no lo tengo en cuenta
                    if v.state == 'sent' and  'CTACTE' not in v.type_id.name:
                        continue
                    if v.state == 'sale' and v.invoice_status != 'invoiced':
                        continue
                    # Unificar Tipo MP como uno solo
                    type_name = v.type_id.name
                    if 'Mercado Pago' in type_name or 'MP' in type_name:
                        type_name = 'MP'
                    if type_name not in totales:
                        totales[type_name]=0
                        cantidad[type_name]=0
                        ids[type_name] = []
                    totales[type_name]+=v.amount_total
                    cantidad[type_name]+=1
                    ids[type_name].append(v.id)
                    _logger.info('%s - %s' % (type_name, v.id))
            v = []

        self.resumen_ids = self.env['account.cashbox.sale.line'].search([('cashbox_id','=',self.id)])

    def autorizo(self,clave=None):
        _logger.info('CLAVE %s' % clave)

        if clave == self.env['ir.config_parameter'].sudo().get_param('autorizacioncaja'):
            self.with_context(autorizo_cierre=True).write({'state': 'closed'})
        else:
            raise UserError('La clave ingresada es incorrecta')

    def action_closing_control(self):
        _logger.warning("=" * 80)
        _logger.warning("[CASHBOX] action_closing_control INICIO")
        _logger.warning("[CASHBOX] self._name = %s | self.id = %s", self._name, self.id)
        _logger.warning("[CASHBOX] cashbox_id = %s", self.cashbox_id)
        _logger.warning("[CASHBOX] cashbox_id._name = %s",
                    self.cashbox_id._name if self.cashbox_id else None)
        _logger.warning("[CASHBOX] cashbox_id.id = %s",
                    self.cashbox_id.id if self.cashbox_id else None)
        # Busco que no queden  ordenes en borrador
        borradores=self.env['sale.order'].search([('caja_id','=',self.id),('state','=','draft')])
        if borradores:
            raise UserError('No se puede continuar, hay ordenes pendientes de confirmar (borrador)')

      
        # 2. Inspeccionar line_ids ANTES de tocar nada
        lines = self.cashbox_id.line_ids
        _logger.warning("[CASHBOX] line_ids._name = %s | cantidad = %s", lines._name, len(lines))

        for line in lines:
            _logger.warning(
                "[CASHBOX][ANTES] line.id=%s | journal='%s' | code='%s' | "
                "balance_start=%s | balance_end=%s | balance_end_real=%s",
                line.id,
                line.journal_id.name,
                line.journal_id.code,
                line.balance_start,
                line.balance_end,
                line.balance_end_real,
            )
    
        # 3. Invalidar caché del compute para leer valores frescos
        _logger.warning("[CASHBOX] Invalidando cache de amount/balance_end...")
        lines.invalidate_recordset(['amount', 'balance_end'])
    
        # 4. Recorrer y copiar
        _logger.warning("[CASHBOX] Recorriendo lineas para copiar balance_end -> balance_end_real")
        for line in lines:
            journal_name = (line.journal_id.name or '').upper()
            journal_code = (line.journal_id.code or '').upper()
            es_mp = (
                'MERCADO PAGO' in journal_name
                or 'MP' in journal_name
                or 'MP' == journal_code
                or 'MERCADOPAGO' in journal_code
            )
            _logger.warning(
                "[CASHBOX] line.id=%s | journal='%s' | es_mp=%s | balance_end=%s",
                line.id, line.journal_id.name, es_mp, line.balance_end,
            )
            if es_mp:
                valor_antes = line.balance_end_real
                line.balance_end_real = line.balance_end
                _logger.warning(
                    "[CASHBOX]   -> ASIGNADO balance_end_real: %s -> %s",
                    valor_antes, line.balance_end_real,
                )
            else:
                _logger.warning("[CASHBOX]   -> SKIP (no es Mercado Pago)")
    
        # 5. Forzar persistencia ANTES de super()
        _logger.warning("[CASHBOX] Flush de balance_end_real...")
        lines.flush_recordset(['balance_end_real'])
    
        # 6. Verificar qué quedó en la DB antes de super()
        self.env.cr.execute("""
            SELECT id, balance_end_real
            FROM account_cashbox_session_line
            WHERE cashbox_session_id = %s
            ORDER BY id
        """, (self.cashbox_id.id,))
        rows = self.env.cr.fetchall()
        _logger.warning("[CASHBOX] ESTADO EN DB (antes de super): %s", rows)
    
        # 7. Llamar al super
        _logger.warning("[CASHBOX] Llamando a super().action_closing_control()...")
        res = super().action_closing_control()
        _logger.warning("[CASHBOX] super() retorno: %s", res)
    
        # 8. Verificar qué quedó en la DB DESPUÉS de super()
        self.env.cr.execute("""
            SELECT id, balance_end_real
            FROM account_cashbox_session_line
            WHERE cashbox_session_id = %s
            ORDER BY id
        """, (self.cashbox_id.id,))
        rows = self.env.cr.fetchall()
        _logger.warning("[CASHBOX] ESTADO EN DB (despues de super): %s", rows)
    
        for line in lines:
            _logger.warning(
                "[CASHBOX][DESPUES] line.id=%s | balance_end_real=%s",
                line.id, line.balance_end_real,
            )
    
        _logger.warning("[CASHBOX] action_closing_control FIN")
        _logger.warning("=" * 80)
        return res

    def action_account_cashbox_session_close_auth(self):
        popup = self.env['paimon.popup.confirmation']
        action = popup.show_aut(self, 'Ingrese la clave de autorizacion', 'autorizo')
        return action

    @api.constrains('state')
    def _create_recibos_central(self):
         if self.state == 'closed':
             self.recibos_central()

    def recibos_central(self):
        for r in self:
            for pay in r.payment_ids:
                if 'Central' in '%s' % pay.journal_id.name or 'Banco' in '%s' % pay.journal_id.name:
                    # Armo un recibo en CENTRAL
                    if 'Efectivo' in pay.journal_id.name:
                        pay_journal = self.env['account.journal'].sudo().search([('name','=','Efectivo'),('company_id','=',5)])
                    if 'PVS' in pay.journal_id.name:
                        pay_journal = self.env['account.journal'].sudo().search([('name','=','PVS'),('company_id','=',5)])
                    if 'Banco' in pay.journal_id.name:
                        pay_journal = self.env['account.journal'].sudo().search([('name','=','Banco'),('company_id','=',5)])
                    _logger.info('JOURNAL %s' % pay_journal)
                    
                    recipe_book = self.env['account.payment.receiptbook'].sudo().search([('name','like','Recibos de Cliente'),('company_id','=',5)])[0]
                    partner_type = 'customer'
                    payment_group = pay.env['account.payment.group'].sudo().create({
                                            'company_id': 5,
                                            'partner_type': partner_type,
                                            'payment_date': pay.date,
                                            'notes': pay.name,
                                            'receiptbook_id':recipe_book.id,
                                            'partner_id': pay.company_id.partner_id.id, })

                    payment_type = 'inbound'
                    payment_methods = pay_journal.inbound_payment_method_line_ids.payment_method_id
                    payment_method = payment_methods.filtered(lambda x: x.code == 'manual')
                    payment_group.partner_type = partner_type
                    payment_group.sudo().payment_ids.create({
                                                      'payment_group_id': payment_group.id,
                                                      'payment_type': payment_type,
                                                      'partner_type': partner_type,
                                                      'company_id': 5,
                                                      'ref': pay.name,
                                                      'partner_id': pay.partner_id.id,
                                                      'amount': abs(pay.amount),
                                                      'journal_id': pay_journal.id,
                                                      'payment_method_id': payment_method.id,
                                                      'date': pay.date,
                                                      })
                    _logger.info('PAYMENT %s' % payment_group)
                    payment_id = payment_group.post()

class CashBoxSaleLine(models.Model):
    _name='account.cashbox.sale.line'
    _order='type_id'
    type_pay_id = fields.Char(string='Tipo')
    type_id = fields.Char(string='Detalle')
    cashbox_id = fields.Integer(string='CashBox')
    count = fields.Integer(string='Cantidad')
    amount = fields.Float(string='Total')
    ventas_ids = fields.One2many('sale.order','cashbox_id','Ordenes de venta')

