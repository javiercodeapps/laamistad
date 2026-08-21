/** @odoo-module **/

import { Component, useState, useRef, useExternalListener } from "@odoo/owl"
import { registry } from "@web/core/registry"
import { useService, useBus } from "@web/core/utils/hooks";

import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";

const CONNECTION_UNKNOW = "unknown"
const CONNECTION_ONLINE = "online"
const CONNECTION_OFFLINE = "offline"

class PrintTrayMenu extends Component {}
PrintTrayMenu.template = "webprint.PrintTrayMenu"

registry.category("systray").add("printer_systray", { Component: PrintTrayMenu, }, { sequence: 200, },)
