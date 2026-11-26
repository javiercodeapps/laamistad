{
    "name": "BlackLabs - Estado de servicio ARCA",
    "summary": "Monitoreo de ARCA con degradacion controlada para facturacion electronica",
    "description": "Indicador de estado de servicio de ARCA para facturacion electronica. Requiere l10n_ar_afipws_fe (adhoc) y se instala con stop/upgrade/start para asegurar que los assets y la carga de Python queden consistentes.",
    "version": "16.0.1.1.0",
    "author": "Ernesto Bernis - BlackLabs",
    "website": "https://github.com/Blacks-Lab",
    "license": "LGPL-3",
    "category": "Accounting/Localizations/EDI",
    "depends": ["l10n_ar_afipws_fe", "bus", "web"],
    "data": [
        "security/bl_afip_status_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/bl_afip_status_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "bl_afip_status/static/src/systray/bl_afip_systray.scss",
            "bl_afip_status/static/src/systray/bl_afip_systray.js",
            "bl_afip_status/static/src/systray/bl_afip_systray.xml",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
}
