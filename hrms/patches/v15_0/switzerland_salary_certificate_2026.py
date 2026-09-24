# //// Neoffice — added file (no upstream equivalent): bring existing sites to the salary
# //// certificate of 2026-09-23.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Bring existing sites to the salary certificate of 2026-09-23.

1. Positions. The catalogue follows the ESTV/SSK FAQ 2026 on the salary certificate (1.6):
   income replacement benefits in box 7, the corrections of short-time work (2060, 2075) with
   the salary in box 1, tips (1920) in box 7 (Wegleitung Rz 32). Every Swiss Wage Type row takes
   the catalogue's position — it is reference data. A Salary Component takes it where it still
   holds the position of its wage type row before this patch, a position the catalogue held
   since 2026-09-22, or none: a position set deliberately on a client site is left alone.

2. The certificate mapping of the configurations. Until 2026-09-23 it was the only source of
   the certificate, and the setup filled it with default rows. The certificate now places a row
   by its component's own position, so:
   - a row equal to an old default is deleted, after its position moved onto a component that
     has none; "Child Allowance" in box 7 was wrong (family allowances belong to box 1,
     Wegleitung Rz 15) and goes to box 1;
   - a row repeating what the component says anyway is deleted;
   - any other row is a choice and is kept, its legacy values 13.1 and 13.2 rewritten to the
     positions of the form (the select no longer offers them).

3. Employees read their own certificates (portal, mobile app): the Employee role's read and
   print, added to the site's customised permissions when it has some — a site whose Role
   Permission Manager touched the certificate ignores the doctype's own permissions altogether —
   and the Employee Self Service user type.
"""

import frappe
from frappe.utils import cint

from hrms.regional.switzerland.patch_utils import has_swiss_columns
from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types

# Positions the catalogue held on 2026-09-22 where it changed on 2026-09-23.
PREVIOUS_POSITIONS = {
	"1920": {"1"},
	"2020": {"1"},
	"2025": {"1"},
	"2030": {"1"},
	"2035": {"1"},
	"2060": {"7"},
	"2075": {"7"},
}

# The default certificate mapping as the setup wrote it until 2026-09-23.
OLD_DEFAULT_MAPPING = {
	"Basic": "1",
	"13th Month Salary": "1",
	"Overtime Pay": "1",
	"Vacation Allowance": "1",
	"Bonus": "3",
	"APG Allowance": "7",
	"IJM Sickness Allowance": "7",
	"Maternity Allowance": "7",
	"Child Allowance": "7",
	"AVS/AI/APG Employee": "9",
	"AC/ALV Employee": "9",
	"LAA Non-Professional Employee": "9",
	"LPP/BVG Employee": "10.1",
	"Source Tax Employee": "12",
	"Travel Expenses": "13.1.1",
	"Car Expenses": "13.1.1",
	"Meal Expenses": "13.1.1",
	"Flat-Rate Representation Expenses": "13.2.1",
}
FAMILY_ALLOWANCE_COMPONENTS = {"Child Allowance"}
LEGACY_POSITIONS = {"13.1": "13.1.1", "13.2": "13.2.3"}


def execute():
	if not frappe.db.table_exists("Swiss Wage Type"):
		return
	_sync_positions()
	_clean_mappings()
	_grant_employee_read()
	_grant_employee_self_service()
	frappe.db.commit()


def _sync_positions():
	# The wage types always; the components only once their Swiss columns exist (#722).
	components_readable = has_swiss_columns(
		"Salary Component", "ch_wage_type_code", "ch_lohnausweis_position"
	)
	for code, position in {
		wt["code"]: wt["lohnausweis_position"] or "" for wt in get_swiss_wage_types()
	}.items():
		name = f"CH-WT-{code}"
		before = frappe.db.get_value("Swiss Wage Type", name, "lohnausweis_position")
		if before is not None and (before or "") != position:
			frappe.db.set_value(
				"Swiss Wage Type", name, "lohnausweis_position", position, update_modified=False
			)
			print(f"Swiss payroll: wage type {code} salary certificate {before or '-'} -> {position or '-'}")

		if not components_readable:
			continue
		untouched = {"", before or "", *PREVIOUS_POSITIONS.get(code, ())}
		for component in frappe.get_all(
			"Salary Component",
			filters={"ch_wage_type_code": code},
			fields=["name", "ch_lohnausweis_position"],
		):
			current = component.ch_lohnausweis_position or ""
			if current != position and current in untouched:
				frappe.db.set_value(
					"Salary Component",
					component.name,
					"ch_lohnausweis_position",
					position,
					update_modified=False,
				)
				print(
					f"Swiss payroll: '{component.name}' ({code}) salary certificate "
					f"{current or '-'} -> {position or '-'}"
				)


def _own_position(component):
	if component.ch_lohnausweis_position:
		return component.ch_lohnausweis_position
	if component.ch_wage_type_code:
		return frappe.db.get_value(
			"Swiss Wage Type", f"CH-WT-{component.ch_wage_type_code}", "lohnausweis_position"
		)
	return None


def _clean_mappings():
	if not frappe.db.table_exists("Swiss Lohnausweis Mapping"):
		return
	if not has_swiss_columns("Salary Component", "ch_wage_type_code", "ch_lohnausweis_position"):
		return
	for row in frappe.get_all(
		"Swiss Lohnausweis Mapping",
		filters={"parenttype": "Swiss Social Insurance Config"},
		fields=["name", "parent", "salary_component", "lohnausweis_position", "include_in_certificate"],
	):
		position = LEGACY_POSITIONS.get(row.lohnausweis_position, row.lohnausweis_position)
		component = frappe.db.get_value(
			"Salary Component",
			row.salary_component,
			["name", "type", "ch_lohnausweis_position", "ch_wage_type_code"],
			as_dict=True,
		)
		if not component:
			continue
		own = _own_position(component)

		if cint(row.include_in_certificate) and OLD_DEFAULT_MAPPING.get(row.salary_component) == position:
			if not own:
				moved = "1" if row.salary_component in FAMILY_ALLOWANCE_COMPONENTS else position
				frappe.db.set_value(
					"Salary Component",
					component.name,
					"ch_lohnausweis_position",
					moved,
					update_modified=False,
				)
			frappe.db.delete("Swiss Lohnausweis Mapping", {"name": row.name})
			print(f"Swiss payroll: {row.parent}: default mapping row '{row.salary_component}' removed")
		elif cint(row.include_in_certificate) and (
			own == position or (not own and component.type == "Earning" and position == "1")
		):
			frappe.db.delete("Swiss Lohnausweis Mapping", {"name": row.name})
			print(f"Swiss payroll: {row.parent}: redundant mapping row '{row.salary_component}' removed")
		elif position != row.lohnausweis_position:
			frappe.db.set_value(
				"Swiss Lohnausweis Mapping", row.name, "lohnausweis_position", position, update_modified=False
			)


def _grant_employee_read():
	doctype = "Swiss Salary Certificate"
	if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
		return  # the doctype's own permissions apply, Employee included
	if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": "Employee", "permlevel": 0}):
		return
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": "Employee",
			"permlevel": 0,
			"read": 1,
			"print": 1,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype=doctype)
	print(f"Swiss payroll: {doctype} readable by the Employee role (customised permissions)")


def _grant_employee_self_service():
	if not frappe.db.exists("User Type", "Employee Self Service"):
		return
	doc = frappe.get_doc("User Type", "Employee Self Service")
	if "Swiss Salary Certificate" in {d.document_type for d in doc.user_doctypes}:
		return
	frappe.db.savepoint("ess_salary_certificate")
	try:
		doc.append("user_doctypes", {"document_type": "Swiss Salary Certificate", "read": 1})
		doc.flags.ignore_links = True
		doc.save(ignore_permissions=True)
	except Exception as e:
		# The user type refuses to save when the site config sets no doctype limit for it, or a
		# lower one than its rows: the certificate stays readable through the Employee role.
		frappe.db.rollback(save_point="ess_salary_certificate")
		print(f"Swiss payroll: Employee Self Service not extended to the salary certificate: {e}")
