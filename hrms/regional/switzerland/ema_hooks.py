# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""EMA (Eintritt/Mutation/Austritt) change detection hooks for Employee."""

import frappe
from frappe.utils import today

# Fields that trigger an EMA Mutation notification when changed
EMA_TRACKED_FIELDS = (
	"marital_status",
	"ch_fiscal_canton",
	"ch_work_percentage",
	"ch_permit_type",
	"ch_avs_number",
	"ch_nationality",
)


def detect_ema_changes(doc, method=None):
	"""Detect EMA-relevant changes on Employee and create draft notifications.

	Called via doc_events Employee.on_update hook. Only triggers for
	companies with country_code == "Switzerland" or a Swiss Social
	Insurance Config.

	Args:
		doc: Employee document being saved.
		method: Hook method name (unused).
	"""
	if not _is_swiss_company(doc.company):
		return

	# Detect event type
	previous = doc.get_doc_before_save()

	if not previous:
		# New employee — Eintritt
		_create_ema_notification(doc, "Eintritt", "New employee created.")
		return

	# Austritt: status changed to "Left" or exit date set
	if _is_austritt(doc, previous):
		exit_date = doc.get("ch_exit_date") or doc.get("relieving_date") or today()
		_create_ema_notification(
			doc, "Austritt", "Employee status changed to Left.", event_date=exit_date
		)
		return

	# Mutation: check tracked fields
	changes = _detect_field_changes(doc, previous)
	if changes:
		details = "; ".join(
			f"{field}: {old_val} → {new_val}" for field, old_val, new_val in changes
		)
		_create_ema_notification(doc, "Mutation", details)


def _is_swiss_company(company):
	"""Check if the company has a Swiss Social Insurance Config."""
	if not company:
		return False
	return frappe.db.exists(
		"Swiss Social Insurance Config", {"company": company}
	)


def _is_austritt(doc, previous):
	"""Check if the employee is leaving."""
	# Status changed to Left
	if doc.status == "Left" and previous.status != "Left":
		return True
	# Exit date was set (and wasn't before)
	new_exit = doc.get("ch_exit_date") or doc.get("relieving_date")
	old_exit = previous.get("ch_exit_date") or previous.get("relieving_date")
	if new_exit and not old_exit:
		return True
	return False


def _detect_field_changes(doc, previous):
	"""Compare EMA-tracked fields between current and previous state.

	Returns:
		list of (field_name, old_value, new_value) tuples for changed fields.
	"""
	changes = []
	for field in EMA_TRACKED_FIELDS:
		old_val = previous.get(field)
		new_val = doc.get(field)
		if str(old_val or "") != str(new_val or ""):
			changes.append((field, old_val, new_val))
	return changes


def _create_ema_notification(doc, event_type, change_details, event_date=None):
	"""Create a draft EMA notification for the employee.

	Args:
		doc: Employee document.
		event_type: "Eintritt", "Mutation", or "Austritt".
		change_details: Description of what changed.
		event_date: Optional event date (defaults to today).
	"""
	if event_date is None:
		if event_type == "Eintritt":
			event_date = doc.get("ch_entry_date") or doc.get("date_of_joining") or today()
		else:
			event_date = today()

	try:
		ema = frappe.get_doc(
			{
				"doctype": "Swissdec EMA Notification",
				"company": doc.company,
				"employee": doc.name,
				"event_type": event_type,
				"event_date": event_date,
				"change_details": change_details,
			}
		)
		ema.insert(ignore_permissions=True)
		frappe.msgprint(
			frappe._("EMA notification ({0}) created for {1}.").format(event_type, doc.employee_name),
			indicator="blue",
			alert=True,
		)
	except Exception:
		# Don't block employee save if EMA creation fails
		frappe.log_error("EMA creation failed", frappe.get_traceback())
