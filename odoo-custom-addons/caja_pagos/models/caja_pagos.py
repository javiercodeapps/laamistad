from odoo import models, fields, api
from datetime import datetime, timedelta
from odoo.exceptions import UserError
import openpyxl
from io import BytesIO
from base64 import b64decode
import logging
_logger = logging.getLogger(__name__)

class CajaPagos(models.Model):
    _name = "caja.pagos"
    _description = "Pagos desde Caja"
    _order = 'create_date desc'
    _inherit = ['mail.thread']
    tipo = fields.Many2one('caja.pagos.tipo',string='Tipo')
    name = fields.Char(string='Descripcion')
    origen = fields.Many2one('account.journal')
    destino = fields.Many2one('account.journal')
    monto = fields.Float(string='Monto',tracking=True)
    cashbox_session = fields.Many2one('account.cashbox.session', domain=([('state','=','opened')]) )  #, compute='_default_cashbox_session')
    payment_group = fields.Many2one('account.payment.group',tracking=True)
    payment = fields.Many2one('account.payment',tracking=True)
    user    = fields.Many2one('res.users', default=lambda self: self.env.user.id)
    state = fields.Selection([
                   ('draft', 'Borrador'),
                   ('done', 'Procesada'),
                   ('cancel', 'Cancelada')
                   ], default="draft", string="Estado",tracking=True)
    is_admin = fields.Boolean(default=False, store=True)
    company_id = fields.Many2one('res.company', 'Company' , default=lambda self: self.env.company)


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
        self.state = 'draft'
        if self.tipo.tipo_pago == 'Pago':
            self.payment_group.action_draft()
            self.payment_group.cancel()
        else:
            self.payment.action_draft()
            self.payment.action_cancel()
            # Busco la segunda transferencia
            if self.payment.is_internal_transfer and self.payment.id:
                domain = [
                          ('id', '!=', self.payment.id),
                          ('is_internal_transfer', '=', True),
                          ('ref', '=', self.payment.ref),
                          ('amount', '=', self.payment.amount),
                          ('journal_id', '=', self.payment.destination_journal_id.id),
                          ('destination_journal_id', '=', self.payment.journal_id.id),
                          ]
                paired_payment_id = self.env['account.payment'].search(domain, limit=1, order='id desc')
                if paired_payment_id:
                    paired_payment_id.action_draft()
                    paired_payment_id.action_cancel()
        popup = self.env['paimon.popup.confirmation']
        action = popup.show_aut(self, 'Ingrese la clave de autorizacion', 'autorizo')
        return action

    def cancelar(self):
        if self.is_admin == True:
            self.is_admin = False
            return True
        self.state = 'cancel'
        popup = self.env['paimon.popup.confirmation']
        action = popup.show_aut(self, 'Ingrese la clave de autorizacion', 'autorizo')
        return action

    def imprimir(self):
        if self.payment_group:
           # return self.env.ref('account_payment_group.action_report_payment_group').report_action(self.payment_group)
            return self.env.ref('custom_account_payment_report.action_report_payment_group_custom').report_action(self.payment_group)


        if self.payment:
          # return self.env.ref('account.action_report_payment_receipt').report_action(self.payment)
            return self.env.ref('custom_account_payment_report.action_report_payment_custom').report_action(self.payment)


    def _default_cashbox_session(self):
        for record in self:
            caja = self.env['account.cashbox.session'].search([('state','=','opened')])
            if not caja:
                raise UserError('No se encontro ninguna caja abierta')
            return  caja[0].id

    @api.onchange('tipo')
    def _compute_origen(self):
        for record in self:
            record.origen = self.tipo.origen
            record.destino = self.tipo.destino

  # @api.model
  # def create(self, vals):
  #     p = super(CajaPagos,self).create(vals)
  #     _logger.info('GENERAR PAGO %s' % p)
  #     p.generar()
  #     return p

    def generar(self):
        _logger.info('PAGO %s' % self.tipo.tipo_pago)
        caja = self.env['account.cashbox.session'].search([('state','=','opened')])
        if not caja:
            raise UserError('No se encontro ninguna caja abierta')
        self.cashbox_session = caja[0]
        if self.tipo.tipo_pago == 'Pago':
            self.state = 'done'
            payment_lines = [{'payment_type':'outbound',
                'amount':self.monto, 
                'ref': self.name,
                'journal_id':self.origen.id,
                #'cashbox_session_id': caja[0].id if caja else '',
                'cashbox_session_id': self.cashbox_session.id,
                }]
            paygroup = {'partner_id' : self.tipo.partner_id.id,
                    'communication': self.name,
                    'partner_type': 'supplier',
                    'receiptbook_id': self.tipo.talonario.id,
                    "payment_ids": [(0, 0, line) for line in payment_lines],
                    }

            p = self.env['account.payment.group'].create(paygroup)
            p.post()
            self.payment_group = p.id
            return p.id
        if self.tipo.tipo_pago == 'Transferencia':
            action =  dict(
            name        = 'Transferencia',
            target      = 'new',
            view_mode   = 'form',
            res_model   = 'account.payment',
            type        = 'ir.actions.act_window',
            context     = {'form_view_ref': 'account_payment_group.view_account_payment_form2','default_payment_type': 'outbound','default_is_internal_transfer': True,'default_move_journal_types': ('bank', 'cash'),'default_ref':self.name,'default_amount':self.monto,'default_destination_journal_id':self.destino.id,'default_journal_id':self.origen.id,'caja_pago_id':self.id,'default_cashbox_session_id':self.cashbox_session.id,'default_available_journal_ids':[self.origen.id]},
            domain      = [('is_internal_transfer', '=', 'transfer')],)
            _logger.info('%s' % action)
            return action

class AccoutPayment(models.Model):
    _inherit='account.payment'

    def action_post(self):
        res = super().action_post()
        context = self.env.context
        if context.get('caja_pago_id',None):
            pago = self.env['caja.pagos'].search([('id','=',context.get('caja_pago_id',None))])
            for p in pago:
                p.write({'state':'done','payment':self.id})
        return res

#   def create(self, vals):
#       res_id = super(self,vals).create()
#       pago = self.env['caja.pagos'].search([('id','=',context.get('caja_pago_id',None))])
#       for p in pago:
#           res_id.action_post()
#       return res_id


class CajaPagosTipo(models.Model):
    _name = "caja.pagos.tipo"
    _description = "Tipo de pagos desde Caja"
    name = fields.Char(string="Name")
    partner_id = fields.Many2one("res.partner", string="Contacto")
    tipo_pago = fields.Selection([('Pago','Pago'),('Transferencia','Transferencia')],string="Tipo")
    talonario = fields.Many2one('account.payment.receiptbook')
    origen = fields.Many2one('account.journal')
    destino = fields.Many2one('account.journal')
    company_id = fields.Many2one('res.company', 'Company')

