{
    'name': 'Custom Account Payment Report',
    'version': '1.0',
    'category': 'Accounting/Reporting',
    'summary': 'Reporte personalizado de Pagos (account.payment)',
    'description': """
        Este módulo agrega un reporte PDF personalizado para los pagos (account.payment).
        Incluye:
        - Nombre de la empresa
        - Fecha
        - Proveedor
        - Memo
        - Importe
    """,
    'depends': ['account'],
    'data': [
        'report/payment_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
