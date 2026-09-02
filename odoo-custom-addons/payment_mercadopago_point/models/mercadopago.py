# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import mercadopago
from datetime import datetime, timedelta
import pytz

import requests
from requests.structures import CaseInsensitiveDict
_logger = logging.getLogger(__name__)


class PaymentMercadopagoPoint(models.Model):
    _name = 'payment_mercadopago_point.mercadopago'
    _description = 'Payment Mercadopago Point'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char('Name')
     
    payment_provider_id = fields.Many2one('payment.provider', 'Payment Provider')
    terminal_id = fields.Char('Terminal ID')
    platform_id = fields.Char('Platform ID')
    company_id = fields.Many2one('res.company', 'Company', default=lambda self: self.env.company)
    
    def create_order(self,so):   
        mp_token = self.payment_provider_id.mercado_pago_qr_access_token
        sdk = mercadopago.SDK(mp_token)
        mercadopago_items = []
        for line in so.order_line:
            mercadopago_items.append({ "title": '%s %s' % (line.product_id.name,line.name),
                  "quantity": line.product_uom_qty,
                  "currency_id": 'ARS',
                  "unit_price": line.price_unit,
              })    
        data = { "type": "point",
          "external_reference": so.name,
          "expiration_time": "PT16M",
          "description": so.name,
          "transactions": {
          "payments": [
              {      
                "amount": "%s" % so.amount_total
              }
            ]
          },
          "config": {
            "point": {
              "terminal_id": self.terminal_id,
              "print_on_terminal": "no_ticket",
              "ticket_number": so.name
            },
          },
          "integration_data": {
            "platform_id": self.platform_id,
            
          },       
        }
        _logger.info("data: %s", data)
        preference_response = sdk.order().create(data)
        _logger.info("preference_response: %s", preference_response)
        preference = preference_response["response"]
        self.env['payment_mercadopago_point.mercadopago.history'].create({
            'sale_id': so.id,
            'name': so.name,
            'preference': str(preference),
        })
        so.message_post(body='Mercado Pago %s' % preference)
        return preference

    def create_order_link(self,so):
        mp_token = self.payment_provider_id.mercado_pago_qr_access_token
        base_url = self.get_base_url()
        sdk = mercadopago.SDK(mp_token)
        mercadopago_items = []
        fecha_exp = calcular_fecha_expiracion()
        for line in so.order_line:
            if line.product_uom_qty > 0:
                mercadopago_items.append({
                    "title": '%s %s' % (line.product_id.name,line.name),
                    "quantity": line.product_uom_qty,
                    "currency_id": 'ARS',
                    "unit_price": line.price_unit
            })
        data = { "items": mercadopago_items,
                "back_urls": {
                         "success": f"{base_url}/mercadopago_point_payment/success",
                         "failure": f"{base_url}/mercadopago_point_payment/failure",
                         "pending": f"{base_url}/mercadopago_point_payment/pending",
                },
                "expires": True,  # importante para que se respete la fecha
                "date_of_expiration": fecha_exp,
                "auto_return": "approved",
                "external_reference": so.name,
                "description": so.name,
            }
        _logger.info("data: %s", data)
        preference_response = sdk.preference().create(data)
        _logger.info("preference_response: %s", preference_response)
        preference = preference_response["response"]
        self.env['payment_mercadopago_point.mercadopago.history'].create({
            'sale_id': so.id,
            'name': so.name,
            'preference': str(preference),
        })
        so.message_post(body='Mercado Pago Link de pago %s' % preference['init_point'])
        return preference['init_point']

    def get_payment_status(self,so,payment_id=None):
        mp_token = self.payment_provider_id.mercado_pago_qr_access_token
        sdk = mercadopago.SDK(mp_token)
        response = sdk.payment().get(payment_id)
        payment = response["response"]
        status = payment["status"]
        return status

    def get_order_status(self,so):
        preference = self.env['payment_mercadopago_point.mercadopago.history'].search([('sale_id', '=', so.id)],order='date desc', limit=1)
        _logger.info("preference: %s", preference.preference)
        pref = eval(preference.preference)
        mp_token = self.payment_provider_id.mercado_pago_qr_access_token
        sdk = mercadopago.SDK(mp_token)
        preference_response = sdk.order().get(pref['id'])
        preference = preference_response["response"]
        _logger.info("preference: %s %s", (preference,pref['id']) )
        so.message_post(body='Mercado Pago %s' % preference)
        self.env['payment_mercadopago_point.mercadopago.history'].create({
            'sale_id': so.id,
            'name': so.name,
            'preference': str(preference),
        })
        return preference['status']

    def set_terminal_pdv(self):
        headers = CaseInsensitiveDict()
        headers["Authorization"]="Bearer %s" % self.payment_provider_id.mercado_pago_qr_access_token
        headers["Content-Type"] = "application/json"
        terminals = {'terminals' : [{'id': self.terminal_id,'operating_mode':'PDV'}] }
        preference = requests.patch("https://api.mercadopago.com/terminals/v1/setup", headers=headers, data=terminals)
        _logger.info("preference: %s", terminals)
        _logger.info("preference: %s", preference.content)
        import subprocess
        subprocess.Popen(['curl', '-X', 'PATCH', 'https://api.mercadopago.com/terminals/v1/setup', '-H', 'Authorization: Bearer %s' % self.payment_provider_id.mercado_pago_qr_access_token,'-H', 'Content-Type: application/json', '-d', '{"terminals": [{"id": "%s", "operating_mode": "PDV"}]}' % self.terminal_id])
        self.get_terminals()
        return True
    def set_terminal_manual(self):
        headers = CaseInsensitiveDict()
        headers["Authorization"]="Bearer %s" % self.payment_provider_id.mercado_pago_qr_access_token
        _logger.info("headers: %s", headers)
        headers["Content-Type"] = "application/json"
        terminals = {'terminals' : [{'id': self.terminal_id,'operating_mode':'STANDALONE'}] }
        preference = requests.patch("https://api.mercadopago.com/terminals/v1/setup", headers=headers, data=terminals)
        import subprocess
        subprocess.Popen(['curl', '-X', 'PATCH', 'https://api.mercadopago.com/terminals/v1/setup', '-H', 'Authorization: Bearer %s' % self.payment_provider_id.mercado_pago_qr_access_token,'-H', 'Content-Type: application/json', '-d', '{"terminals": [{"id": "%s", "operating_mode": "STANDALONE"}]}' % self.terminal_id])
        _logger.info("terminals: %s", terminals)
        _logger.info("preference: %s", preference.content)
        self.get_terminals()
        return True
    def get_terminals(self):
        headers = CaseInsensitiveDict()
        headers["Authorization"]="Bearer %s" % self.payment_provider_id.mercado_pago_qr_access_token
        headers["Content-Type"] = "application/json"
        preference = requests.get("https://api.mercadopago.com/terminals/v1/list", headers=headers)
        _logger.info("preference: %s", preference.content)
        self.message_post(body='Terminales %s' % preference.content)
        return True


def calcular_fecha_expiracion(creacion_dt=None, hora_limite=21, horas_duracion=3):
    """
    Calcula la fecha de expiración para un link de pago.
    - Si creacion_dt es None, usa la hora actual.
    - La expiración será: creacion + horas_duracion, pero sin superar las hora_limite (21:00) del mismo día.
    - Retorna un string ISO 8601 con zona horaria (offset) para Mercado Pago.
    """
    # 1. Obtener la fecha/hora actual con zona horaria (ej. 'America/Asuncion' o la de la empresa)
    tz = pytz.timezone('America/Buenos Aires')  # Ajusta según tu zona horaria
    if creacion_dt is None:
        ahora = datetime.now(tz)
    else:
        # Si creacion_dt es naive, asumimos que es local y la localizamos
        if creacion_dt.tzinfo is None:
            creacion_dt = tz.localize(creacion_dt)
        ahora = creacion_dt

    # 2. Calcular fecha de expiración por tiempo (3 horas después)
    expiracion_por_tiempo = ahora + timedelta(hours=horas_duracion)

    # 3. Calcular el límite de hoy a las 21:00
    limite_hoy = ahora.replace(hour=hora_limite, minute=0, second=0, microsecond=0)

    # 4. Tomar el mínimo entre ambos (el que ocurra primero)
    fecha_expiracion = min(expiracion_por_tiempo, limite_hoy)

    # 5. Validar que la fecha de expiración sea mayor que la actual (si no, el link ya expiró)
    if fecha_expiracion <= ahora:
        raise ValueError("La fecha de expiración calculada ya pasó. No se puede crear el link.")

    # 6. Formatear en ISO 8601 con offset (ej. -04:00)
    #    Mercado Pago espera algo como "2025-07-21T20:59:59.000-04:00"
    #    Obtenemos el offset como string
    offset = fecha_expiracion.strftime('%z')  # ej. -0400
    offset_formateado = offset[:3] + ':' + offset[3:]  # -04:00
    iso_str = fecha_expiracion.strftime('%Y-%m-%dT%H:%M:%S.000') + offset_formateado
    return iso_str

class PaymentMercadopagoPointHistory(models.Model):
    _name = 'payment_mercadopago_point.mercadopago.history'
    _description = 'Payment Mercadopago Point History'

    sale_id = fields.Many2one('sale.order', 'Sale Order')
    name = fields.Char('Name')
    preference = fields.Char('Preference')
    date = fields.Datetime('Date', default=fields.Datetime.now)

    def get_id(self,so):
        preference = self.env['payment_mercadopago_point.mercadopago.history'].search([('sale_id', '=', so.id)],order='date desc', limit=1)
        pref = eval(preference.preference)
        return pref['id']