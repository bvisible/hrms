import json
import os

import frappe


def execute():
	"""Install the Swiss Payroll workspace and the HR sidebar hierarchy.

	The workspace sync skips records whose DB copy was edited after the
	JSON was authored, so consolidated fleets never pick the new
	workspace or the parent_page moves up — import/repair explicitly.
	"""
	path = frappe.get_app_path("hrms", "payroll", "workspace", "swiss_payroll", "swiss_payroll.json")
	if os.path.exists(path):
		with open(path) as f:
			data = json.load(f)
		if frappe.db.exists("Workspace", "Swiss Payroll"):
			doc = frappe.get_doc("Workspace", "Swiss Payroll")
			doc.update(
				{k: v for k, v in data.items() if k not in ("name", "creation", "modified", "modified_by", "owner", "doctype")}
			)
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc(data).insert(ignore_permissions=True)

	# Sidebar hierarchy: ONE root (HR), Swiss Payroll nested right under it,
	# generic Payroll under Swiss Payroll, secondary HR workspaces under HR.
	moves = {
		"HR": ("", 29),
		"Swiss Payroll": ("HR", 30),
		"Payroll": ("Swiss Payroll", 31),
		"Leaves and Attendance": ("HR", 32),
		"Expense Claims": ("HR", 33),
		"Recruitment & Performance": ("HR", 34),
		"Training": ("HR", 35),
		"HR Reports": ("HR", 36),
	}
	for name, (parent, sequence) in moves.items():
		if frappe.db.exists("Workspace", name):
			frappe.db.set_value(
				"Workspace", name, {"parent_page": parent, "sequence_id": sequence}, update_modified=False
			)
