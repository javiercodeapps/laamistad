{
    'name': 'AFIP/ARCA WebService Monitor',
    'version': '16.0.1.0.0',
    'category': 'Accounting/Localizations',
    'summary': 'Monitor AFIP/ARCA WebService availability and block invoice confirmation when service is down (or hand over to CAEA contingency)',
    # Sin título con subrayado (===): docutils lo interpreta como título de
    # sección DENTRO de un blockquote (la cadena va indentada) y la
    # instalación del módulo revienta con "Unexpected section title".
    'description': """AFIP/ARCA WebService Monitor
* Monitors AFIP/ARCA electronic invoicing web service availability
* Displays a warning banner when service is down
* Blocks invoice confirmation for Argentinian POS journals when service is unavailable
* Automatic periodic checks
* Manual refresh option
""",
    'author': 'Trixocom',
    'website': 'https://trixocom.com',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'l10n_ar',
    ],
    'external_dependencies': {
        'python': ['requests', 'zeep'],
    },
    'data': [
        'security/ir.model.access.csv',
        'views/afip_service_status_views.xml',
        ##'views/account_move_views.xml',
        'views/res_config_settings_views.xml',
        'data/ir_cron_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'afip_webservice_monitor/static/src/js/afip_status_banner.js',
            'afip_webservice_monitor/static/src/xml/afip_status_banner.xml',
            'afip_webservice_monitor/static/src/css/afip_status_banner.css',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
