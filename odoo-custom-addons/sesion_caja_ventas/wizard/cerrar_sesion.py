from odoo import models, fields, api
from odoo.exceptions import UserError

class CerrarSesionWizard(models.TransientModel):
    _name = "cerrar.sesion.wizard"
    _description = "Cerrar Sesión de Caja"

    efectivo_fin = fields.Float(string="Efectivo Final")

    def cerrar_sesion(self):
        sesion = self.env['sesion.caja'].browse(self.env.context.get('active_id'))
        sesion.efectivo_fin = self.efectivo_fin
        sesion.fecha_fin = fields.Datetime.now()
        sesion.state = 'cerrada'

        if not sesion.diferencia:
            return

        account_loss = self.env['account.account'].search([('name', 'ilike', 'Pérdida por diferencia de efectivo')], limit=1)
        account_gain = self.env['account.account'].search([('name', 'ilike', 'Ganancia por diferencia de efectivo')], limit=1)
        account_journal = self.env['account.account'].search([('name', 'ilike', 'Efectivo')], limit=1)

        if not account_loss or not account_gain:
            raise UserError("Deben existir las cuentas con nombre 'Efectivo', 'Pérdida por diferencia de efectivo' y 'Ganancia por diferencia de efectivo'.")

        move_vals = {
            'ref': f"Cierre Sesión Caja {sesion.name}",
            'date': fields.Date.today(),
            'journal_id': self.env['account.journal'].search([('type', '=', 'general')], limit=1).id,
            'line_ids': [],
        }

        if sesion.diferencia > 0:
            move_vals['line_ids'] = [
                (0, 0, {'account_id': account_journal.id, 'name': 'Ganancia por Caja', 'credit': 0.0, 'debit': sesion.diferencia}),
                (0, 0, {'account_id': account_gain.id, 'name': 'Ganancia por Caja', 'credit': sesion.diferencia, 'debit': 0.0}),
            ]
        else:
            move_vals['line_ids'] = [
                (0, 0, {'account_id': account_loss.id, 'name': 'Pérdida por Caja', 'credit': 0.0, 'debit': -sesion.diferencia}),
                (0, 0, {'account_id': account_journal.id, 'name': 'Pérdida por Caja', 'credit': -sesion.diferencia, 'debit': 0.0}),
            ]
        self.env['account.move'].create(move_vals)
