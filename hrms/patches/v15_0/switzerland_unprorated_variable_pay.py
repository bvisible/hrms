# //// Neoffice — added file (no upstream equivalent): push down to existing sites the wage types of
# //// variable pay that must never be prorated by the days paid.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""A commission (1218) and a tip (1920) are paid in full, whatever the days paid.

The catalogue left both depending on the days paid, so the framework prorated a commission earned in a month by the
days the employee was paid in it: 600 earned, 300 paid on an entry month. Same shape as
``switzerland_unprorated_advances_and_expenses``: the flag is pushed down to the Swiss Wage Type rows, to the Salary
Components made from them and to the rows of the salary structures that carry those components. Prorating an amount
already earned is never a client's choice, so no value is kept.
"""

import frappe

CODES = ("1218", "1920")


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
