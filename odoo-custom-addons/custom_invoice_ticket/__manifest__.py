{
    'name': 'Custom Invoice Ticket 80mm',
    'version': '16.0.1.0.0',
    'category': 'Accounting/Reporting',
    'summary': 'Invoice report in 80mm thermal ticket format',
    'description': """
        This module adds a custom report for invoices formatted as 80mm tickets.
        It includes:
        - Company Logo
        - Fiscal Data
        - ARCA/AFIP QR Code support
    """,
    'depends': ['account', 'l10n_ar'],
    'data': [
        'data/paperformat.xml',
        'reports/report_actions.xml',
        'reports/report_invoice_ticket.xml',
        'reports/report_invoice_ticket_b.xml',
        'reports/report_sale_order_ticket_b.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
