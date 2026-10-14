// static/src/js/notification_receiver.js
odoo.define('payment_mercadopago_point.notification_receiver', function (require) {
    "use strict";

    var session = require('web.session');
    var bus = require('bus.bus').bus;

    // Canal con el ID del usuario actual
    var channel = JSON.stringify([session.db, 'mercadopago_notification_' + session.uid]);

    // Suscribirse al canal
    bus.add_channel(channel);

    // Escuchar mensajes
    bus.on('notification', this, function (notifications) {
        _.each(notifications, function (notif) {
            if (notif.type === 'payment_processed') {
                // Muestra la notificación (toast, alert, etc.)
                if (notif.status === 'success') {
                    // Usa el sistema de notificaciones de Odoo
                    // En backend: this.do_notify(...) o Notification widget
                    // En frontend: puedes usar alert o un toast personalizado
                    alert(notif.message); // Simple, pero puedes mejorar
                }
            }
        });
    });
});