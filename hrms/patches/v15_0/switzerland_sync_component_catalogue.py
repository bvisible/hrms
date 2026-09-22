# //// Neoffice — added file (no upstream equivalent): resynchronise Swiss salary components
# //// with the wage type catalogue.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Push catalogue corrections down onto the salary components of existing sites.

`create_swiss_salary_components()` only ever creates what is missing. A site
therefore keeps forever the salary-certificate position its components were
given the day it was provisioned, and a catalogue correction never reaches it.

The 2026 ESTV guide ("Wegleitung zum Ausfüllen des Lohnausweises") puts under
Ziffer 1 the daily allowances an employer pays out (sickness, accident,
invalidity) and every family allowance — we had several of them at 7 or 3. Left
alone, those sites keep issuing salary certificates that put taxable salary in
the wrong box.

Only the salary-certificate position is synchronised here, and only where the
component still carries the value the catalogue used to hold: a position edited
deliberately on a client site is left alone.
"""

import frappe

# code -> (position the catalogue used to hold, position it holds now)
POSITION_FIXES = {
	"2025": ("7", "1"),
	"2030": ("7", "1"),
	"2035": ("7", "1"),
	"3000": ("7", "1"),
	"3010": ("7", "1"),
	"3030": ("7", "1"),
	"3031": ("7", "1"),
	"3032": ("3", "1"),
	"3033": ("3", "1"),
	"3034": ("7", "1"),
}


def execute():
	moved = 0
	for code, (old_position, new_position) in POSITION_FIXES.items():
		components = frappe.get_all(
			"Salary Component",
			filters={"ch_wage_type_code": code, "ch_lohnausweis_position": old_position},
			pluck="name",
		)
		for name in components:
			frappe.db.set_value(
				"Salary Component", name, "ch_lohnausweis_position", new_position,
				update_modified=False,
			)
			moved += 1
			print(f"Swiss payroll: '{name}' ({code}) salary certificate {old_position} -> {new_position}")
	if moved:
		frappe.db.commit()
		print(f"Swiss payroll: {moved} salary certificate position(s) corrected")
