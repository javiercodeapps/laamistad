"""The read tools refuse a restricted field in a domain, an order or a group.

Odoo 16 core checks the field groups only on the fields it reads.
``search_records`` and ``aggregate_records`` check the other field names too,
so a filter, a sort or a group cannot reveal the values of a field that the
user cannot read.
"""

import time
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import common, tagged

from .test_helpers import create_test_user


@tagged("much_unit", "post_install", "-at_install")
class TestFieldGroupsGuard(common.TransactionCase):
    """Restricted fields in domains, orders, groupby and aggregate specs."""

    def setUp(self):
        super().setUp()
        partner_model = self.env.ref("base.model_res_partner")
        enabled = self.env["mcp.enabled.model"].search(
            [("model_id", "=", partner_model.id)], limit=1
        )
        if enabled:
            enabled.write({"allow_read": True, "active": True})
        else:
            self.env["mcp.enabled.model"].create(
                {"model_id": partner_model.id, "allow_read": True}
            )
        patcher = patch(
            "odoo.addons.mcp_server.controllers.utils.is_mcp_enabled",
            return_value=True,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # Restrict three stock fields to Settings for this test only.
        for model, fname in (
            ("res.partner", "ref"),
            ("res.partner", "color"),
            ("res.country", "code"),
        ):
            self.patch(self.env[model]._fields[fname], "groups", "base.group_system")

        unique_id = str(int(time.time() * 1000))[-6:]
        self.user = create_test_user(
            self.env, "Field Guard User", f"field_guard_{unique_id}"
        )
        self.admin = self.env.ref("base.user_admin")
        self.partner = self.env["res.partner"].create(
            {
                "name": f"Field Guard Co {unique_id}",
                "ref": "FG-1",
                "color": 3,
                "country_id": self.env.ref("base.de").id,
            }
        )

    def _tools(self, user):
        return self.env["mcp.mixin"].with_user(user)

    def _search(self, user, domain, order=None):
        return self._tools(user).search_records(
            "res.partner",
            [["id", "=", self.partner.id], *domain],
            ["name"],
            order=order,
        )

    def _aggregate(self, user, groupby, aggregates=None, order=None):
        return self._tools(user).aggregate_records(
            "res.partner",
            groupby,
            aggregates=aggregates,
            domain=[["id", "=", self.partner.id]],
            order=order,
        )

    def _assert_refused(self, call, field, model):
        with self.assertRaises(AccessError) as caught:
            call(self.user)
        # Core words the message in two forms (with or without the
        # technical-features group); both name the field, model and operation.
        message = str(caught.exception)
        self.assertRegex(message, rf"\b{field}\b")
        self.assertIn(f"({model})", message)
        self.assertIn("Operation: read", message)

    def _ids(self, result):
        return [row["id"] for row in result["structuredContent"]["records"]]

    def test_domain_on_restricted_field(self):
        def call(user):
            return self._search(user, [["ref", "=", "FG-1"]])

        self._assert_refused(call, "ref", "res.partner")
        self.assertEqual(self._ids(call(self.admin)), [self.partner.id])

    def test_domain_dotted_path_checks_the_comodel(self):
        def call(user):
            return self._search(user, [["country_id.code", "=", "DE"]])

        self._assert_refused(call, "code", "res.country")
        self.assertEqual(self._ids(call(self.admin)), [self.partner.id])

    def test_order_on_restricted_field(self):
        def call(user):
            return self._search(user, [], order="name, ref desc")

        self._assert_refused(call, "ref", "res.partner")
        self.assertEqual(self._ids(call(self.admin)), [self.partner.id])

    def test_groupby_on_restricted_field(self):
        def call(user):
            return self._aggregate(user, ["ref"])

        self._assert_refused(call, "ref", "res.partner")
        groups = call(self.admin)["structuredContent"]["groups"]
        self.assertEqual([group["ref"] for group in groups], ["FG-1"])

    def test_aggregate_on_restricted_field(self):
        def call(user):
            return self._aggregate(user, ["country_id"], ["color:sum"])

        self._assert_refused(call, "color", "res.partner")
        groups = call(self.admin)["structuredContent"]["groups"]
        self.assertEqual([group["color:sum"] for group in groups], [3])

    def test_order_by_restricted_aggregate(self):
        def call(user):
            return self._aggregate(user, ["country_id"], order="color:sum desc")

        self._assert_refused(call, "color", "res.partner")
        groups = call(self.admin)["structuredContent"]["groups"]
        self.assertEqual([group["__count"] for group in groups], [1])

    def test_aggregate_function_cannot_name_another_field(self):
        # 16 read_group would aggregate the field in the parentheses.
        for kwargs in (
            {"aggregates": ["name:sum(color)"]},
            {"order": "name:max(color) desc"},
        ):
            for user in (self.user, self.admin):
                with self.subTest(user=user.login, **kwargs), self.assertRaisesRegex(
                    UserError, "must have the form 'field:function'"
                ):
                    self._aggregate(user, ["country_id"], **kwargs)

    def test_aggregate_spec_must_name_a_field(self):
        # 16 read_group reads 'color)' as 'color', past the field-groups check.
        for kwargs in (
            {"aggregates": ["color):sum"]},
            {"aggregates": ["color)x:max"]},
            {"order": "color):max desc"},
        ):
            for user in (self.user, self.admin):
                with self.subTest(user=user.login, **kwargs), self.assertRaisesRegex(
                    UserError, "is not a field"
                ):
                    self._aggregate(user, ["country_id"], **kwargs)

    def test_unrestricted_fields_pass_unchanged(self):
        result = self._search(
            self.user, [["country_id.name", "=", "Germany"]], order="name desc"
        )
        self.assertEqual(self._ids(result), [self.partner.id])
        groups = self._aggregate(
            self.user, ["country_id"], ["id:count"], order="country_id"
        )["structuredContent"]["groups"]
        self.assertEqual([group["id:count"] for group in groups], [1])
        self.assertEqual(groups[0]["country_id"][0], self.env.ref("base.de").id, groups)
