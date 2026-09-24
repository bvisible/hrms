# //// Neoffice — added file (no upstream equivalent): every Swiss payroll patch on a site that
# //// never had the Swiss payroll's columns (neoffice-maintenance#722).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Every Swiss payroll patch runs on a site that never had the Swiss payroll's columns.

hooks.after_migrate creates the Swiss custom fields on every site, but after the patches: the first
migrate of such a site runs them while Salary Component.ch_wage_type_code and the other Swiss
columns do not exist yet. One patch that read them aborted `bench migrate` on a canary
instance without the Swiss payroll (2026-09-24, neoffice-maintenance#722).

Each Swiss patch of patches.txt runs here as it would there: the Swiss columns of the standard
DocTypes reported missing, their creation skipped, and any query that names one of them refused.
Schema changes are skipped too (MariaDB would commit the test's transaction on them), commits are
disarmed, and everything is rolled back.
"""

import importlib
import re
from contextlib import ExitStack
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import setup

SCHEMA_CHANGE = re.compile(r"\s*(alter|create|drop|rename|truncate)\b", re.I)


def swiss_patches():
	"""The Swiss entries of patches.txt: its Swiss section, and any entry named after Switzerland."""
	entries, in_swiss = [], False
	with open(frappe.get_app_path("hrms", "patches.txt"), encoding="utf-8") as f:
		for line in f:
			line = line.strip()
			if line.startswith("#"):
				in_swiss = in_swiss or "Swiss payroll patches" in line
				continue
			if not line or line.startswith("["):
				continue
			module = line.split()[0]
			if (in_swiss or "swiss" in module) and module not in entries:
				entries.append(module)
	return entries


def swiss_columns():
	return {
		doctype: {f["fieldname"] for f in fields if f.get("fieldname")}
		for doctype, fields in setup.get_custom_fields().items()
	}


def without_swiss_columns(module):
	"""A context in which ``module`` runs as on a site whose Swiss columns do not exist yet."""
	columns = swiss_columns()
	real_sql, real_has_column = frappe.db.sql, frappe.db.has_column

	def has_column(doctype, column):
		return False if column in columns.get(doctype, ()) else real_has_column(doctype, column)

	def sql(query, *args, **kwargs):
		text = str(query)
		if SCHEMA_CHANGE.match(text):
			return ()
		for doctype, names in columns.items():
			if f"`tab{doctype}`" not in text:
				continue
			for name in names:
				if re.search(rf"\b{re.escape(name)}\b", text):
					raise AssertionError(
						f"{module.__name__} reads {doctype}.{name}, which does not exist before "
						"after_migrate creates the Swiss custom fields"
					)
		return real_sql(query, *args, **kwargs)

	stack = ExitStack()
	stack.enter_context(patch.object(frappe.db, "has_column", has_column))
	stack.enter_context(patch.object(frappe.db, "sql", sql))
	stack.enter_context(patch.object(frappe.db, "sql_ddl", lambda *a, **k: None))
	stack.enter_context(patch.object(frappe.db, "commit", lambda *a, **k: None))
	stack.enter_context(patch.object(setup, "make_custom_fields", lambda *a, **k: None))
	if hasattr(module, "create_custom_fields"):
		stack.enter_context(patch.object(module, "create_custom_fields", lambda *a, **k: None))
	return stack


class TestSwissPatchesBeforeTheSwissColumns(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_the_swiss_patches_are_all_found(self):
		patches = swiss_patches()
		self.assertIn("hrms.patches.v15_0.switzerland_sync_component_catalogue", patches)
		self.assertIn("hrms.patches.v15_0.rename_swiss_qst_tariff_type", patches)
		self.assertGreaterEqual(len(patches), 20)

	def test_the_guard_refuses_a_query_on_a_missing_column(self):
		# The simulation itself: an unguarded read of a Swiss column fails as it did on the canary.
		module = importlib.import_module("hrms.regional.switzerland.patch_utils")
		with without_swiss_columns(module), self.assertRaises(AssertionError):
			frappe.get_all("Salary Component", filters={"ch_wage_type_code": "1200"})

	def test_every_swiss_patch_runs_before_the_swiss_columns_exist(self):
		for name in swiss_patches():
			module = importlib.import_module(name)
			with self.subTest(patch=name), without_swiss_columns(module):
				module.execute()
			frappe.db.rollback()


class TestSwissPatchesWithTheSwissPayroll(FrappeTestCase):
	"""The guards leave a site that has the Swiss columns to the patches' work."""

	def tearDown(self):
		frappe.db.rollback()

	def setUp(self):
		if not frappe.db.has_column("Salary Component", "ch_wage_type_code"):
			self.skipTest("the Swiss custom fields are not installed on this site")

	def test_every_swiss_patch_runs_with_the_swiss_columns(self):
		for name in swiss_patches():
			module = importlib.import_module(name)
			with self.subTest(patch=name), ExitStack() as stack:
				real_sql = frappe.db.sql
				stack.enter_context(
					patch.object(
						frappe.db,
						"sql",
						lambda q, *a, **k: () if SCHEMA_CHANGE.match(str(q)) else real_sql(q, *a, **k),
					)
				)
				stack.enter_context(patch.object(frappe.db, "sql_ddl", lambda *a, **k: None))
				stack.enter_context(patch.object(frappe.db, "commit", lambda *a, **k: None))
				module.execute()
			frappe.db.rollback()

	def test_a_component_still_gets_its_corrected_position(self):
		from hrms.patches.v15_0 import switzerland_sync_component_catalogue

		component = frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": "_Test Swiss Family Allowance #722",
				"salary_component_abbr": "_TSFA722",
				"type": "Earning",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"Salary Component", component.name, {"ch_wage_type_code": "3000", "ch_lohnausweis_position": "7"}
		)
		with patch.object(frappe.db, "commit", lambda *a, **k: None):
			switzerland_sync_component_catalogue.execute()
		self.assertEqual(
			frappe.db.get_value("Salary Component", component.name, "ch_lohnausweis_position"), "1"
		)
