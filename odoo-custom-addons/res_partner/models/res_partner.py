from odoo import models, fields, api

class ResPartnerInherit(models.Model):
    _inherit = 'res.partner'

    def _get_name(self):
        name = super()._get_name()
        if self.ref:
            name = "[{}] {}".format(self.ref, name)
        return name

  # @api.depends('ref','name')
  # def name_get(self):
  #     res = []
  #     for rec in self:
  #         if rec.ref:
  #             res.append((rec.id, '%s - %s' % (rec.ref, rec.name)))
  #         else:
  #             res.append((rec.id,rec.name))
  #     return res
  # @api.depends('ref', 'name')
  # def _compute_display_name(self):
  #     for rec in self:
  #         if rec.ref:
  #             rec.display_name = "%s - %s"%(rec.ref,rec.name)
  #         else:
  #             rec.display_name = rec.name
