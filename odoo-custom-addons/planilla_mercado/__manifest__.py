{
    "name": "Planilla Camion" ,
    "summary": "Create Purchase/Sale  Orders by reading xlsx.",
    "author": "Javier Pepe",
    
    "license": "LGPL-3",
    "category": "Sales",
    "version": "15.0.1.0.0",
    "depends": ["sale","purchase"],
    "data": [
        "security/ir.model.access.csv",
        "views/import_wizard_view.xml",
        "views/purchase.xml",
    ],
    "installable": True,
    "application": True,
}
