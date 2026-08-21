from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import openpyxl
from io import BytesIO
from base64 import b64decode
import logging
_logger = logging.getLogger(__name__)

class SaleOrderDiscount(models.Model):
    _name = "sale.order.discount"
    name = fields.Char(string="Name")
    sale_order_type = fields.Many2one("sale.order.type", string="Sale Order Type")
    discount = fields.Float(string="Discount")
    product_id = fields.Many2one("product.product", string="Producto")
    monto = fields.Float(string="Monto")
    active = fields.Boolean(string="Activo", default=True)
    company_id = fields.Many2one('res.company', 'Company')
    dia = fields.Many2many('sale.order.discount.weekdays', string="Dia")

class WeekDays(models.Model):
     _name = 'sale.order.discount.weekdays'

     day = fields.Integer("Dia numero")
     name = fields.Char("Nombre")

