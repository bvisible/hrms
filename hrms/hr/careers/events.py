# //// Neoffice — added file (no upstream equivalent): what the careers page does when an opening, an
# //// applicant or the site's plugin changes (neoffice-maintenance#1294). Wired in hooks.doc_events.
import json

import frappe
from frappe.utils import add_days, cint, now_datetime, today

from hrms.hr.careers.openings import normalize_route
from hrms.hr.careers.plugin import sync_menu

CRITERIA_FIELDS = ("criterion", "axis", "importance", "weight")


def _criteria_key(rows) -> str:
	return json.dumps([[r.get(f) for f in CRITERIA_FIELDS] for r in rows or []])


def job_opening_validate(doc, method=None):
	normalize_route(doc)
	_track_criteria(doc)


def _track_criteria(doc):
	"""Remember when the reading grid changed, and whether a person or the queue wrote it.

	A reading made before the grid changed is stale (NORA offers to read again), and scores that
	rest on criteria only Nora chose say so until a person has saved them.
	"""
	before = doc.get_doc_before_save()
	if before is not None and _criteria_key(before.get("careers_criteria")) == _criteria_key(
		doc.get("careers_criteria")
	):
		return
	if not doc.get("careers_criteria") and before is None:
		return
	doc.careers_criteria_changed_on = now_datetime()
	doc.careers_criteria_reviewed = 0 if frappe.flags.careers_queue_writes_criteria else 1


def job_opening_on_update(doc, method=None):
	if doc.publish and doc.status == "Open":
		from hrms.hr.careers.share_image import ensure_share_image

		ensure_share_image(doc)
	before = doc.get_doc_before_save()
	if before is not None and before.status != "Closed" and doc.status == "Closed":
		_start_retention_of(doc.name)
	sync_menu()


def job_opening_on_trash(doc, method=None):
	frappe.enqueue("hrms.hr.careers.plugin.sync_menu", queue="short", enqueue_after_commit=True)


def _retention_days() -> int:
	return cint(frappe.db.get_single_value("Careers Settings", "retention_days")) or 90


def _start_retention_of(job_opening: str):
	"""The opening is closed: its applicants' files are kept for the retention period, then deleted —
	except the one hired, whose file becomes an employee's."""
	until = add_days(today(), _retention_days())
	for name in frappe.get_all(
		"Job Applicant",
		filters={
			"job_title": job_opening,
			"status": ("!=", "Accepted"),
			"careers_retention_until": ("is", "not set"),
		},
		pluck="name",
	):
		frappe.db.set_value("Job Applicant", name, "careers_retention_until", until, update_modified=False)


def job_applicant_validate(doc, method=None):
	"""The decision starts the retention clock (rejected) or stops it (hired)."""
	before = doc.get_doc_before_save()
	if before is None or before.status == doc.status:
		return
	if doc.status == "Rejected" and not doc.get("careers_retention_until"):
		doc.careers_retention_until = add_days(today(), _retention_days())
	elif doc.status == "Accepted":
		doc.careers_retention_until = None


def website_plugin_on_update(doc, method=None):
	from hrms.hr.careers import PLUGIN_NAME

	if getattr(doc, "plugin_name", None) == PLUGIN_NAME:
		sync_menu()
