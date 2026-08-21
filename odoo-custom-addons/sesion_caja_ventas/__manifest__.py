{
    "name": "Sesión de Caja para Ventas",
    "version": "16.0.1.0.0",
    "summary": "Gestión de sesiones de caja para ventas en efectivo y otros medios",
    "description": "Módulo para controlar sesiones de caja relacionadas con órdenes de venta.",
    "author": "KleinerZuloaga",
    "website": "https://kleinerzuloaga.net.ar",
    "category": "Sales",
    "depends": ["base", "sale_management", "account"],
    "data": [
        "security/ir.model.access.csv",
        "views/sesion_caja_views.xml",
        "views/sesion_caja_menu.xml",
        "wizard/cerrar_sesion_wizard.xml",
        "data/sesion_caja_sequence.xml"
    ],
    "installable": True,
    "application": True,
    "license": "LGPL-3"
}
