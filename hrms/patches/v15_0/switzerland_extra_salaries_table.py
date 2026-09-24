# //// Neoffice — added file (no upstream equivalent): carry the legacy 13th month setting into the
# //// extra salaries table of the Swiss Social Insurance Config.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""The 13th month mode becomes a row of the extra salaries table (13th, 14th, 15th).

The payroll reads the table and falls back on the legacy mode while it is empty, so nothing changes
for a site that is not migrated; written here, the choice shows where the company payroll setup
and the form now edit it. A configuration whose table already has rows is left as it is.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Swiss Extra Salary") or not frappe.db.has_column(
		"Swiss Social Insurance Config", "thirteenth_month_mode"
	):
		return
	for config in frappe.get_all("Swiss Social Insurance Config", fields=["name", "thirteenth_month_mode"]):
		if config.thirteenth_month_mode not in ("Annual", "Monthly"):
			continue
		if frappe.db.exists("Swiss Extra Salary", {"parent": config.name}):
			continue
		frappe.get_doc(
			{
				"doctype": "Swiss Extra Salary",
				"parent": config.name,
				"parenttype": "Swiss Social Insurance Config",
				"parentfield": "extra_salaries",
				"idx": 1,
				"extra_salary": "13th",
				"percent": 100,
				"schedule": config.thirteenth_month_mode,
				"payment_month": 12,
			}
		).db_insert()
		print(
			f"Swiss payroll: {config.name} — 13th month ({config.thirteenth_month_mode}) in the extra salaries"
		)
