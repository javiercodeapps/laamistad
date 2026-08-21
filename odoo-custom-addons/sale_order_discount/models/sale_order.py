from odoo import models, fields, api
from datetime import datetime, timedelta,date
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)
class SaleOrder(models.Model):
    _inherit = "sale.order"
    sale_discount = fields.Float(
        "Descuento",
       #compute="compute_discount",
        store=True,
    )
    sale_discount_percent = fields.Float(
        "Descuento Porcentaje",
        #compute="compute_discount",
        store=True,
    )
    sale_with_discount = fields.Float(
        "Total con Descuento",
        compute="compute_discount",
        store=True,
    )
    sale_discounts = fields.Many2many('sale.order.discount',string='Descuentos Activos')


    def copy(self, default=None):
        new_order = super().copy(default=default)

        sale_efectivo = self.env["sale.order.type"].search([("name", "ilike", 'Efectivo'),("company_id","=",self.company_id.id)], limit=1)
        new_order.type_id = sale_efectivo.id

        # Itera sobre las líneas de la nueva orden
        for line in new_order.order_line:
            # Ejemplo: Si el producto es X o Y, elimina la línea
            try:
                if line.product_id.name[:9] == 'DESCUENTO':
                    line.unlink() # o line.write({'active': False})
                if line.product_id.name == 'REDONDEO':
                    line.unlink() # o line.write({'active': False})
            except:
                continue
        return new_order

    @api.depends('order_line.price_subtotal', 'order_line.price_tax', 'order_line.price_total')
    def compute_discount(self):
        descuentos = {}
        for order in self:
            if order.state in ['draft','sent'] and not order.is_admin: # and order.efectivo == 0:
                total = order.amount_total
                # Buscamos los descuentos activos
               # discounts = self.env["sale.order.discount"].search([("active", "=", True)],order="monto asc")    
                discounts=self.env["sale.order.discount"].search([("active", "=", True),('company_id','=',self.company_id.id)],order="monto asc")
                _logger.info('DESCUENTO %s %s ' % (discounts,order.type_id))
                # Calculamos el monto del descuento
                discount_amount = 0
                order_type = order.type_id
                if order.type_id.name == 'CTACTE':
                    sale_efectivo = self.env["sale.order.type"].search([("name", "ilike", 'Efectivo'),("company_id","=",self.company_id.id)], limit=1)
                    order_type = sale_efectivo
                for discount in discounts:
                    if not discount.sale_order_type:
                        continue
                    activo = True
                    if discount.dia:
                        activo = False
                        for day in discount.dia:
                            today = fields.Date.context_today(self)
                            today = datetime.now() - timedelta(hours=6)
                            if today.weekday()  == day.day:
                                activo = True
                    if activo and total > discount.monto:
                        descuentos[discount.sale_order_type.id] = discount.id
                    _logger.info('CALCULAR DESCUENTO %s ' %  descuentos.values())

                    activo = False
                    if discount.sale_order_type and  discount.sale_order_type.id == order_type.id:
                        activo = True
                        if discount.dia:
                            activo = False
                            for day in discount.dia:
                                today = fields.Date.context_today(self)
                                if today.weekday()  == day.day:
                                    activo = True
                    if activo:
                        _logger.info('DESCUENTO %s %s ' % (discount.sale_order_type.name,discount.dia) )
                        for line in self.order_line:
                            if line.product_id.id == discount.product_id.id:
                                line.write({"price_unit":0})
                        if total > discount.monto:
                            order.sale_discount = total * discount.discount / 100
                            order.sale_with_discount = total - order.sale_discount
                            order.sale_discount_percent = discount.discount
                            for line in self.order_line:
                                if line.product_id.id == discount.product_id.id:
                                    line.write({"price_unit":-order.sale_discount})
                            _logger.info('CALCULAR DESCUENTO %s ' %  total)
                _logger.info('CALCULAR DESCUENTO %s ' %  descuentos.values())
                order.write({'sale_discounts':list(descuentos.values())})

    @api.onchange('sale_discount_percent')
    def compute_discount_manual(self):
        _logger.info('Descuento manual')
        for order in self:
            if order.state in ['draft','sent']:# and order.efectivo == 0:
                total = order.amount_total
                order.sale_discount = total * order.sale_discount_percent / 100
                order.sale_with_discount = total - order.sale_discount

    def apply_discount(self):
        # Leemos de la orden el monto total y el tipo de orden
        for order in self:
            if not self.is_admin:
                recalcular = True
               #if order.type_id not in self.sale_discounts:
               #    recalcular = False
               #    order.sale_discount = 0
               #    order.sale_with_discount = 0
               #    order.sale_discount_percent = 0
                if order.sale_discount == 0:
                    recalcular = False
                    if order.create_date.date() == datetime.now().date():
                        order.compute_discount()
                if recalcular:
                    order.compute_discount()
            if order.sale_discount == 0:
                continue
            _logger.info('APLICAR DESCUENTO %s %s' % (order.amount_due,order.type_id) )
            order_type = order.type_id
            # Buscamos los descuentos activos
            #discounts = self.env["sale.order.discount"].search([("active", "=", True)],order="monto asc")    
            discounts=self.env["sale.order.discount"].search([("sale_order_type", "=", order_type.id), ("active", "=", True),('company_id','=',self.company_id.id)],order="monto asc")
            dd=[]
            prds=[]
            # Calculamos el monto del descuento
            for discount in discounts:
                _logger.info('DESCUENTO %s %s' % ( discount.dia,self.date_order.weekday()))
                prds.append(discount.product_id)
                activo=False
                if discount.sale_order_type.id == order_type.id:
                    activo = True
                    if discount.dia:
                        activo = False
                    for day in discount.dia:
                        today = datetime.now() - timedelta(hours=6)
                        if today.weekday() == day.day:
                            activo = True
                if activo and order.amount_due >  discount.monto:
                    dd.append(discount)
                    product = discount.product_id
            if self.is_admin:
                discounts = self.env["sale.order.discount"].search([("active", "=", True),('name','=','Descuento Empleado'),('discount','=',self.sale_discount_percent),('company_id','=',self.company_id.id)],order="monto asc")    
                if not discounts:
                    discounts = self.env["sale.order.discount"].search([("active", "=", True),('name','=','Descuento Especial')],order="monto asc")    
                dd=[]
                # Calculamos el monto del descuento
                for discount in discounts:
                    dd.append(discount)
                    product = discount.product_id
            # pongo en 0 todos los descuentos
            for p in prds:
                for line in self.order_line:
                    if line.product_id.id == p.id:
                        line.write({"price_unit":0,"product_uom_qty":0})
            
            total = 0
            if len(dd) > 0:
                # Reviso si esta el codigo en la orden y separo proporcionalmente los montos por diretente iva
                taxes ={}
                for line in self.order_line:
                    if line.product_id.id == product.id:
                        #line.write({"price_unit":order.sale_discount * -1})
                        line.unlink()
                    else:
                        if line.tax_id.id not in taxes:
                            taxes[line.tax_id.id] = 0
                        taxes[line.tax_id.id] += line.price_total
                        total += line.price_total

                # Agregamos el codigo de descuento a la orden
                descuento = 0
                for tax in taxes:
                    if descuento == 0:
                        descuento = order.sale_discount * (taxes[tax] / total)
                    else:
                        descuento = order.sale_discount - descuento
                    sale_order_line = self.env["sale.order.line"].create({
                        "order_id": order.id,
                        "product_id": product.id,
                        "name": '%s %d %%' % (product.name , self.sale_discount_percent) ,
                        "product_uom_qty": 1,
                        "tax_id": [tax],
                        "price_unit": -descuento,
                    })
                    _logger.info('DESCUENTO %s ' %  order.sale_discount)
            else:
                order.sale_discount = 0
                order.sale_with_discount = 0
                order.sale_discount_percent = 0
        return True

    def apply_redondeo(self):
        # Leemos de la orden el monto total y el tipo de orden
        for order in self:
            _logger.info('DESCUENTO REDONDEO %s ' % order.redondeo)
            if order.redondeo != 0:
                product = self.env['product.product'].search([('default_code','=','REDONDEO')], limit=1)
                sale_order_line = self.env["sale.order.line"].create({
                        "order_id": order.id,
                        "product_id": product.id,
                        "name": product.name,
                        "product_uom_qty": 1,
                        "price_unit": -order.redondeo,
                    })
                _logger.info('DESCUENTO REDONDEO %s ' %  order.redondeo)
        return True
   #def action_confirm(self):
   #   #if self.state in ['draft','sent']:
   #   #    self.apply_redondeo()
   #   #    self.apply_discount()
   #   #    self.env.cr.commit()
   #    res = super().action_confirm()
   #    return res
