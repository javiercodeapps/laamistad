from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import openpyxl
from io import BytesIO
from base64 import b64decode
import logging
_logger = logging.getLogger(__name__)

class PurchaseOrder(models.Model):
    _inherit = "purchase.order"
    partner_ref = fields.Char(string='Referencia' ,compute='get_bultos')

    def get_bultos(self):
        for rec in self:
            if rec.partner_id:
                rec.partner_ref = '%s' % (rec.partner_id.ref)

    @api.model
    def create_order_from_xls(self,file_xls,file_xls_name):

        wb = openpyxl.load_workbook(filename=BytesIO(b64decode(file_xls)),data_only=True)

        sheet = wb['GENERAL']
        compra = {}
        sucursales = {}
        proveedor = {}
        so_id = 0
        for r in sheet.rows:
           if (isinstance(r[1].value,int) or isinstance(r[1].value,float) ) and  r[1].value > 0:
               print(r[0].value,r[1].value)
               proveedor[r[3].value]=r[3].value
               clave='%s-%s-%s' % (r[0].value,r[3].value,r[9].value)
               compra[clave] = {}
               compra[clave]['codigo']=r[0].value
               compra[clave]['proveedor']=r[3].value
               compra[clave]['cantidad']=r[1].value
               for suc in sucursales:
                   if r[suc].value and r[suc].value > 0:
                       compra[clave][sucursales[suc]]=r[suc].value
        
               if  r[6].value == 'x':
                   compra[clave]['senia'] = compra[clave]['cantidad']
               else:
                   compra[clave]['senia'] = 0
               compra[clave]['senia_precio'] = r[8].value
               compra[clave]['compra'] = r[9].value
               compra[clave]['venta'] = r[10].value
           else:
               if r[1].value == 'CANT':
                   ref = r[2].value
                   for col in range(11,26):
                       if 'VENTA' not in r[col].value:
                           sucursales[col] = r[col].value
        ref = '%s %s' % (ref,self.env['ir.sequence'].next_by_code('MERCADO') )
        # Preparo compra por proveedor
        for prv in proveedor:
            print("Proveedor %s" % prv)
            prv_obj = self.env['res.partner'].search([('ref','=',prv.upper().strip())])
            senia = 0
            compra_prv=[]
            cajones = {}
            for c in compra:
                if compra[c]['proveedor'] == prv:
                   compra_prv.append(compra[c])
                   # Sumo cajones
                   if compra[c]['senia'] > 0:
                       if compra[c]['senia_precio'] not in cajones:
                           cajones[compra[c]['senia_precio']] = 0
                       cajones[compra[c]['senia_precio']] += compra[c]['senia']
            for cajon in cajones:
                c = {'codigo':'CAJON%s' % cajon,'cantidad':cajones[cajon],'compra': cajon}
                compra_prv.append(c)
            compania = self.env['res.company'].search([('code','=','LAAMISTAD')])
            if not prv_obj:
                raise UserError('El proveedor no esta creado %s' % prv.upper())
            so_id = self.create_order_dic(compra_prv,prv_obj,compania,False,ref)
        # Preparo venta sucursales
        for ss in sucursales:
            s=sucursales[ss]
            _logger.info('Sucursal %s ' % s)
            venta = {}
            senia = 0
            for c in compra:
                if  s in compra[c]:
                    # Agrupo los las ventas por codigo-precio
                    clave='%s-%s' % (compra[c]['codigo'],compra[c]['venta'])
                    if clave not in venta:
                        venta[clave] ={}
                        venta[clave]['codigo']= compra[c]['codigo']
                        venta[clave]['venta'] = compra[c]['venta']
                        venta[clave]['cantidad'] = 0
                    venta[clave]['cantidad'] += compra[c][s]
                    if compra[c]['senia'] > 0:
                        senia+=compra[c][s]
            venta_suc = []
            _logger.info(venta)
            cajon = 0
            # Separar cajon por precio en diferentes codigos, a la sucursal 1 solo codigo
            for v in venta:
                venta_suc.append(venta[v])
           #    cajon += venta[v]['cantidad']
            if len(venta_suc) == 0:
                continue
            cajon = {'codigo':'CAJON','cantidad':senia,'venta': 4000,'compra':0}
            venta_suc.append(cajon)
            sucursal = self.env['res.partner'].search([('ref','=',s)])
            compania = self.env['res.company'].search([('code','=','LAAMISTAD')])
            if not sucursal:
                raise UserError('El proveedor no esta creado %s' % s)
            _logger.info('SUCURSAL %s %s' % (sucursal,s))
            sale_obj = self.env["sale.order"].create_order_dic(venta_suc,sucursal,compania,ref)
            compania = self.env['res.company'].search([('code','=',s)])
            partner_id = self.env['res.partner'].search([('ref','=','LAAMISTAD')])
            if not partner_id:
                raise UserError('El proveedor no esta creado %s' % 'LAAMISTAD')
            if not compania:
                raise UserError('La compania no esta creado %s' % s)
            purchase_id = self.env["purchase.order"].create_order_dic(venta_suc,partner_id,compania,True,ref)
        return so_id

    def create_order_dic(self, compra, partner_id, compania, venta=False, ref=False):
        order_lines= []
        _logger.info("Creando orden de compra %s %s" % (compra, compania) )
        for c in compra:
            # Busco producto
            product_ref = c['codigo']
            cantidad = c['cantidad']
            precio = c['venta'] if venta else c['compra']
            product_obj = self.env["product.product"].search([("default_code", "=", product_ref)], limit=1)
            uom = product_obj.uom_id  # Default unit of measure
            if product_obj:
                order_lines.append({
                            "product_id": product_obj.id,
                            "name": product_obj.name,
                            "product_qty": cantidad,  # Weight is used directly
                            "qty_received": cantidad,  # Weight is used directly
                            "product_uom": uom.id,
                            "price_unit": precio,
                        })
            else:
                raise UserError('Producto no encontrado %s ' % product_ref)
        _logger.info('COMPRAS %s %s' % (order_lines,venta))
        order = self.create({
                "partner_id": partner_id.id,
                "company_id": compania.id,
                "origin": ref,
                "order_line": [(0, 0, line) for line in order_lines],
            })
      # order.button_confirm()
        # Busco recepcion y las confirmo
      # for picking in order.picking_ids:
      #     picking.action_set_quantities_to_reservation()
      #     picking.button_validate()
      # order.action_create_invoice()
        return order.id
