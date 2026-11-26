from odoo import models


class IrWebsocket(models.AbstractModel):
    _inherit = "ir.websocket"

    def _build_bus_channel_list(self, channels):
        channel_list = list(channels)
        user = self.env.user
        if user and not user._is_public() and user._is_internal():
            channel_list.append("bl_afip_status")
        return super()._build_bus_channel_list(channel_list)
