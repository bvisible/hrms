# //// Neoffice — added file (no upstream equivalent): what NORA's HR pole reads of recruitment, and the
# //// one switch it may flip (neoffice-maintenance#1294). Every call runs as the person asking: the
# //// Job Applicant / Job Opening permissions decide (HR User, HR Manager), and a person without them
# //// gets a PermissionError.
"""Recruitment, for NORA (tools `hr_job_*`, hermes-poc).

Compact on purpose: a tool's result is cut beyond a size, so the readings come as their summary,
scores and points — never the text of the documents.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, get_datetime

from hrms.hr.careers.share import page_url

SUMMARY_LIMIT = 300


def _json(value) -> dict:
	if isinstance(value, dict):
		return value
	try:
		return json.loads(value or "{}")
	except ValueError:
		return {}


def _criteria_state(job_openings: list[str]) -> dict:
	rows = frappe.get_all(
		"Job Opening",
		filters={"name": ("in", job_openings or [""])},
		fields=["name", "careers_criteria_reviewed", "careers_criteria_changed_on"],
	)
	return {r.name: r for r in rows}


@frappe.whitelist()
def list_openings(status: str = "Open") -> list[dict]:
	frappe.has_permission("Job Opening", "read", throw=True)
	filters = {"status": status} if status else {}
	openings = frappe.get_list(
		"Job Opening",
		filters=filters,
		fields=["name", "job_title", "status", "publish", "closes_on", "route", "careers_criteria_reviewed"],
		order_by="posted_on desc",
		limit_page_length=50,
	)
	counts = dict(
		frappe.get_all(
			"Job Applicant",
			filters={"job_title": ("in", [o.name for o in openings] or [""])},
			fields=["job_title", "count(name) as n"],
			group_by="job_title",
			as_list=True,
		)
	)
	return [
		{
			"name": o.name,
			"job_title": o.job_title,
			"status": o.status,
			"published": cint(o.publish),
			"applications": counts.get(o.name, 0),
			"closes_on": str(o.closes_on) if o.closes_on else None,
			"url": page_url(o.route) if o.publish and o.route else None,
			"criteria_reviewed": cint(o.careers_criteria_reviewed),
		}
		for o in openings
	]


def _stale(reviewed_on, criteria_changed_on) -> int:
	return int(
		bool(
			reviewed_on
			and criteria_changed_on
			and get_datetime(reviewed_on) < get_datetime(criteria_changed_on)
		)
	)


@frappe.whitelist()
def list_applications(
	job_opening: str | None = None,
	since: str | None = None,
	status: str | None = None,
	order_by: str = "score",
	limit: int = 20,
) -> list[dict]:
	frappe.has_permission("Job Applicant", "read", throw=True)
	filters = {}
	if job_opening:
		filters["job_title"] = job_opening
	if status:
		filters["status"] = status
	if since:
		filters["creation"] = (">=", since)
	order = "careers_score desc, creation desc" if order_by == "score" else "creation desc"
	rows = frappe.get_list(
		"Job Applicant",
		filters=filters,
		fields=[
			"name",
			"applicant_name",
			"job_title",
			"status",
			"creation",
			"careers_review_status",
			"careers_score",
			"careers_completeness",
			"careers_summary",
			"careers_review",
		],
		order_by=order,
		limit_page_length=min(cint(limit) or 20, 50),
	)
	titles = dict(
		frappe.get_all(
			"Job Opening",
			filters={"name": ("in", [r.job_title for r in rows if r.job_title] or [""])},
			fields=["name", "job_title"],
			as_list=True,
		)
	)
	states = _criteria_state([r.job_title for r in rows if r.job_title])
	reviews = {
		r.name: r
		for r in frappe.get_all(
			"Job Applicant Review",
			filters={"name": ("in", [r.careers_review for r in rows if r.careers_review] or [""])},
			fields=["name", "axis_scores", "reviewed_on"],
		)
	}
	out = []
	for r in rows:
		review = reviews.get(r.careers_review)
		state = states.get(r.job_title)
		out.append(
			{
				"name": r.name,
				"applicant_name": r.applicant_name,
				"job_opening": r.job_title,
				"job_title": titles.get(r.job_title) or _("Unsolicited application"),
				"status": r.status,
				"received": str(r.creation)[:16],
				"review_status": r.careers_review_status or "Not requested",
				# an unsolicited application is read without criteria: it has no score
				"score": r.careers_score if r.job_title else None,
				"completeness": r.careers_completeness,
				"axes": _json(review.axis_scores) if review else {},
				"summary": (r.careers_summary or "")[:SUMMARY_LIMIT],
				"review_stale": _stale(review.reviewed_on, state.careers_criteria_changed_on)
				if review and state
				else 0,
			}
		)
	return out


@frappe.whitelist()
def get_application(job_applicant: str) -> dict:
	frappe.has_permission("Job Applicant", "read", doc=job_applicant, throw=True)
	applicant = frappe.get_doc("Job Applicant", job_applicant)
	opening = frappe.get_doc("Job Opening", applicant.job_title) if applicant.job_title else None
	review = (
		frappe.get_doc("Job Applicant Review", applicant.careers_review)
		if applicant.get("careers_review")
		else None
	)
	details = _json(review.details) if review else {}
	return {
		"name": applicant.name,
		"applicant_name": applicant.applicant_name,
		"job_opening": applicant.job_title,
		"job_title": opening.job_title if opening else _("Unsolicited application"),
		"status": applicant.status,
		"received": str(applicant.creation)[:16],
		"source": applicant.source,
		"review_status": applicant.get("careers_review_status") or "Not requested",
		"score": applicant.get("careers_score") if details.get("criteria") else None,
		"completeness": applicant.get("careers_completeness"),
		"axes": _json(review.axis_scores) if review else {},
		"summary": review.summary if review else "",
		"strengths": details.get("strengths") or [],
		"to_check": details.get("to_check") or [],
		"interview_questions": details.get("interview_questions") or [],
		"missing": details.get("missing") or [],
		"criteria": [
			{"criterion": c.get("criterion"), "verdict": c.get("verdict"), "evidence": c.get("evidence")}
			for c in details.get("criteria") or []
		],
		"documents": [
			{"type": row.document_type, "label": row.label or "", "read_status": row.read_status or ""}
			for row in applicant.get("careers_documents") or []
		],
		"answers": [
			{"question": a.question, "answer": a.answer} for a in applicant.get("careers_answers") or []
		],
		"criteria_reviewed": cint(opening.get("careers_criteria_reviewed")) if opening else 1,
		"review_stale": _stale(review.reviewed_on, opening.get("careers_criteria_changed_on"))
		if review and opening
		else 0,
	}


@frappe.whitelist()
def set_published(job_opening: str, publish) -> dict:
	"""Publish an opening on the site, or withdraw it."""
	frappe.has_permission("Job Opening", "write", doc=job_opening, throw=True)
	doc = frappe.get_doc("Job Opening", job_opening)
	doc.publish = 1 if str(publish).lower() in ("1", "true", "yes") else 0
	doc.save()
	return {"published": cint(doc.publish), "url": page_url(doc.route) if doc.publish and doc.route else None}
