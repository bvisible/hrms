# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _


@frappe.whitelist()
def create_salary_component_from_wage_type(wage_type_code, company=None):
	"""Create Salary Component(s) from a Swiss Wage Type catalog entry.

	If the wage type has a linked counterpart (employee/employer pair),
	both components are created and linked together.

	Args:
		wage_type_code: The Swiss Wage Type code (e.g., "5010").
		company: Optional company name for GL account setup.

	Returns:
		dict with created component name(s).
	"""
	wt_name = f"CH-WT-{wage_type_code}"
	if not frappe.db.exists("Swiss Wage Type", wt_name):
		frappe.throw(_("Swiss Wage Type {0} not found").format(wage_type_code))

	wt = frappe.get_doc("Swiss Wage Type", wt_name)
	primary = _create_component_from_wage_type(wt)

	linked_name = None
	if wt.linked_wage_type_code:
		linked_wt_name = f"CH-WT-{wt.linked_wage_type_code}"
		if frappe.db.exists("Swiss Wage Type", linked_wt_name):
			linked_wt = frappe.get_doc("Swiss Wage Type", linked_wt_name)
			existing = frappe.db.get_value("Salary Component", {"ch_wage_type": linked_wt_name}, "name")
			if not existing:
				linked_name = _create_component_from_wage_type(linked_wt)
			else:
				linked_name = existing

	# Link paired components
	if linked_name and primary:
		frappe.db.set_value("Salary Component", primary, "linked_component", linked_name)
		frappe.db.set_value("Salary Component", linked_name, "linked_component", primary)
		frappe.db.commit()

	result = {"primary": primary}
	if linked_name:
		result["linked"] = linked_name
	return result


def _create_component_from_wage_type(wt):
	"""Create a single Salary Component from a Swiss Wage Type.

	Args:
		wt: Swiss Wage Type document.

	Returns:
		Name of the created Salary Component.
	"""
	component_name = wt.wage_type_name
	if frappe.db.exists("Salary Component", component_name):
		# Check if already linked to this wage type
		existing_wt = frappe.db.get_value("Salary Component", component_name, "ch_wage_type")
		if existing_wt == wt.name:
			return component_name
		frappe.throw(_("Salary Component '{0}' already exists.").format(component_name))

	comp_type = wt.type if wt.type in ("Earning", "Deduction") else "Earning"
	abbr = wt.abbreviation or f"CH{wt.code}"

	# Use French description if available, fallback to wage type name
	description = wt.description_fr or f"{wt.wage_type_name} (Code {wt.code})"

	doc = frappe.new_doc("Salary Component")
	doc.salary_component = component_name
	doc.salary_component_abbr = abbr
	doc.type = comp_type
	doc.description = description
	doc.depends_on_payment_days = wt.depends_on_payment_days if wt.depends_on_payment_days is not None else 1
	doc.remove_if_zero_valued = 1

	# Formula/condition from template
	if wt.amount_based_on_formula and wt.formula:
		doc.amount_based_on_formula = 1
		doc.formula = wt.formula
	elif wt.default_amount:
		doc.amount = wt.default_amount

	if wt.condition:
		doc.condition = wt.condition

	# Employer contribution flags
	if wt.is_employer_contribution:
		doc.is_employer_contribution = 1
		doc.do_not_include_in_total = 1
	elif wt.do_not_include_in_total:
		doc.do_not_include_in_total = 1

	# Swiss-specific fields
	doc.ch_wage_type = wt.name
	doc.ch_wage_type_code = wt.code
	doc.ch_subject_to_avs = wt.subject_to_avs
	doc.ch_subject_to_ac = wt.subject_to_ac
	doc.ch_subject_to_laa = wt.subject_to_laa
	doc.ch_subject_to_ijm = wt.subject_to_ijm
	doc.ch_subject_to_lpp = wt.subject_to_lpp
	doc.ch_subject_to_imp = wt.subject_to_imp
	if wt.lohnausweis_position:
		doc.ch_lohnausweis_position = wt.lohnausweis_position

	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name


# ─── Swiss Payroll Chat Assistant API ─────────────────────────────────


@frappe.whitelist()
def chat_start_session(company=None):
	"""Start or resume a Swiss payroll configuration chat session."""
	from hrms.regional.switzerland.assistant.chat_service import SwissPayrollChatService

	service = SwissPayrollChatService()
	return service.start_session(company=company)


@frappe.whitelist()
def chat_send_message(session_id, message):
	"""Send a user message and get AI response."""
	from hrms.regional.switzerland.assistant.chat_service import SwissPayrollChatService

	if not session_id or not message:
		frappe.throw(_("Session ID and message are required"))

	service = SwissPayrollChatService()
	return service.process_message(session_id, message)


@frappe.whitelist()
def chat_apply_step(session_id):
	"""Apply collected data for the current step to Frappe records."""
	from hrms.regional.switzerland.assistant.chat_service import SwissPayrollChatService

	if not session_id:
		frappe.throw(_("Session ID is required"))

	service = SwissPayrollChatService()
	return service.apply_step(session_id)


@frappe.whitelist()
def chat_get_session(session_id):
	"""Get full session data for display."""
	if not session_id:
		frappe.throw(_("Session ID is required"))

	import json

	session = frappe.get_doc("Swiss Payroll Chat Session", session_id)

	# Verify ownership
	if session.user != frappe.session.user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Access denied"))

	return {
		"session_id": session.name,
		"status": session.status,
		"current_step": session.current_step,
		"completion": session.completion_percentage,
		"collected_data": session.get_collected_data(),
		"messages": [
			{
				"role": msg.role,
				"content": msg.content,
				"buttons": json.loads(msg.buttons) if msg.buttons else None,
				"timestamp": str(msg.timestamp) if msg.timestamp else None,
			}
			for msg in session.messages
		],
	}
