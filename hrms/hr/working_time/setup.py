# //// Neoffice — added file (no upstream equivalent): the Employee fields of the working-time engine,
# //// made idempotently at each migration (lot T, neoffice-maintenance#2623).
"""The Employee fields of the working time: the labour agreement the person is tied to, whether the time to
compensate the hours over was extended in writing for them, and the hours a week of their contract. Custom Fields, like the Swiss ones: nothing is
written into the upstream Employee JSON."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hrms.hr.working_time.agreement import CONTRACT_HOURS_FIELD, DOCTYPE, EMPLOYEE_FIELD, EXTENSION_FIELD


def after_migrate():
	if not frappe.db.exists("DocType", DOCTYPE):
		return
	employee = frappe.get_meta("Employee")
	anchor = "ch_work_percentage" if employee.has_field("ch_work_percentage") else "department"
	create_custom_fields(
		{
			"Employee": [
				{
					"fieldname": EMPLOYEE_FIELD,
					"label": "Labour Agreement",
					"fieldtype": "Link",
					"options": DOCTYPE,
					"insert_after": anchor,
					"description": "The agreement whose confirmed rules count this person's working time.",
				},
				{
					"fieldname": EXTENSION_FIELD,
					"label": "Time to Compensate Extended in Writing",
					"fieldtype": "Check",
					"insert_after": EMPLOYEE_FIELD,
					"depends_on": f"eval:doc.{EMPLOYEE_FIELD}",
					"description": "Agreed in writing with this person: the agreement's longer time to compensate the hours over applies.",
				},
				{
					"fieldname": CONTRACT_HOURS_FIELD,
					"label": "Hours a Week of the Contract",
					"fieldtype": "Float",
					"insert_after": EXTENSION_FIELD,
					"non_negative": 1,
					"depends_on": f"eval:doc.{EMPLOYEE_FIELD}",
					"description": "The hours due when the agreement draws them from the contract (the law alone, for instance).",
				},
			]
		},
		update=True,
	)
