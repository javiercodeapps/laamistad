{
    "name": "QR Sale Order",
    "summary": "Create Sale Orders by scanning a QR Code.",
    "author": "KleinerZuloaga",
    "website": "https://kleinerzuloaga.net.ar",
    "license": "LGPL-3",
    "category": "Sales",
    "version": "16.0.1.0.0",
    "depends": ["sale","payment_status_in_sale"],
    "data": [
        "security/ir.model.access.csv",
        "views/scan_qr_wizard_views.xml",
        "views/custom_popup_confirmation.xml",
        "views/sale_order_views.xml",
    # Para prueba de reportes:
    'views/sale_order_invoice_report.xml',
    'views/report.xml'
    #
    ],
    "installable": True,
    "application": True,
}
