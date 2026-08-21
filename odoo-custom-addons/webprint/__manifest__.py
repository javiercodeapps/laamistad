# -*- coding: utf-8 -*-
{
    'name': "webapp-hardware-bridgent from Desktop",
    'summary': """webapp-hardware-bridge.""",
    'version': '1.1.0',
    'author': "Javier Pepe",
    'images': ['static/description/main_screenshot.png'],
    'license': "OPL-1",
    'category': 'Printer',
    'price': 0,
    'currency': 'EUR',
    'depends': ['base', 'web'],
    'data': [
        'views/views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'webprint/static/src/network/*',
#           'webprint/static/src/components/systray.*',
        ],
    },
    'application': True,
}
