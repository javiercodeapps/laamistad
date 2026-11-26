/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AfipStatusBanner extends Component {
    static template = "afip_webservice_monitor.StatusBanner";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.interval = null;

        this.state = useState({
            visible: false,
            wsfeAvailable: true,
            wsaaAvailable: true,
            lastCheck: null,
            errorMessage: null,
            loading: false,
        });

        onWillStart(async () => {
            await this.checkStatus();
        });

        onMounted(() => {
            // Check status every 5 minutes
            this.interval = setInterval(() => {
                this.checkStatus();
            }, 5 * 60 * 1000);
        });

        onWillUnmount(() => {
            if (this.interval) {
                clearInterval(this.interval);
            }
        });
    }

    async checkStatus() {
        try {
            this.state.loading = true;

            // Get configuration
            const params = await this.orm.call(
                "ir.config_parameter",
                "get_param",
                ["afip_webservice_monitor.show_banner"]
            );

            if (params === "False") {
                this.state.visible = false;
                return;
            }

            // Get status info
            const statusInfo = await this.orm.call(
                "afip.service.status",
                "get_status_info",
                []
            );

            this.state.wsfeAvailable = statusInfo.wsfe?.available ?? true;
            this.state.wsaaAvailable = statusInfo.wsaa?.available ?? true;
            this.state.lastCheck = statusInfo.wsfe?.check_date || null;
            this.state.errorMessage = statusInfo.wsfe?.error_message || null;

            // Show banner only if any service is unavailable
            this.state.visible = !this.state.wsfeAvailable || !this.state.wsaaAvailable;

        } catch (error) {
            console.error("Error checking AFIP status:", error);
            this.state.visible = false;
        } finally {
            this.state.loading = false;
        }
    }

    async onRefreshClick() {
        await this.checkStatus();

        if (this.state.wsfeAvailable && this.state.wsaaAvailable) {
            this.notification.add(
                "Servicio AFIP/ARCA disponible",
                {
                    type: "success",
                }
            );
        } else {
            this.notification.add(
                "Servicio AFIP/ARCA no disponible",
                {
                    type: "danger",
                }
            );
        }
    }

    onDismissClick() {
        this.state.visible = false;
    }
}

registry.category("main_components").add("AfipStatusBanner", {
    Component: AfipStatusBanner,
});
