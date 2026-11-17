/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";

export class McpListController extends ListController {
    /**
     * Opens the MCP model selection wizard and reloads the list when it closes.
     * Odoo 16 shows list header buttons only with a selection.
     */
    onClickMcpWizard() {
        return this.actionService.doAction(
            "mcp_server.action_mcp_model_selection_wizard",
            {
                onClose: async () => {
                    await this.model.root.load();
                    this.model.notify();
                },
            }
        );
    }
}

export const mcpListView = {
    ...listView,
    Controller: McpListController,
    buttonTemplate: "mcp_server.ListView.Buttons",
};

registry.category("views").add("mcp_list_with_wizard", mcpListView);
