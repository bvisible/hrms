# //// Neoffice — added file (no upstream equivalent): consistency audit of the Swiss salary
# //// components installed on a site against the wage type catalogue.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Check the Swiss salary components of a site against the wage type catalogue.

Salary Components are created once, when a site is provisioned, and never
revisited: `create_swiss_salary_components()` only creates what is missing. So a
component keeps forever the wage type code it was given the day it was made —
and if that code was wrong, or the catalogue moved under it, nothing says so.

That is not theoretical. On an instance provisioned early, "13th Month Salary"
carried code **1050**, which is the HOUSING ALLOWANCE: the 13th month would have
been declared as a housing benefit. The code is stored on the component only
(Salary Detail has no copy), so a single correction fixes past slips too — but
only if someone notices.

This module is what notices. Run it before onboarding a client, and after any
catalogue change.
"""

import frappe

from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types


def audit_salary_components(company=None):
	"""Compare every Swiss salary component with the catalogue.

	Args:
		company: restrict to one company; all of them if omitted.

	Returns:
		dict with ``issues`` (a list of dicts: component, code, severity, message)
		and ``checked``.
	"""
	catalogue = {str(w["code"]): w for w in get_swiss_wage_types()}

	filters = {"ch_wage_type_code": ["!=", ""]}
	if company:
		filters["company"] = company
	components = frappe.get_all(
		"Salary Component",
		filters=filters,
		fields=["name", "type", "ch_wage_type", "ch_wage_type_code", "ch_lohnausweis_position"],
	)

	issues = []
	for c in components:
		code = (c.ch_wage_type_code or "").strip()
		entry = catalogue.get(code)

		if not entry:
			issues.append({
				"component": c.name,
				"code": code,
				"severity": "error",
				"message": f"wage type {code} is not in the catalogue",
			})
			continue

		# A component whose name has nothing to do with its wage type is the
		# signature of a code assigned once and never revisited.
		if c.type and entry.get("type") and c.type != entry["type"]:
			issues.append({
				"component": c.name,
				"code": code,
				"severity": "error",
				"message": (
					f"component is a {c.type} but wage type {code} "
					f"({entry['wage_type_name']}) is a {entry['type']}"
				),
			})

		expected_position = str(entry.get("lohnausweis_position") or "").strip()
		actual_position = str(c.ch_lohnausweis_position or "").strip()
		if expected_position and actual_position and expected_position != actual_position:
			issues.append({
				"component": c.name,
				"code": code,
				"severity": "warning",
				"message": (
					f"salary certificate position {actual_position!r} differs from the "
					f"catalogue's {expected_position!r} for {entry['wage_type_name']}"
				),
			})

		if c.ch_wage_type and c.ch_wage_type != f"CH-WT-{code}":
			issues.append({
				"component": c.name,
				"code": code,
				"severity": "error",
				"message": f"link {c.ch_wage_type} does not match code {code}",
			})

	return {"checked": len(components), "issues": issues}


def report(company=None):
	"""Printable audit, for a bench execute or a console.

	Not whitelisted: neither needs it, and through /api/method any signed-in user — a portal customer
	included — read the audit of the company's salary components (three-identity test, 24.09)."""
	result = audit_salary_components(company)
	errors = [i for i in result["issues"] if i["severity"] == "error"]
	warnings = [i for i in result["issues"] if i["severity"] == "warning"]

	print(f"Swiss salary components checked: {result['checked']}")
	print(f"  errors   : {len(errors)}")
	print(f"  warnings : {len(warnings)}")
	for issue in errors + warnings:
		mark = "ERROR  " if issue["severity"] == "error" else "warning"
		print(f"  [{mark}] {issue['component']} ({issue['code']}): {issue['message']}")
	return result
