# //// Neoffice — added file (no upstream equivalent): push the wage type catalogue checked against
# //// the Swissdec guidelines 6.0 down onto existing sites.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Bring existing sites to the wage type catalogue checked against the Swissdec guidelines 6.0.

On 2026-09-23 the catalogue was compared line by line with the sample wage type table of the
guidelines (6.0, 5.2.1) and their worked examples (8.7.2). The daily allowances of the APG,
maternity, military and invalidity insurance were not subject to IJM; vacation paid out was
exempt from everything; 1976 and 1978 carried each other's meaning; the corrections of a daily
allowance (2050) and of short-time work (2060) were deductions that left the gross and every
base untouched; tips (1920) and the short-time work loss (2065) were paid earnings.

Nothing reaches a site on its own: the Swiss Wage Type rows and the Salary Components made
from them are created once. Each corrected code is pushed down to both:

* the Swiss Wage Type row takes the catalogue values — it is reference data;
* a Salary Component takes the new subject flags only where it still holds the old ones, and
  the new certificate position only where it still holds the old one: a value set deliberately
  on a client site is left alone;
* a component changes nature — a deduction becoming a negative earning, a paid earning becoming
  one that only raises the bases — only if no slip and no structure ever used it. One that did
  is left as it is and named in the log: converting it would change what past periods meant,
  or stop paying something a client pays through the payroll.
"""

import frappe

from hrms.regional.switzerland.patch_utils import has_swiss_columns
from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types

FLAG_FIELDS = ("avs", "ac", "laa", "ijm", "lpp", "imp")

# code -> (type, certificate position, subject flags avs/ac/laa/ijm/lpp/imp) the catalogue held
# before 2026-09-23. A component still holding these was never adjusted by hand.
OLD_CATALOGUE = {
	"1165": ("Earning", "1", (0, 0, 0, 0, 0, 0)),
	"1401": ("Earning", "3", (1, 1, 0, 0, 0, 1)),
	"1920": ("Earning", "1", (1, 1, 1, 1, 1, 1)),
	"1976": ("Earning", "7", (1, 1, 1, 1, 1, 1)),
	"1978": ("Earning", "7", (1, 1, 1, 1, 1, 1)),
	"1980": ("Earning", "13.2.3", (0, 0, 0, 0, 0, 0)),
	"2000": ("Earning", "7", (1, 1, 0, 0, 0, 1)),
	"2020": ("Earning", "7", (0, 0, 0, 0, 0, 1)),
	"2021": ("Earning", "7", (0, 0, 0, 0, 0, 1)),
	"2025": ("Earning", "1", (1, 1, 0, 0, 0, 1)),
	"2026": ("Earning", "7", (0, 0, 0, 0, 0, 1)),
	"2031": ("Earning", "7", (0, 0, 0, 0, 0, 1)),
	"2040": ("Earning", "7", (1, 1, 0, 0, 0, 1)),
	"2050": ("Deduction", "", (1, 1, 1, 0, 0, 1)),
	"2060": ("Deduction", "", (0, 0, 0, 0, 0, 1)),
	"2065": ("Earning", "", (1, 1, 1, 0, 1, 0)),
	"2075": ("Earning", "", (0, 0, 0, 0, 0, 1)),
}

WAGE_TYPE_FIELDS = (
	"wage_type_name",
	"type",
	"lohnausweis_position",
	"do_not_include_in_total",
	"is_negative",
	"bases_only",
	*(f"subject_to_{f}" for f in FLAG_FIELDS),
)


def execute():
	if not frappe.db.table_exists("Swiss Wage Type"):
		return

	from hrms.regional.switzerland.setup import create_swiss_wage_types, make_custom_fields

	# The Salary Component columns this patch writes are created by make_custom_fields, which
	# otherwise only runs after the patches (after_migrate). Both calls are idempotent.
	make_custom_fields()
	create_swiss_wage_types()  # 1979 is new

	catalogue = {wt["code"]: wt for wt in get_swiss_wage_types()}
	for code in OLD_CATALOGUE:
		entry = catalogue[code]
		name = f"CH-WT-{code}"
		if frappe.db.exists("Swiss Wage Type", name):
			frappe.db.set_value(
				"Swiss Wage Type",
				name,
				{field: entry.get(field, 0) for field in WAGE_TYPE_FIELDS},
				update_modified=False,
			)
		if not has_swiss_columns("Salary Component", "ch_wage_type_code", "ch_lohnausweis_position"):
			continue  # created by make_custom_fields above; checked all the same (#722)
		for component in frappe.get_all(
			"Salary Component", filters={"ch_wage_type_code": code}, pluck="name"
		):
			_sync_component(component, code, entry)

	frappe.db.commit()


def _sync_component(component, code, entry):
	old_type, old_position, old_flags = OLD_CATALOGUE[code]
	current = frappe.db.get_value(
		"Salary Component",
		component,
		["type", "ch_lohnausweis_position", *(f"ch_subject_to_{f}" for f in FLAG_FIELDS)],
		as_dict=True,
	)
	updates = {}

	flags_untouched = tuple(int(current.get(f"ch_subject_to_{f}") or 0) for f in FLAG_FIELDS) == old_flags
	if flags_untouched:
		updates.update({f"ch_subject_to_{f}": entry[f"subject_to_{f}"] for f in FLAG_FIELDS})

	new_position = entry["lohnausweis_position"]
	if (current.ch_lohnausweis_position or "") == old_position and new_position != old_position:
		updates["ch_lohnausweis_position"] = new_position

	changes_nature = entry["type"] != old_type or entry["is_negative"] or entry["bases_only"]
	if changes_nature and flags_untouched and current.type == old_type:
		if _ever_used(component):
			print(
				f"Swiss payroll: '{component}' ({code}) left as a {current.type}: it is already used on "
				f"slips or structures. Create a new component from wage type {code} for the next periods."
			)
		else:
			updates["type"] = entry["type"]
			updates["ch_negative_wage_type"] = entry["is_negative"]
			updates["ch_bases_only"] = entry["bases_only"]
			if entry["bases_only"]:
				updates["do_not_include_in_total"] = 1

	if updates:
		frappe.db.set_value("Salary Component", component, updates, update_modified=False)
		print(
			f"Swiss payroll: '{component}' ({code}) aligned on the Swissdec 6.0 catalogue: {sorted(updates)}"
		)


def _ever_used(component):
	return bool(frappe.db.exists("Salary Detail", {"salary_component": component}))
