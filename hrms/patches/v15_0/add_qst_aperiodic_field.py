import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Install Salary Slip.ch_qst_aperiodic (aperiodic share of the slip)."""
	from hrms.regional.switzerland.setup import get_custom_fields

	fields = get_custom_fields()
	targeted = [
		f
		for f in fields.get("Salary Slip", [])
		if f.get("fieldname") in ("ch_qst_aperiodic", "ch_qst_correction_details")
	]
	if targeted:
		create_custom_fields({"Salary Slip": targeted}, update=True)

	# The aperiodic detection reads the wage type's statistical category:
	# link the hook-created 13th month component to its catalog entry
	# (SMS) where the link is missing.
	if frappe.db.exists("Salary Component", "13th Month Salary") and frappe.db.exists(
		"Swiss Wage Type", "CH-WT-1181"
	):
		if not frappe.db.get_value("Salary Component", "13th Month Salary", "ch_wage_type"):
			frappe.db.set_value(
				"Salary Component", "13th Month Salary", "ch_wage_type", "CH-WT-1181"
			)
