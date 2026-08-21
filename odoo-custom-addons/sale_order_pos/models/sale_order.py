from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError, ValidationError
import logging
_logger = logging.getLogger(__name__)

class SaleOrderQR(models.Model):
    _inherit = "sale.order"
    # Agrego campos para que carguen el efecto y calcular el vuelto
    efectivo = fields.Monetary(string='Efectivo',copy=False)
    vuelto = fields.Monetary(string='Vuelto',copy=False)
    redondeo = fields.Monetary(string='Redondeo',copy=False)
    total_calculado = fields.Monetary(string='Total',copy=False)
    is_admin = fields.Boolean(default=False, compute='check_group', store=True,tracking=True)

    
    def _action_cancel(self):
        for record in self:
            if self.state == 'draft':
                self.state = 'cancel'
                return True
            if not record.is_admin:
                raise UserError('El pedido solo puede ser cancelado por el encargado')
            # Busco facturas
            _logger.info('Rever %s ' % self.invoice_ids)
            for invoice in self.invoice_ids:
                for payment in invoice.payment_group_ids:
                    payment.action_draft()
                    payment.cancel()
            if self.invoice_ids:
                self.create_reverse(self.invoice_ids)
            return self.write({'state': 'cancel'})
        return True

    def create_reverse(self,move):
        move_reversal = self.env['account.move.reversal']\
            .with_context(active_model='account.move', active_ids=move.ids)\
            .create({'reason': 'no reason',
                     'refund_method': 'cancel',
                     'journal_id': move.journal_id.id,
                     })
        reversal = move_reversal.reverse_moves()
        reverse_move = self.env['account.move'].browse(reversal['res_id'])
        try:
            reverse_move.action_post()
            (move + reverse_move).line_ids\
                   .filtered(lambda line: line.account_type in ('asset_receivable', 'liability_payable'))\
                   .reconcile()
        except:
            return True


    def check_group(self):
        if self.user_has_groups('account_cashbox.cashbox_view_access'):
            self.is_admin = True
        else:
            self.is_admin = False

    def set_admin(self):
        if self.is_admin:
            self.is_admin = False
        else:
            self.is_admin = True

    def autorizo(self,clave=None):
        _logger.info('CLAVE %s' % clave)

        if clave == self.env['ir.config_parameter'].sudo().get_param('autorizacioncaja'):
            self.is_admin = True
        else:
            raise UserError('La clave ingresada es incorrecta')

    def modifico(self):
        if self.is_admin == True:
            self.is_admin = False
            return True
        popup = self.env['paimon.popup.confirmation']
        action = popup.show_aut(self, 'Ingrese la clave de autorizacion', 'autorizo')
        return action

    @api.onchange('vuelto')
    def _compute_total_calculado_vuelto(self):
        for record in self:
            if self.efectivo ==0:
                return {}
            if record.sale_with_discount > 0:
                total = record.sale_with_discount
            else:
                total = record.amount_total
            record.redondeo = 0
            if record.efectivo == 0:
                record.vuelto = 0
            redondeo = total  - ( record.efectivo - record.vuelto)
            if abs(redondeo) > 1000:
                raise ValidationError('No puede aplicar un redondeo mayor a 1.000 (%s) ' % redondeo)
            record.redondeo = redondeo
            record.total_calculado = total - self.redondeo 


    @api.onchange('efectivo')
    def _compute_total_efectivo(self):
        for record in self:
            if record.sale_with_discount > 0:
                total = record.sale_with_discount
            else:
                total = record.amount_total
            record.redondeo = 0
            if record.vuelto == 0:
                record._compute_vuelto()
            if record.vuelto >= 0 and record.efectivo > 0:
                redondeo = total  - ( record.efectivo - record.vuelto)
                record.redondeo = redondeo
            record.total_calculado = total - self.redondeo 

    @api.onchange('sale_discount','amount_total','sale_with_discount')
    def _compute_total_calculado(self):
        for record in self:
            record.efectivo = 0
            record.vuelto = 0
           #if record.amount_total and not record.efectivo:
           #    _logger.info('Pongo en 0')
           #    record.efectivo = 0
           #    record.vuelto = 0
            if record.sale_with_discount > 0:
                total = record.sale_with_discount
            else:
                total = record.amount_total
            record.redondeo = 0
            if record.vuelto == 0:
                record._compute_vuelto()
            if record.vuelto >= 0 and record.efectivo > 0:
                redondeo = total  - ( record.efectivo - record.vuelto)
               #if abs(redondeo) > 1000:
               #    raise ValidationError('No puede aplicar un redondeo mayor a 1.000 (%s) ' % redondeo)
                record.redondeo = redondeo
            record.total_calculado = total - self.redondeo 

    #@api.onchange('efectivo')
    def _compute_vuelto(self):
        for record in self:
            if record.sale_with_discount > 0 :
                total = record.sale_with_discount
            else:
                total = record.amount_total
            if record.efectivo > total:
                record.vuelto = record.efectivo - total
                if record.vuelto < 0:
                    record.vuelto = 0
                

    #@api.onchange('vuelto')
    def _compute_vuelto_efectivo(self):
        for record in self:
            if record.sale_with_discount > 0 :
                total = record.sale_with_discount
            else:
                total = record.amount_total
            _logger.info('REDONDEO  %s ' %  total)
            redondeo = total  - ( record.efectivo - record.vuelto)
            if abs(redondeo) > 1000:
                raise ValidationError('No puede aplicar un redondeo mayor a 1.000 (%s) ' % redondeo)
            self.redondeo = redondeo
