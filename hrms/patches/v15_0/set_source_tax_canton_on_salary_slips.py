# //// Neoffice — added file (no upstream equivalent): installs Salary Slip.ch_qst_canton and fills it
# //// on the slips already settled under source tax, so the year-end recap splits their tax by the
# //// canton they were computed with, not by the canton the employee lives in today.
import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from hrms.regional.switzerland.patch_utils import has_swiss_columns

FIELDS = ("ch_qst_taxation_canton", "ch_fiscal_canton")


def execute():
	from hrms.regional.switzerland.payroll_hooks import _resolve_component_by_wage_type
	from hrms.regional.switzerland.setup import get_custom_fields

	fields = [f for f in get_custom_fields().get("Salary Slip", []) if f.get("fieldname") == "ch_qst_canton"]
	if fields:
		create_custom_fields({"Salary Slip": fields}, update=True)
	# Resolving the source tax component reads Salary Component.ch_wage_type (#722).
	if not has_swiss_columns("Salary Component", "ch_wage_type"):
		return
	component = _resolve_component_by_wage_type(5060, "Source Tax Employee")
	if not component or not frappe.db.has_column("Salary Slip", "ch_qst_canton"):
		return

	slips = frappe.db.sql(
		"""SELECT DISTINCT ss.name, ss.employee, ss.creation
		FROM `tabSalary Slip` ss
		JOIN `tabSalary Detail` sd
			ON sd.parent = ss.name AND sd.parentfield = 'deductions' AND sd.salary_component = %s
		WHERE ss.docstatus = 1 AND IFNULL(ss.ch_qst_canton, '') = ''
			AND (IFNULL(ss.ch_qst_tariff_code, '') != '' OR sd.amount != 0)""",
		component,
		as_dict=True,
	)
	by_employee = {}
	for slip in slips:
		by_employee.setdefault(slip.employee, []).append(slip)

	for employee, rows in by_employee.items():
		current = frappe.db.get_value("Employee", employee, FIELDS, as_dict=True)
		if not current:
			continue
		history = field_changes(employee)
		for slip in rows:
			# The canton the payroll read when it computed the slip: the employee's values then.
			canton = next(
				(
					value
					for value in (
						value_at(current.get(field), history.get(field, []), slip.creation)
						for field in FIELDS
					)
					if value
				),
				None,
			)
			if canton:
				frappe.db.set_value("Salary Slip", slip.name, "ch_qst_canton", canton, update_modified=False)


def field_changes(employee):
	"""{field: [(changed_at, old, new)]} of the employee's canton fields, oldest first, from the
	version log (Employee tracks its changes)."""
	changes = {}
	for version in frappe.get_all(
		"Version",
		filters={"ref_doctype": "Employee", "docname": employee},
		fields=["creation", "data"],
		order_by="creation asc",
	):
		try:
			data = json.loads(version.data or "{}")
		except ValueError:
			continue
		for row in data.get("changed") or []:
			if len(row) == 3 and row[0] in FIELDS:
				changes.setdefault(row[0], []).append((version.creation, row[1], row[2]))
	return changes


def value_at(current, changes, moment):
	"""The value a field had at ``moment``: the old value of its first change after that moment,
	else its current value. ``changes`` are (changed_at, old, new), oldest first."""
	for changed_at, old, _new in changes:
		if changed_at > moment:
			return old
	return current
