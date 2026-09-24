# //// Neoffice — added file (no upstream equivalent): push down to existing sites the wage types
# //// that must never be prorated by the days paid.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Advances and effective expenses are paid or recovered in full, whatever the days paid.

On 2026-09-24 a payslip compared with the certified engine's showed an advance of 500 (6510)
recovered as 322.60 on an entry month: the catalogue left 6510, 6520 and the effective expenses
6010, 6020 and 6030 depending on the days paid, so the framework prorated them like a salary.

Nothing reaches a site on its own: the Swiss Wage Type rows and the Salary Components made from
them are created once. The flag is pushed down to the wage type rows, to the components made from
them, and to the rows of the salary structures that carry those components. Prorating an amount
already paid or a cost actually incurred is never a client's choice, so no value is kept.
"""

import frappe

CODES = ("6010", "6020", "6030", "6510", "6520")


def execute():
	if not frappe.db.table_exists("Swiss Wage Type"):
		return

	for code in CODES:
		name = f"CH-WT-{code}"
		if frappe.db.exists("Swiss Wage Type", name):
			frappe.db.set_value("Swiss Wage Type", name, "depends_on_payment_days", 0, update_modified=False)

	if not frappe.db.has_column("Salary Component", "ch_wage_type_code"):
		return
	components = frappe.get_all(
		"Salary Component",
		filters={"ch_wage_type_code": ("in", CODES), "depends_on_payment_days": 1},
		pluck="name",
	)
	for component in components:
		frappe.db.set_value(
			"Salary Component", component, "depends_on_payment_days", 0, update_modified=False
		)
		print(f"Swiss payroll: '{component}' no longer prorated by the days paid")
	if components:
		frappe.db.sql(
			"""update `tabSalary Detail` set depends_on_payment_days = 0
			where parenttype = 'Salary Structure' and salary_component in %(components)s""",
			{"components": components},
		)
