from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from unittest.mock import patch


class TestAfipMonitor(TransactionCase):
    
    def setUp(self):
        super(TestAfipMonitor, self).setUp()
        
        # Create AFIP service status records
        self.afip_service = self.env['afip.service.status'].create({
            'name': 'Test WSFE Service',
            'service_type': 'wsfe',
            'environment': 'testing',
            'url': 'https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL',
            'is_available': True,
        })
        
        # Create Argentinian journal with POS
        self.ar_journal = self.env['account.journal'].create({
            'name': 'Test AR POS Journal',
            'type': 'sale',
            'code': 'TARPOS',
            'l10n_ar_is_pos': True,
        })
        
        # Create regular journal without POS
        self.regular_journal = self.env['account.journal'].create({
            'name': 'Test Regular Journal',
            'type': 'sale',
            'code': 'TREG',
        })
        
        # Create partner
        self.partner = self.env['res.partner'].create({
            'name': 'Test Customer',
        })
        
        # Create product
        self.product = self.env['res.product'].create({
            'name': 'Test Product',
            'list_price': 100.0,
        })

    def test_service_status_check(self):
        """Test service status check functionality"""
        result = self.afip_service.check_service_status()
        self.assertIn('available', result)
        self.assertIn('status_code', result)
        self.assertIn('response_time', result)

    def test_requires_afip_check_with_ar_journal(self):
        """Test that invoices with AR POS journal require AFIP check"""
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.ar_journal.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100.0,
            })],
        })
        
        self.assertTrue(invoice.requires_afip_check)

    def test_requires_afip_check_without_ar_journal(self):
        """Test that invoices without AR POS journal don't require AFIP check"""
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.regular_journal.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100.0,
            })],
        })
        
        self.assertFalse(invoice.requires_afip_check)

    def test_invoice_confirmation_blocked_when_service_down(self):
        """Test that invoice confirmation is blocked when AFIP service is down"""
        # Set service as unavailable
        self.afip_service.write({'is_available': False})
        
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.ar_journal.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100.0,
            })],
        })
        
        with self.assertRaises(UserError) as context:
            invoice.action_post()
        
        self.assertIn('AFIP', str(context.exception))

    def test_invoice_confirmation_allowed_when_service_up(self):
        """Test that invoice confirmation works when AFIP service is available"""
        # Set service as available
        self.afip_service.write({'is_available': True})
        
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.ar_journal.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100.0,
            })],
        })
        
        # Should not raise error
        try:
            invoice.action_post()
            success = True
        except UserError:
            success = False
        
        self.assertTrue(success or invoice.state == 'posted')

    def test_invoice_confirmation_allowed_for_non_ar_journals(self):
        """Test that non-AR journals can confirm regardless of AFIP status"""
        # Set service as unavailable
        self.afip_service.write({'is_available': False})
        
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.partner.id,
            'journal_id': self.regular_journal.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100.0,
            })],
        })
        
        # Should not raise error even with service down
        try:
            invoice.action_post()
            success = True
        except UserError:
            success = False
        
        self.assertTrue(success)

    def test_initialize_services(self):
        """Test service initialization"""
        # Delete existing services
        self.env['afip.service.status'].search([]).unlink()
        
        # Initialize services
        self.env['afip.service.status'].initialize_services()
        
        # Check that services were created
        services = self.env['afip.service.status'].search([])
        self.assertTrue(len(services) >= 2)  # At least WSFE and WSAA

    def test_is_afip_available(self):
        """Test is_afip_available method"""
        self.afip_service.write({'is_available': True})
        available = self.env['afip.service.status'].is_afip_available('wsfe')
        self.assertTrue(available)
        
        self.afip_service.write({'is_available': False})
        available = self.env['afip.service.status'].is_afip_available('wsfe')
        self.assertFalse(available)

    def test_get_status_info(self):
        """Test get_status_info method"""
        status_info = self.env['afip.service.status'].get_status_info()
        
        self.assertIn('wsfe', status_info)
        self.assertIn('wsaa', status_info)
        self.assertIn('all_available', status_info)

    def test_consecutive_failures_counter(self):
        """Test that consecutive failures are counted"""
        initial_failures = self.afip_service.consecutive_failures
        
        # Simulate failure
        self.afip_service.write({
            'is_available': False,
            'consecutive_failures': initial_failures + 1,
        })
        
        self.assertEqual(self.afip_service.consecutive_failures, initial_failures + 1)
        
        # Simulate success
        self.afip_service.write({
            'is_available': True,
            'consecutive_failures': 0,
        })
        
        self.assertEqual(self.afip_service.consecutive_failures, 0)
