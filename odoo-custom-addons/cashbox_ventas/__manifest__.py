{
    "name": "Cashbox Ventas" ,
    "summary": "Registo de ventas",
    "author": "Javier Pepe",
    
    "license": "LGPL-3",
    "category": "Sales",
    "version": "15.0.1.0.0",
    "depends": ["sale","account","account_cashbox","web_widget_mpld3_chart"], 
    "data": [
        "security/ir.model.access.csv",
        "views/cashbox_session.xml",
        "views/cashbox_session_resumen.xml",
        "views/cashbox_session_menu.xml",
        "report/templates.xml",
    ],
    "installable": True,
    "application": True,
}
