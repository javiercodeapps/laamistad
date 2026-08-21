from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError, ValidationError
import logging
_logger = logging.getLogger(__name__)

class CajaControl(models.TransientModel):
    _name = "caja.pagos.control"
    _description = "Control Caja"
    caja = fields.Many2one('account.cashbox.session')
    monto = fields.Float(string='Monto')
    
    @api.model
    def default_get(self, fields):
        caja = self.env['account.cashbox.session'].search([('state','=','opened')])
        if not caja:
            raise UserError('No se encontro ninguna caja abierta')
        result = super().default_get(fields)
        result.update({'caja': caja[0].id })
        return result

    
    def control(self):
        max_diff_in_currency = self.caja.cashbox_id.max_diff
        for line in self.caja.line_ids:
            if 'Efectivo' in line.journal_id.name:
                payments = self.env['account.payment'].search([ ('journal_id', '=', line.journal_id.id),
                                                                ('create_date', '>', self.caja.opening_date),
                                                                ('state', '=', 'posted'),
                                                                ('cashbox_session_id', '=', False),
                                                                ])
                payments.cashbox_session_id = self.caja
                balance_end = line.balance_end
                _logger.info('%s %s' % (balance_end,line.balance_start) )
                diff = abs(balance_end - self.monto)
                diff_ss = balance_end - self.monto
                if diff > max_diff_in_currency:
                    raise ValidationError(
                                       'En el diario "%s" el Balance Final Real (%s) excede la máxima diferencia permitida (%s).' % (
                                       line.journal_id.name,
                                       self.monto,
                                       max_diff_in_currency,
                                       ))
                else:
                    raise ValidationError("La caja esta correcta")

