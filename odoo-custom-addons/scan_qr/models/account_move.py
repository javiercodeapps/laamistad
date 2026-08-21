import logging
from odoo import models

_logger = logging.getLogger(__name__)

class AccountMove(models.Model):
    _inherit = "account.move"

    def action_post(self):
        # Confirm the invoice
        res = super().action_post()
        for move in self:
            # Check if the invoice is an "out_invoice" or "out_refund" (customer invoices & refunds)
            if move.move_type in ["out_invoice", "out_refund"]:
                # Ensure the invoice was NOT manually created (i.e., it was created by another process)
                if not move.env.context.get('manual_creation', False):
                    _logger.info('printed')  # This logs 'printed' when report is generated
                    return move.env['ir.actions.report'].search(
                        [('report_name', '=', 'account.report_invoice')], limit=1
                    ).report_action(move)

            return res

###

#    def print_invoice(self):
#        # Check if the invoice is an "out_invoice" or "out_refund" (customer invoices & refunds)
#        if self.move_type in ["out_invoice", "out_refund"]:
#            # Ensure the invoice was NOT manually created (i.e., it was created by another process)
#            if not self.env.context.get('manual_creation', False):
#                return self.env['ir.actions.report'].search(
#                    [('report_name', '=', 'account.report_invoice')], limit=1
#                ).report_action(self)
