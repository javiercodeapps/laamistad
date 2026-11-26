/** @odoo-module **/
/* Copyright 2026 Ernesto Bernis - BlackLabs */

import { Component, onWillStart, onWillUnmount, useExternalListener, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

// Refresco adaptativo: este servidor puede correr sin workers y el bus no
// siempre es confiable, por eso el chip nunca depende solo del push.
const POLL_OK_MS = 5 * 60 * 1000;
const POLL_ALERT_MS = 45 * 1000;

const CHIP_CLASS_BY_LEVEL = {
    ok: "bl-afip-top-chip-ok",
    warning: "bl-afip-top-chip-warning",
    down: "bl-afip-top-chip-down",
    error: "bl-afip-top-chip-error",
    loading: "bl-afip-top-chip-loading",
};

export class BlAfipStatusSystray extends Component {
    static template = "bl_afip_status.SystrayItem";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        // bus_service declara async=true y rompe el wrapper de useService: se toma directo.
        this.busService = this.env.services.bus_service;
        this.rootRef = useRef("root");

        this.state = useState({
            visible: false,
            level: "loading",
            title: _t("Verificando ARCA"),
            message: _t("Chequeando servicio..."),
            app_status: "",
            db_status: "",
            auth_status: "",
            checked_at: "",
            services: [],
            can_test: false,
            test_mode_enabled: false,
            test_block_active: false,
            test_block_mode: "soft",
            test_block_until: "",
            open: false,
            loading: true,
        });

        this._poll = null;
        this._pollDelay = null;
        this._onBusUpdate = (payload) => this._handleBusUpdate(payload);

        onWillStart(async () => {
            await this.reload();
            this._subscribeBus();
            this._schedulePoll();
        });

        onWillUnmount(() => {
            if (this._poll) {
                clearInterval(this._poll);
            }
            try {
                this.busService.unsubscribe("bl_afip_status/update", this._onBusUpdate);
                this.busService.deleteChannel("bl_afip_status");
            } catch (error) {
                // el bus puede no estar disponible: no es critico
            }
        });

        useExternalListener(window, "click", (ev) => {
            if (this.state.open && this.rootRef.el && !this.rootRef.el.contains(ev.target)) {
                this.state.open = false;
            }
        });
    }

    get chipClass() {
        return CHIP_CLASS_BY_LEVEL[this.state.level] || CHIP_CLASS_BY_LEVEL.loading;
    }

    get shortLabel() {
        switch (this.state.level) {
            case "ok":
                return _t("ARCA OK");
            case "warning":
                return _t("ARCA ALERTA");
            case "down":
                return _t("ARCA CAIDO");
            case "error":
                return _t("ARCA REVISAR");
            default:
                return _t("ARCA CHECK");
        }
    }

    get tooltip() {
        const app = this.state.app_status || "-";
        const db = this.state.db_status || "-";
        const auth = this.state.auth_status || "-";
        const checked = this.state.checked_at || "-";
        const testLine = this.state.test_block_active
            ? `MODO PRUEBA (${this.state.test_block_mode || "soft"}) - vence ${this.state.test_block_until || "-"}\n`
            : "";
        const message = this.state.message || "";
        const baseMessage = message.startsWith("MODO PRUEBA")
            ? message.split("\n").slice(1).join("\n") || message
            : message;
        return `${testLine}${this.state.title}\n${baseMessage}\nApp/DB/Auth: ${app}/${db}/${auth}\n${checked}`;
    }

    get showTestButton() {
        return this.state.test_mode_enabled && this.state.can_test;
    }

    get testButtonClass() {
        return this.state.test_block_active ? "bl-afip-block-btn-on" : "bl-afip-block-btn-off";
    }

    get testButtonLabel() {
        const mode = this.state.test_block_mode || "soft";
        if (mode === "firewall") {
            return this.state.test_block_active ? _t("FW BLOQ") : _t("FW REAL");
        }
        return this.state.test_block_active ? _t("ARCA BLOQ") : _t("ARCA REAL");
    }

    chipClassFor(level) {
        return CHIP_CLASS_BY_LEVEL[level] || CHIP_CLASS_BY_LEVEL.loading;
    }

    _schedulePoll() {
        const delay = this.state.level === "ok" ? POLL_OK_MS : POLL_ALERT_MS;
        if (this._poll && this._pollDelay === delay) {
            return;
        }
        if (this._poll) {
            clearInterval(this._poll);
        }
        this._pollDelay = delay;
        this._poll = setInterval(() => this.reload(), delay);
    }

    _subscribeBus() {
        try {
            this.busService.addChannel("bl_afip_status");
            this.busService.subscribe("bl_afip_status/update", this._onBusUpdate);
        } catch (error) {
            console.warn("bl_afip_status: bus no disponible, queda solo el refresco periodico", error);
        }
    }

    _apply(data) {
        if (!data) {
            return;
        }
        this.state.visible = Boolean(data.visible);
        this.state.level = data.level || "loading";
        this.state.title = data.title || "";
        this.state.message = data.message || "";
        this.state.app_status = data.app_status || "";
        this.state.db_status = data.db_status || "";
        this.state.auth_status = data.auth_status || "";
        this.state.checked_at = data.checked_at || "";
        this.state.services = data.services || [];
        this.state.can_test = Boolean(data.can_test);
        this.state.test_mode_enabled = Boolean(data.test_mode_enabled);
        this.state.test_block_active = Boolean(data.test_block_active);
        this.state.test_block_mode = data.test_block_mode || "soft";
        this.state.test_block_until = data.test_block_until || "";
        this._schedulePoll();
    }

    async reload() {
        try {
            const data = await this.orm.silent.call("bl.afip.status", "get_systray_state", []);
            this._apply(data);
        } catch (error) {
            console.warn("bl_afip_status: no se pudo leer el estado", error);
        } finally {
            this.state.loading = false;
        }
    }

    async _handleBusUpdate(payload) {
        await this.reload();
        if (payload && payload.event === "recovered") {
            this.notification.add(
                _t("ARCA volvio a estar operativo. Ya podes emitir los comprobantes pendientes."),
                { type: "success", title: _t("Servicio ARCA restablecido") }
            );
        } else if (payload && payload.event === "down") {
            this.notification.add(
                _t("ARCA no esta respondiendo. La emision de comprobantes electronicos puede fallar."),
                { type: "warning", title: _t("Servicio ARCA caido") }
            );
        }
    }

    onPanelClick() {
        // absorbe el click para que el listener de window no cierre el panel
    }

    toggle() {
        this.state.open = !this.state.open;
        if (this.state.open) {
            this.reload();
        }
    }

    async probeNow() {
        this.state.loading = true;
        this.state.level = "loading";
        this._schedulePoll();
        try {
            const data = await this.orm.call("bl.afip.status", "probe_now", []);
            this._apply(data);
            this.notification.add(
                this.state.level === "ok"
                    ? _t("ARCA responde correctamente.")
                    : _t("ARCA sigue sin responder correctamente."),
                { type: this.state.level === "ok" ? "success" : "warning" }
            );
        } catch (error) {
            console.warn("bl_afip_status: fallo la verificacion manual", error);
        } finally {
            this.state.loading = false;
        }
    }

    async toggleTestBlock() {
        this.state.loading = true;
        try {
            const target = !this.state.test_block_active;
            const data = await this.orm.call("bl.afip.status", "bl_toggle_test_block", [], { blocked: target });
            this._apply(data);
            this.notification.add(
                this.state.test_block_active
                    ? _t("Simulacion de caida ARCA activada.")
                    : _t("Simulacion de caida ARCA desactivada."),
                { type: this.state.test_block_active ? "warning" : "success" }
            );
        } catch (error) {
            console.warn("bl_afip_status: fallo el toggle de simulacion", error);
            this.notification.add(_t("No se pudo cambiar el modo de prueba de ARCA."), {
                type: "danger",
                title: _t("Error de simulacion"),
            });
        } finally {
            this.state.loading = false;
        }
    }

    openDetail() {
        this.state.open = false;
        this.action.doAction("bl_afip_status.action_bl_afip_status");
    }
}

export const blAfipStatusSystrayItem = { Component: BlAfipStatusSystray };

registry.category("systray").add("bl_afip_status.SystrayItem", blAfipStatusSystrayItem, { sequence: 90 });
