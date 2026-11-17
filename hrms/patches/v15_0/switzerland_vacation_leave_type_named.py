# //// Neoffice — added file (no upstream equivalent): the vacation leave type marked in HR Settings, then named in the
# //// site's language where it still carries the install's name (« Congé de privilège » becomes « Vacances » on a
# //// French site), never over a name the company chose nor beside a type already called so (neoffice-maintenance#2793).
import frappe


def execute():
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	from hrms.regional.switzerland.setup import name_vacation_leave_type, vacation_field

	# the field comes with the Swiss fields at after_migrate, which runs after the patches: made here first
	create_custom_fields({"HR Settings": [vacation_field()]}, update=True)
	frappe.clear_cache(doctype="HR Settings")
	name_vacation_leave_type()
