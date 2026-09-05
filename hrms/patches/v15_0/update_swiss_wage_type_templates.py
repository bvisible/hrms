# //// Neoffice — added file (no upstream equivalent): refreshes the Swiss Wage Type rows with the
# //// template fields (abbreviation, formula, ...) added after the first catalog import.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe

from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types


def execute():
	"""Update Swiss Wage Types with template fields (abbreviation, formula, etc.)."""
	if not frappe.db.exists("DocType", "Swiss Wage Type"):
		return

	wage_types = get_swiss_wage_types()
	template_fields = [
		"abbreviation", "description_fr", "is_employer_contribution",
		"linked_wage_type_code", "depends_on_payment_days",
		"amount_based_on_formula", "formula", "condition",
		"default_amount", "do_not_include_in_total",
	]

	for wt_data in wage_types:
		wt_name = f"CH-WT-{wt_data['code']}"
		if not frappe.db.exists("Swiss Wage Type", wt_name):
			# New wage type (e.g., 5011, 5023, 5024, 5030) — create it
			doc = frappe.new_doc("Swiss Wage Type")
			for key, value in wt_data.items():
				if hasattr(doc, key):
					setattr(doc, key, value)
			doc.insert(ignore_permissions=True)
			continue

		# Existing wage type — update template fields only
		updates = {}
		for field in template_fields:
			if field in wt_data:
				updates[field] = wt_data[field]

		if updates:
			frappe.db.set_value("Swiss Wage Type", wt_name, updates, update_modified=False)

	frappe.db.commit()
