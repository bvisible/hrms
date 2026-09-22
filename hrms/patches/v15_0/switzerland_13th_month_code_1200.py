# //// Neoffice — added file (no upstream equivalent): repoint the 13th month component
# //// at the Swissdec standard wage type code.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Point the 13th month salary component at wage type 1200 instead of 1181.

1181 is one of our own variants. The Swissdec guidelines use **1200** for the
13th month — it appears as "1200 / 13. Monatslohn" in the ELM test examples,
whose Lohnartenstamm the guidelines declare authoritative for certification.
An ELM declaration built on 1181 therefore carried a code no recipient knows.

1180, 1181 and 1182 are kept: they describe HOW the 13th month is paid (as a
percentage, paid out, computed) and existing slips reference them. Only the
component that is declared moves.
"""

import frappe


def execute():
	from hrms.regional.switzerland.setup import create_swiss_wage_types

	# Idempotent; creates CH-WT-1200 if the site predates it.
	create_swiss_wage_types()

	if not frappe.db.exists("Swiss Wage Type", "CH-WT-1200"):
		frappe.log_error(
			"Swiss 13th month patch skipped",
			"CH-WT-1200 is missing after create_swiss_wage_types(); "
			"the 13th month component still points at CH-WT-1181.",
		)
		return

	components = frappe.get_all(
		"Salary Component",
		filters={"ch_wage_type": "CH-WT-1181"},
		pluck="name",
	)
	for name in components:
		frappe.db.set_value(
			"Salary Component",
			name,
			{"ch_wage_type": "CH-WT-1200", "ch_wage_type_code": "1200"},
			update_modified=False,
		)

	if components:
		frappe.db.commit()
		print(f"Swiss payroll: {len(components)} component(s) moved from wage type 1181 to 1200")
