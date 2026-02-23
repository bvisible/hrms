# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _


@frappe.whitelist()
def create_salary_component_from_wage_type(wage_type_code, company=None):
	"""Create a Salary Component from a Swiss Wage Type catalog entry.

	Args:
		wage_type_code: The Swiss Wage Type code (e.g., "1000").
		company: Optional company name for GL account setup.

	Returns:
		The name of the newly created Salary Component.
	"""
	wt_name = f"CH-WT-{wage_type_code}"
	if not frappe.db.exists("Swiss Wage Type", wt_name):
		frappe.throw(_("Swiss Wage Type {0} not found").format(wage_type_code))

	wt = frappe.get_doc("Swiss Wage Type", wt_name)

	# Generate a component name from the wage type
	component_name = wt.wage_type_name
	if frappe.db.exists("Salary Component", component_name):
		frappe.throw(
			_("Salary Component '{0}' already exists. Link it to Swiss Wage Type {1} manually.").format(
				component_name, wage_type_code
			)
		)

	# Generate abbreviation from code
	abbr = f"CH{wage_type_code}"

	comp_type = wt.type if wt.type in ("Earning", "Deduction") else "Earning"

	doc = frappe.new_doc("Salary Component")
	doc.salary_component = component_name
	doc.salary_component_abbr = abbr
	doc.type = comp_type
	doc.description = f"{wt.wage_type_name} (Code {wage_type_code})"
	doc.depends_on_payment_days = 1
	doc.remove_if_zero_valued = 1

	# Set Swiss-specific fields
	doc.ch_wage_type = wt_name
	doc.ch_wage_type_code = wage_type_code
	doc.ch_subject_to_avs = wt.subject_to_avs
	doc.ch_subject_to_ac = wt.subject_to_ac
	doc.ch_subject_to_laa = wt.subject_to_laa
	doc.ch_subject_to_ijm = wt.subject_to_ijm
	doc.ch_subject_to_lpp = wt.subject_to_lpp
	doc.ch_subject_to_imp = wt.subject_to_imp
	if wt.lohnausweis_position:
		doc.ch_lohnausweis_position = wt.lohnausweis_position

	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	return doc.name
