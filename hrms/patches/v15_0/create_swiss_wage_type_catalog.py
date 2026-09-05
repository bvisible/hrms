# //// Neoffice — added file (no upstream equivalent): populates the Swiss Wage Type catalog
# //// (~170 Swissdec standard codes) from wage_type_data.py on existing sites.
import frappe


def execute():
	"""Create Swiss Wage Type catalog entries from the standard reference data.

	This patch populates the Swiss Wage Type DocType with ~170 standard wage type
	codes as defined by the Swissdec standard reference.
	"""
	if not frappe.db.table_exists("Swiss Wage Type"):
		return

	from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types

	wage_types = get_swiss_wage_types()
	for wt in wage_types:
		name = f"CH-WT-{wt['code']}"
		if not frappe.db.exists("Swiss Wage Type", name):
			doc = frappe.new_doc("Swiss Wage Type")
			doc.update(wt)
			doc.insert(ignore_permissions=True)

	frappe.db.commit()
