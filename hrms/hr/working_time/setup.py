# //// Neoffice — added file (no upstream equivalent): the Employee fields of the working-time engine,
# //// made idempotently at each migration (lot T, neoffice-maintenance#2623).
"""The Employee fields of the working time: the labour agreement the person is tied to, whether the time to
compensate the hours over was extended in writing for them, and the hours a week of their contract. Custom Fields, like the Swiss ones: nothing is
written into the upstream Employee JSON.

For the minimum wage (minimum.py): the person's category and start of professional experience as the agreement's
table reads them, their zone, the canton they work in, whether a reduction of the minimum was agreed with them; and
on a Salary Component, whether it counts toward the minimum."""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hrms.hr.working_time.agreement import CONTRACT_HOURS_FIELD, DOCTYPE, EMPLOYEE_FIELD, EXTENSION_FIELD
from hrms.hr.working_time.minimum import (
	CANTON_FIELD,
	CATEGORY_FIELD,
	COUNTS_FIELD,
	EXPERIENCE_FIELD,
	REDUCTION_FIELD,
	ZONE_FIELD,
)

CANTONS = "\n".join(
	["", *"AG AI AR BE BL BS FR GE GL GR JU LU NE NW OW SG SH SO SZ TG TI UR VD VS ZG ZH".split()]
)


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
				{
					"fieldname": CATEGORY_FIELD,
					"label": "Category for the Minimum Wage",
					"fieldtype": "Data",
					"insert_after": CONTRACT_HOURS_FIELD,
					"depends_on": f"eval:doc.{EMPLOYEE_FIELD}",
					"description": "As the agreement's table of minimum wages names it.",
				},
				{
					"fieldname": EXPERIENCE_FIELD,
					"label": "Professional Experience Since",
					"fieldtype": "Date",
					"insert_after": CATEGORY_FIELD,
					"depends_on": f"eval:doc.{EMPLOYEE_FIELD}",
					"description": "The day the years of experience the minimum wage counts begin.",
				},
				{
					"fieldname": ZONE_FIELD,
					"label": "Zone for the Minimum Wage",
					"fieldtype": "Data",
					"insert_after": EXPERIENCE_FIELD,
					"depends_on": f"eval:doc.{EMPLOYEE_FIELD}",
					"description": "Only when the agreement's minimum wages differ by zone.",
				},
				{
					"fieldname": CANTON_FIELD,
					"label": "Canton of Work",
					"fieldtype": "Select",
					"options": CANTONS,
					"insert_after": ZONE_FIELD,
					"depends_on": f"eval:doc.{EMPLOYEE_FIELD}",
					"description": "The canton whose minimum wage applies to this person, when it has one.",
				},
				{
					"fieldname": REDUCTION_FIELD,
					"label": "Reduction of the Minimum Agreed",
					"fieldtype": "Check",
					"insert_after": CANTON_FIELD,
					"depends_on": f"eval:doc.{EMPLOYEE_FIELD}",
					"description": "Agreed with this person as the agreement allows it: the minimum is lowered only in a month"
					" whose turnover stays under the agreement's threshold.",
				},
			],
			"Salary Component": [
				{
					"fieldname": COUNTS_FIELD,
					"label": "Counts toward the Minimum Wage",
					"fieldtype": "Check",
					"insert_after": "depends_on_payment_days",
					"description": "Its amounts on a pay slip count when the month's pay is compared to the minimum wage"
					" of the person's agreement.",
				}
			],
		},
		update=True,
	)
