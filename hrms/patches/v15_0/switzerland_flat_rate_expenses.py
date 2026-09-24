# //// Neoffice — added file (no upstream equivalent): push down to existing sites the flat-rate
# //// expense wage types that follow the expense regulation, not the days paid.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Flat-rate allowances 6050, 6060 and 6070 no longer depend on the days paid; 6060 is exempt.

The days paid cut a flat allowance from the first unpaid day and by working days, while the
company's expense regulation keeps it for four weeks of absence (expenses.py computes it from its
full amount). 6040 was already exempt of the days paid. And 6060, flat expenses of expatriates,
was subject to every insurance: Swissdec 6.0 lists every expense of 6000-6070 with all its
columns at 0.

As for the earlier unprorated wage types, the flags are pushed down to the wage type rows, to the
components made from them and to the rows of the salary structures that carry them.
"""

import frappe

CODES = ("6050", "6060", "6070")
EXEMPT_CODES = ("6060",)
INSURANCES = ("avs", "ac", "laa", "ijm", "lpp", "imp")


def execute():
	if not frappe.db.table_exists("Swiss Wage Type"):
		return

	for code in CODES:
		name = f"CH-WT-{code}"
		if not frappe.db.exists("Swiss Wage Type", name):
			continue
		values = {"depends_on_payment_days": 0}
		if code in EXEMPT_CODES:
			values.update({f"subject_to_{insurance}": 0 for insurance in INSURANCES})
		frappe.db.set_value("Swiss Wage Type", name, values, update_modified=False)

	if not frappe.db.has_column("Salary Component", "ch_wage_type_code"):
		return
	components = frappe.get_all(
		"Salary Component",
		filters={"ch_wage_type_code": ("in", CODES)},
		fields=["name", "ch_wage_type_code"],
	)
	for component in components:
		values = {"depends_on_payment_days": 0}
		if component.ch_wage_type_code in EXEMPT_CODES:
			values.update(
				{
					f"ch_subject_to_{insurance}": 0
					for insurance in INSURANCES
					if frappe.db.has_column("Salary Component", f"ch_subject_to_{insurance}")
				}
			)
		frappe.db.set_value("Salary Component", component.name, values, update_modified=False)
		print(f"Swiss payroll: '{component.name}' follows the expense regulation, not the days paid")
	if components:
		frappe.db.sql(
			"""update `tabSalary Detail` set depends_on_payment_days = 0
			where parenttype = 'Salary Structure' and salary_component in %(components)s""",
			{"components": [c.name for c in components]},
		)
