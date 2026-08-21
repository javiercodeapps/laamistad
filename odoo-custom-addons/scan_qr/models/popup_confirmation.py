# -*- coding: utf-8 -*-

from odoo import models, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

# TODO: add example how to used this custom popup
class CustomPopupConfirmation(models.TransientModel):
    _name = 'paimon.popup.confirmation'
    _description = "Custom Popup Confirmation"

    message = fields.Char()
    text  = fields.Char()
    callback = fields.Char()
    source_model = fields.Char()

    def show(self, records, message, callback_name=None):
        context = dict(self.env.context)
        context.update(record_ids=records.ids)

        popup = self.create(dict(
            message     = message,
            callback    = callback_name,
            source_model= records._name,)
        )

        action =  dict(
            name        = 'Confirmation',
            target      = 'new',
            res_id      = popup.id,
            view_mode   = 'form',
            res_model   = self._name,
            view_id     = self.env.ref('scan_qr.custom_popup_confirmation').id,
            type        = 'ir.actions.act_window',
            context     = context,
        )
        return action

    def show_aut(self, records, message, callback_name=None):
        context = dict(self.env.context)
        context.update(record_ids=records.ids)

        popup = self.create(dict(
            message     = message,
            callback    = callback_name,
            source_model= records._name,)
        )

        action =  dict(
            name        = 'Confirmation',
            target      = 'new',
            res_id      = popup.id,
            view_mode   = 'form',
            view_id     = self.env.ref('scan_qr.custom_popup_clave').id,
            res_model   = self._name,
            type        = 'ir.actions.act_window',
            context     = context,
        )
        return action
    def show_efectivo(self, records, message, callback_name=None):
        context = dict(self.env.context)
        context.update(record_ids=records.ids)

        popup = self.create(dict(
            message     = message,
            callback    = callback_name,
            source_model= records._name,)
        )

        action =  dict(
            name        = 'Confirmation',
            target      = 'new',
            res_id      = popup.id,
            view_mode   = 'form',
            view_id     = self.env.ref('scan_qr.custom_popup_efectivo').id,
            res_model   = self._name,
            type        = 'ir.actions.act_window',
            context     = context,
        )
        return action

    def confirm(self):
        context = self.env.context
        record_ids = context.get('record_ids') or []
        model = self.env['ir.model'].search([('model', '=', self.source_model)])
        # check if model is exist
        if not model:
            message = 'not found model {}'.format(self.source_model)
            _logger.warning(message)
            raise UserError(message)

        if self.callback:
            records = self.env[self.source_model].browse(record_ids)
            callback = getattr(records, self.callback, None)
            # check if function is exist inside model
            if not callback:
                message = 'model {} dont have function {}'.format(self.source_model, self.callback)
                _logger.warning(message)
                raise UserError(message)
            if self.text:
                return callback(self.text)
            return callback()
