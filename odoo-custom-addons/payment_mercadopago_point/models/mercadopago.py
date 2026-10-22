# -*- coding: utf-8 -*-
import ast
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

    def create_order_link(self,sale_orders):
        """Crea un único link de pago de Mercado Pago para una o varias órdenes
        de venta. El monto del link es la suma de todas las órdenes recibidas."""
        sale_orders = sale_orders.sorted('id')
        if not sale_orders:
            raise UserError(_("No se indicaron órdenes de venta para generar el link de pago."))
        mp_token = self.payment_provider_id.mercado_pago_qr_access_token
        base_url = self.get_base_url()
        sdk = mercadopago.SDK(mp_token)
        fecha_exp = calcular_fecha_expiracion()
        # Un único ítem por el total del link (la suma de todas las órdenes)
        partner = sale_orders[:1].partner_id
        mercadopago_items = [{
            "title": 'La Amistad - %s' % (partner.name or partner.display_name),
            "quantity": 1,
            "currency_id": sale_orders[:1].currency_id.name or 'ARS',
            # amount_total ya incluye los impuestos de todas las líneas
            "unit_price": sum(sale_orders.mapped('amount_total')),
        }]
        # Referencia externa combinada (Mercado Pago limita el campo a 256 caracteres)
        referencia = ', '.join(sale_orders.mapped('name'))[:256]
        data = { "items": mercadopago_items,
                "back_urls": {
                         "success": f"{base_url}/mercadopago_point_payment/success",
                         "failure": f"{base_url}/mercadopago_point_payment/failure",
                         "pending": f"{base_url}/mercadopago_point_payment/pending",
                },
                "expires": True,  # importante para que se respete la fecha
                "date_of_expiration": fecha_exp,
                "auto_return": "approved",
                "external_reference": referencia,
                "description": referencia,
            }
        _logger.info("data: %s", data)
        preference_response = sdk.preference().create(data)
        _logger.info("preference_response: %s", preference_response)
        preference = preference_response["response"]
        # Guardo el vencimiento real del link para poder reutilizarlo mientras
        # siga vigente (y no generar links nuevos sin necesidad).
        expiration_date = _parse_mp_datetime(
            preference.get('date_of_expiration') or fecha_exp)
        # Registro el historial y aviso en cada orden que participa del link
        for so in sale_orders:
            self.env['payment_mercadopago_point.mercadopago.history'].create({
                'sale_id': so.id,
                'name': referencia,
                'preference': str(preference),
                'preference_id': preference.get('id'),
                'mp_link': preference.get('init_point'),
                'expiration_date': expiration_date,
            })
            so.message_post(body='Mercado Pago Link de pago %s (Órdenes: %s)' % (preference['init_point'], referencia))
        return preference['init_point']

    def search_payments(self, external_reference, limit=30):
        """Busca en Mercado Pago los pagos asociados a una referencia externa.

        Se usa para comprobar si el pago ingresó aunque el callback/webhook
        no se haya disparado. Devuelve la lista de pagos encontrados (puede
        haber intentos rechazados y uno aprobado).
        """
        mp_token = self.payment_provider_id.mercado_pago_qr_access_token
        sdk = mercadopago.SDK(mp_token)
        response = sdk.payment().search({
            "external_reference": external_reference,
            "limit": limit,
        })
        _logger.info("MP payment search %s: %s", external_reference, response)
        status = response.get("status")
        if status and status >= 400:
            raise UserError(_("Mercado Pago devolvió un error al consultar los pagos: %s")
                            % (response.get("response") or response))
        results = (response.get("response") or {}).get("results") or []
        if not isinstance(results, list):
            results = []
        # El más reciente primero (para priorizar el último intento)
        results.sort(key=lambda p: p.get('date_created') or '', reverse=True)
        return results

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
        pref = ast.literal_eval(preference.preference or '{}')
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


def calcular_fecha_expiracion(creacion_dt=None, hora_limite=23, horas_duracion=3):
    """
    Calcula la fecha de expiración para un link de pago.
    - Si creacion_dt es None, usa la hora actual.
    - La expiración será: creacion + horas_duracion, pero sin superar las hora_limite (23:00) del mismo día
      (si ya pasó esa hora, se usa el plazo completo para no generar un link vencido).
    - Retorna un string ISO 8601 con zona horaria (offset) para Mercado Pago.
    """
    # 1. Obtener la fecha/hora actual con zona horaria (ej. 'America/Asuncion' o la de la empresa)
    tz = pytz.timezone('America/Argentina/Buenos_Aires')  # Ajusta según tu zona horaria
    if creacion_dt is None:
        ahora = datetime.now(tz)
    else:
        # Si creacion_dt es naive, asumimos que es local y la localizamos
        if creacion_dt.tzinfo is None:
            creacion_dt = tz.localize(creacion_dt)
        ahora = creacion_dt

    # 2. Calcular fecha de expiración por tiempo (3 horas después)
    expiracion_por_tiempo = ahora + timedelta(hours=horas_duracion)

    # 3. Calcular el límite de hoy (por defecto 23:00)
    limite_hoy = ahora.replace(hour=hora_limite, minute=0, second=0, microsecond=0)

    # 4. Tomar el mínimo entre ambos, pero solo si el límite del día todavía
    #    no pasó. Si ya pasó (ej. se genera el link a las 23:15), aplicar ese
    #    tope daría una fecha vencida; en ese caso usamos el plazo normal.
    if limite_hoy > ahora:
        fecha_expiracion = min(expiracion_por_tiempo, limite_hoy)
    else:
        fecha_expiracion = expiracion_por_tiempo

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
    preference_id = fields.Char('Preference ID')
    mp_link = fields.Char('Link de pago')
    expiration_date = fields.Datetime('Vencimiento del link')
    date = fields.Datetime('Date', default=fields.Datetime.now)

    def get_id(self,so):
        preference = self.env['payment_mercadopago_point.mercadopago.history'].search([('sale_id', '=', so.id)],order='date desc', limit=1)
        pref = ast.literal_eval(preference.preference or '{}')
        return pref['id']

    def _get_link_data(self):
        """Devuelve los datos del link guardados en este historial.

        Para registros viejos (creados antes de agregar los campos) se
        reconstruyen leyendo el diccionario de la preferencia que se guardó
        en el campo ``preference``.
        """
        self.ensure_one()
        data = {
            'mp_link': self.mp_link,
            'preference_id': self.preference_id,
            'date_of_expiration': self.expiration_date,
            'reference': self.name,
        }
        if not (data['mp_link'] or data['preference_id'] or data['date_of_expiration']):
            try:
                preference = ast.literal_eval(self.preference or '{}')
            except (ValueError, SyntaxError):
                preference = {}
            if isinstance(preference, dict):
                data['mp_link'] = preference.get('init_point') or preference.get('sandbox_init_point')
                data['preference_id'] = preference.get('id')
                data['date_of_expiration'] = preference.get('date_of_expiration')
        return data

    def _get_expiration_datetime(self):
        """Vencimiento del link como datetime UTC naive (o False)."""
        self.ensure_one()
        value = self.expiration_date
        if not value:
            value = self._get_link_data().get('date_of_expiration')
        return _parse_mp_datetime(value)


def _parse_mp_datetime(value):
    """Convierte una fecha ISO 8601 de Mercado Pago a datetime UTC naive,
    que es el formato que Odoo guarda en los campos Datetime."""
    if not value:
        return False
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return False
    if dt.tzinfo is not None:
        dt = dt.astimezone(pytz.utc).replace(tzinfo=None)
    return dt
