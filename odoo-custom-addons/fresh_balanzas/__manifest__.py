{
    'name': 'Fresh Balanzas',
    'version': '16.0.1.0.0',
    'category': 'Sales',
    'summary': 'Conector de balanzas comerciales vía TCP/IP',
    'description': """
        Módulo para conectar Odoo con balanzas comerciales.
        - Soporte multi-marca (Kretz, Systel, etc.)
        - Sincronización de productos (PLU) y vendedores
        - Comunicación TCP/IP directa
        - Logs de sincronización por balanza
    """,
    'author': 'Custom Development',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/balanza_scale_views.xml',
        'views/balanza_sync_wizard_views.xml',
        'views/balanza_verify_wizard_views.xml',
        'views/balanza_sync_log_views.xml',
        'views/res_partner_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
