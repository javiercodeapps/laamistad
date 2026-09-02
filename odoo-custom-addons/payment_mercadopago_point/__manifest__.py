# -*- coding: utf-8 -*-
{
    'name': "payment_mercadopago_point",

    'summary': """
        Integracion MercadoPago SmartPoint""",

    'description': """
        Integracion MercadoPago SmartPoint""",

    'author': "Fresherp",
    'website': "https://www.fresherp.com",

    'category': 'Uncategorized',
    'version': '0.1',

    'depends': ['base','mail'],

    'data': [
        'security/ir.model.access.csv',
        'views/mercadopago_point.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'payment_mercadopago_point/static/src/js/notification_receiver.js',
        ],
    },
    'demo': [
    ],
}
