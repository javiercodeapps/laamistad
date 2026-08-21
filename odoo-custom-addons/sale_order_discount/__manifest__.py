{
    "name": "Sale Order Discount" ,
    "summary": "Descuento a aplicar en los ventas",
    "author": "Javier Pepe",
    
    "license": "LGPL-3",
    "category": "Sales",
    "version": "15.0.1.0.0",
    "depends": ["sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/sale_order_discount.xml",
        "views/sale_order_discount2.xml",
    ],
    "installable": True,
    "application": True,
}
