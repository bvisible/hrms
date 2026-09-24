# //// Neoffice — added file (no upstream equivalent): repoint the 13th month component
# //// at the Swissdec standard wage type code.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Point the 13th month salary component at wage type 1200.

The Swissdec guidelines declare the 13th month under **1200** — it appears as
"1200 / 13. Monatslohn" in the ELM test examples, whose Lohnartenstamm the
guidelines declare authoritative for certification.

Sites carry different wrong codes depending on when they were provisioned:
1181 (one of our own variants) on recent ones, and **1050 on older ones — which
is the code of the HOUSING ALLOWANCE**. A declaration built on either carries a
code that either means nothing to the recipient or, worse, means something else.

So the component is matched by identity, not by its current code: a Salary
Component created by the Swiss setup is never renamed, while its wage type code
is exactly the thing that is wrong.

1180, 1181 and 1182 stay in the catalogue: they describe HOW the 13th month is
paid (as a percentage, paid out, computed) and existing records reference them.
"""

import frappe

from hrms.regional.switzerland.patch_utils import has_swiss_columns

COMPONENT_NAME = "13th Month Salary"
TARGET_CODE = "1200"
TARGET_WAGE_TYPE = "CH-WT-1200"


def execute():
	from hrms.regional.switzerland.setup import create_swiss_wage_types

	# Idempotent; creates CH-WT-1200 on a site that predates it.
	create_swiss_wage_types()

	if not frappe.db.exists("Swiss Wage Type", TARGET_WAGE_TYPE):
		frappe.log_error(
			"Swiss 13th month patch skipped",
			f"{TARGET_WAGE_TYPE} is missing after create_swiss_wage_types(); "
			"the 13th month component keeps its current wage type.",
		)
		return

	if not frappe.db.exists("Salary Component", COMPONENT_NAME):
		return
	# A component of that name on a site whose Swiss columns do not exist yet (#722).
	if not has_swiss_columns("Salary Component", "ch_wage_type", "ch_wage_type_code"):
		return

	current = frappe.db.get_value(
		"Salary Component", COMPONENT_NAME, ["ch_wage_type", "ch_wage_type_code"], as_dict=True
	)
	if current and current.ch_wage_type_code == TARGET_CODE:
		return

	frappe.db.set_value(
		"Salary Component",
		COMPONENT_NAME,
		{"ch_wage_type": TARGET_WAGE_TYPE, "ch_wage_type_code": TARGET_CODE},
		update_modified=False,
	)
	frappe.db.commit()
	print(
		f"Swiss payroll: '{COMPONENT_NAME}' moved from wage type "
		f"{current.ch_wage_type_code or '(none)'} to {TARGET_CODE}"
	)
