import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Install the retroactive-correction audit fields.

	Employee.ch_qst_code_effective_from (HR sets it when a tariff change
	is reported late) and Salary Slip.ch_qst_tariff_code /
	ch_qst_correction_details (the code each slip was settled with — the
	audit trail corrections rely on — and the human-readable correction
	log of a run).
	"""
	from hrms.regional.switzerland.setup import get_custom_fields

	fields = get_custom_fields()
	targeted = {
		"Employee": [
			f
			for f in fields.get("Employee", [])
			if f.get("fieldname") in ("ch_qst_code_effective_from", "ch_qst_column_break")
		],
		"Salary Slip": fields.get("Salary Slip", []),
	}
	create_custom_fields({k: v for k, v in targeted.items() if v}, update=True)
