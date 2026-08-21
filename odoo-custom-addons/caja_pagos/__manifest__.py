{
    "name": "Caja Pagos" ,
    "summary": "Pagos y transferencias automaticas",
    "author": "Javier Pepe",
    
    "license": "LGPL-3",
    "category": "Sales",
    "version": "15.0.1.0.0",
    "depends": ["base","sale","account"],
    "data": [
        "security/ir.model.access.csv",
        "views/control_caja.xml",
        "views/caja_pagos.xml",
    ],
    "installable": True,
    "application": True,
}
