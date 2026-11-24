# -*- coding: utf-8 -*-
"""Enganche entre las transacciones 'MP QR' y los pedidos de ``scan_qr``.

El proveedor ``payment_mercado_pago_qr`` llama a ``_mp_qr_prepare_documents``
justo ANTES de marcar la transacción como ``done``. Hasta ese momento el pedido
sigue en presupuesto (``draft``) y sin factura; recién acá, y sólo si el pago
pudo verificarse, se confirma el pedido y se emite la factura.

Si ``scan_qr`` no estuviera instalado, el proveedor simplemente no encuentra el
método y mantiene su comportamiento anterior (compatibilidad hacia atrás).
"""
import logging
import re

from odoo import models, _
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _mp_qr_linked_orders(self):
        """Pedidos que apuntan DIRECTAMENTE a esta transacción.

        A diferencia de ``_mp_qr_orders`` no usa el fallback por nombre: al
        cancelar un QR viejo no queremos revertir un pedido que ya tiene un QR
        nuevo vigente.
        """
        self.ensure_one()
        SaleOrder = self.env['sale.order'].sudo()
        if 'payment_provider' not in SaleOrder._fields:
            return SaleOrder.browse()
        return SaleOrder.search([('payment_provider', '=', self.id)])

    def _set_canceled(self, state_message=None):
        """Al cancelar un QR, devolver el presupuesto a su estado previo.

        Cubre TODAS las rutas: botón 'Cancel order' del wizard, IPN de
        vencimiento/cancelación de Mercado Pago y cambio de medio de pago.
        El flag de contexto evita revertir durante la regeneración del QR.
        """
        res = super()._set_canceled(state_message)
        if self.env.context.get('mp_qr_no_cancel_revert'):
            return res
        for tx in res:
            orders = tx._mp_qr_linked_orders()
            if orders:
                orders._mp_qr_revert_on_cancel()
        return res

    def _mp_qr_orders(self):
        """Pedido(s) de venta asociados a esta transacción QR."""
        self.ensure_one()
        SaleOrder = self.env['sale.order'].sudo()
        orders = SaleOrder.browse()
        # Enlace principal: sale.order.payment_provider -> payment.transaction.
        if 'payment_provider' in SaleOrder._fields:
            orders |= SaleOrder.search([('payment_provider', '=', self.id)])
        if not orders:
            # Compatibilidad con transacciones anteriores (M2M sale_order_ids).
            orders |= self.sale_order_ids.sudo()
        if not orders and self.reference:
            # Último recurso para poder avisar en el chatter si el pedido ya
            # apunta a un QR más nuevo: la referencia empieza con el nombre del
            # pedido ('S000123' o 'S000123-2').
            name = re.sub(r'-\d+$', '', self.reference.strip())
            orders |= SaleOrder.search([('name', '=', name)], limit=1)
        return orders

    def _mp_qr_prepare_documents(self, order_data=None, expected_amount=None):
        """Valida el pago del QR y, sólo si es correcto, confirma y factura.

        Devuelve ``False`` (fail closed) cuando no se puede verificar: en ese
        caso el proveedor NO marca la transacción como ``done`` y no se emite
        ninguna factura ni se registra ningún cobro.
        """
        self.ensure_one()
        if self.provider_code != 'mercado_pago_qr':
            return True
        orders = self._mp_qr_orders()
        if not orders:
            _logger.warning('MP QR %s: no se encontró el pedido asociado; no se factura.',
                            self.reference)
            return False
        if self.state == 'done':
            # IPN duplicado / reintento: no facturar dos veces, sólo asegurar
            # que la factura siga vinculada a la transacción.
            invoices = orders._mp_qr_invoices()
            if invoices:
                self.invoice_ids = [(6, 0, invoices.ids)]
            return True
        if self.state in ('cancel', 'error'):
            # Sólo revertir pedidos que aún apuntan a ESTA transacción: si ya
            # generaron un QR nuevo, ese QR vigente no se debe tocar.
            self._mp_qr_linked_orders()._mp_qr_revert_on_cancel()
            orders._mp_qr_payment_warning(_(
                'Mercado Pago informó un pago para el QR %s, pero la transacción ya '
                'estaba cancelada o vencida. No se facturó; verifique el cobro en '
                'Mercado Pago antes de cobrar por otro medio.') % self.reference)
            return False
        if not self._mp_qr_verify_payment(order_data, expected_amount, orders):
            # Pago inválido / no verificable: volver al tipo original y
            # recalcular el descuento con ese tipo, sin dejar códigos aplicados.
            orders._mp_qr_revert_on_cancel()
            return False
        try:
            for order in orders:
                order._mp_qr_confirm_and_invoice(self)
        except Exception:
            _logger.exception('MP QR %s: error al confirmar/facturar el pedido', self.reference)
            # El pago NO quedó registrado: volver al tipo original y dejar el
            # presupuesto sin códigos de descuento aplicados.
            orders._mp_qr_revert_on_cancel()
            orders._mp_qr_payment_warning(_(
                'el pago fue verificado pero no se pudo confirmar el pedido ni '
                'emitir la factura. Revise el log; la transacción NO se marcó '
                'como pagada.'))
            return False
        # Si la transacción venía enlazada por sale_order_ids (flujo anterior),
        # la desvinculamos: con 'sale.automatic_invoice' activo, el post-proceso
        # de 'sale' intentaría facturar de nuevo y pisaría tx.invoice_ids.
        if self.sale_order_ids:
            self.sudo().write({'sale_order_ids': [(5, 0, 0)]})
        return True

    def _mp_qr_verify_payment(self, order_data, expected_amount, orders):
        """Fail closed: estado, referencia externa, moneda e importe."""
        order_data = order_data or {}
        status = order_data.get('status')
        if status != 'paid' and order_data.get('status_detail') != 'accredited':
            orders._mp_qr_payment_warning(_(
                'Mercado Pago informa la orden %s en estado %s: no se facturó.')
                % (self.reference, status or '-'))
            return False
        # La orden se consultó a la API por su id (provider_reference), pero
        # además validamos la referencia externa que enviamos al crearla.
        ext_ref = str(order_data.get('external_reference') or '').strip().strip('"\'').strip().upper()
        reference = str(self.reference or '').strip().upper()
        if ext_ref and ext_ref != reference:
            orders._mp_qr_payment_warning(_(
                'el pago del QR %s tiene la referencia "%s" y se esperaba "%s": '
                'no se facturó.') % (self.reference, ext_ref, reference))
            return False
        if not ext_ref:
            _logger.warning('MP QR %s: la respuesta de Mercado Pago no trae '
                            'external_reference; se valida por el id de orden %s.',
                            self.reference, self.provider_reference)
        currency = orders[:1].currency_id or self.currency_id
        pay_currency = order_data.get('currency_id')
        if pay_currency and currency.name and pay_currency != currency.name:
            orders._mp_qr_payment_warning(_(
                'el pago del QR %s es en %s y el pedido en %s: no se facturó.')
                % (self.reference, pay_currency, currency.name))
            return False
        try:
            paid = float(order_data.get('total_amount') or order_data.get('total_paid') or 0.0)
        except (TypeError, ValueError):
            paid = 0.0
        expected = expected_amount if expected_amount is not None else self.amount
        if float_compare(paid, expected, precision_rounding=currency.rounding or 0.01) < 0:
            orders._mp_qr_payment_warning(_(
                'el pago del QR %s es por %s y se esperaban %s: no se facturó. '
                'Verifique el cobro en Mercado Pago.')
                % (self.reference, currency.format(paid), currency.format(expected)))
            return False
        return True
