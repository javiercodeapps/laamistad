from odoo import models, fields, api
from odoo.exceptions import UserError

class ImportXlsWizard(models.TransientModel):
    _name = "import.xls.wizard"
    _description = "Import XLS Order"

    file_xls = fields.Binary("Archivo", required=True)
    file_xls_name = fields.Char("Archivo Name")

    def action_import(self):
        purchase_order_model = self.env["purchase.order"]
        purchase_id = purchase_order_model.create_order_from_xls(self.file_xls, self.file_xls_name)

        if purchase_id:
            order = purchase_order_model.browse(purchase_id)
           # order.action_confirm()

            return {
                "type": "ir.actions.act_window",
                "res_model": "purchase.order",
                "res_id": order.id,
                "view_mode": "form",
                "target": "current",
            }
        else:
            raise UserError("Failed to create a Purchase Order. Please check file.")
