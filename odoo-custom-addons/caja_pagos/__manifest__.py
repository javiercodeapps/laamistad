{
    "name": "Caja Pagos" ,
    "summary": "Pagos y transferencias automaticas",
    "author": "Javier Pepe",
    
    "license": "LGPL-3",
    "category": "Sales",
    "version": "15.0.1.1.0",
    # custom_account_payment_report aporta los reportes que usa imprimir()
    # (action_report_payment_group_custom / action_report_payment_custom).
    "depends": ["base","sale","account","account_payment_group","scan_qr","custom_account_payment_report"],
    "data": [
        "security/ir.model.access.csv",
        "views/control_caja.xml",
        "views/caja_pagos.xml",
    ],
    "installable": True,
    "application": True,
}
