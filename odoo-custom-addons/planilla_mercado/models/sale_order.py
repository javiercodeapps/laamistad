from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger(__name__)
class SaleOrder(models.Model):
    _inherit = "sale.order"

    def create_order_dic(self, venta, sucursal,compania,ref):
        _logger.info('Creating Sale Order from dictionary %s %s' % (venta, sucursal))
        order_lines= []
        for c in venta:
            _logger.info('Creating Sale Order from dictionary %s %s %s %s' % (c,sucursal,compania, ref))
            product_ref = c['codigo']
            cantidad = c['cantidad']
            precio = c['venta']
            product_obj = self.env["product.product"].search([("default_code", "=", product_ref)], limit=1)
            if not product_obj:
                raise UserError('El codigo no existe %s' % product_ref)
            uom = product_obj.uom_id  # Default unit of measure
            type_id = self.env['sale.order.type'].search([('name', '=', 'Venta Mayorista')], limit=1)
            order_lines.append({
                            "product_id": product_obj.id,
                            "name": product_obj.name,
                            "product_uom_qty": cantidad,  # Weight is used directly
                            "qty_delivered": cantidad,  # Weight is used directly
                            "product_uom": uom.id,
                            "price_unit": precio,
                        })
        
        order = self.create({
            "partner_id": sucursal.id,
            "company_id": compania.id,
            "origin": ref,
            "type_id": type_id.id,
            "order_line": [(0, 0, line) for line in order_lines],
        })
       #order.action_confirm()
        return order.id
    def actualizar_precios(self):
        # Preparo lista de precios con los productos de la orden actual
        precios = {}
        for line in self.order_line:
            precios[line.product_template_id] = line.price_unit

        # Busco todas las ordnes con el mismo documento de origen
        for so in self.env['sale.order'].search([('origin','=',self.origin)]):
            # Controlo los precios y los cambios si hace falta
            for line in so.order_line:
                if line.product_template_id in precios and precios[line.product_template_id] != line.price_unit:
                    line.price_unit = precios[line.product_template_id] 

        # Busco todas las ordnes con el mismo documento de origen
        #partner_id = self.env['res.partner'].search([('ref','=','LAAMISTAD')])
        #for po in self.env['purchase.order'].search([('origin','=',self.origin),('partner_id','=',partner_id.id)]):
        for po in self.env['purchase.order'].search([('origin','=',self.origin)]):
            # Controlo los precios y los cambios si hace falta
            for line in po.order_line:
                if line.product_template_id in precios and precios[line.product_template_id] != line.price_unit:
                    line.price_unit = precios[line.product_template_id] 


