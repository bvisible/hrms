# //// Neoffice — added file (no upstream equivalent): the e-mails of an application — the recruiter's
# //// and the applicant's acknowledgement (neoffice-maintenance#1294).
"""Who hears about an application, and when.

- **The applicant** gets an acknowledgement at once, in the language of the page they applied on.
- **The recruiter** gets one e-mail per application: the opening's recruiter, else the addresses of
  Careers Settings, else the HR Managers. It carries Nora's reading when it is ready; the queue
  sends it right after the reading. When the reading cannot run (disabled, Nora busy or down), the
  e-mail leaves without it — the scheduler sends any e-mail still waiting after 15 minutes. The
  files stay in Neoffice: the e-mail links to the record, it attaches nothing.

Our `frappe.sendmail` sends at once and commits (neoffice fork): nothing here is a dry run.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, format_datetime, get_url_to_form, now_datetime, validate_email_address

OVERDUE_MINUTES = 15


def _sender() -> str | None:
	try:
		return frappe.db.get_single_value("HR Settings", "hiring_sender_email") or None
	except Exception:
		return None


def recipients(applicant) -> list[str]:
	"""The recruiter of the opening, else the settings' addresses, else the HR Managers."""
	out = []
	if applicant.job_title:
		recruiter = frappe.db.get_value("Job Opening", applicant.job_title, "careers_recruiter")
		if recruiter:
			out.append(frappe.db.get_value("User", recruiter, "email") or recruiter)
	if not out:
		listed = frappe.db.get_single_value("Careers Settings", "notification_recipients") or ""
		out = [line.strip() for line in listed.replace(",", "\n").split("\n") if line.strip()]
	if not out:
		managers = frappe.get_all(
			"Has Role",
			filters={
				"role": "HR Manager",
				"parenttype": "User",
				"parent": ("not in", ("Administrator", "Guest")),
			},
			pluck="parent",
		)
		out = frappe.get_all("User", filters={"name": ("in", managers or [""]), "enabled": 1}, pluck="email")
	return sorted({e for e in out if validate_email_address(e)})


class _language:
	"""Render in a given language, then restore the job's own."""

	def __init__(self, lang: str | None):
		self.lang = lang

	def __enter__(self):
		self.previous = frappe.local.lang
		if self.lang:
			frappe.local.lang = self.lang

	def __exit__(self, *exc):
		frappe.local.lang = self.previous


def _site_language() -> str:
	return frappe.db.get_default("lang") or "fr"


def _documents(applicant) -> list[dict]:
	from hrms.hr.careers.documents import label_of

	return [
		{"label": label_of(row), "name": (row.file or "").rsplit("/", 1)[-1]}
		for row in applicant.get("careers_documents") or []
	]


def acknowledge(applicant_name: str) -> bool:
	applicant = frappe.get_doc("Job Applicant", applicant_name)
	if applicant.get("careers_acknowledged_on") or not validate_email_address(applicant.email_id):
		return False
	opening = frappe.get_doc("Job Opening", applicant.job_title) if applicant.job_title else None
	with _language(applicant.get("careers_language") or _site_language()):
		subject = (
			_("Your application: {0}").format(opening.job_title)
			if opening
			else _("Your unsolicited application")
		)
		message = frappe.render_template(
			"templates/emails/careers_acknowledgement.html",
			{
				"first_name": (applicant.applicant_name or "").split(" ")[0],
				"opening": opening,
				"company": opening.company if opening else frappe.defaults.get_global_default("company"),
				"documents": _documents(applicant),
				"retention_days": frappe.db.get_single_value("Careers Settings", "retention_days") or 90,
			},
		)
	frappe.sendmail(
		recipients=[applicant.email_id],
		sender=_sender(),
		subject=subject,
		message=message,
		reference_doctype="Job Applicant",
		reference_name=applicant.name,
	)
	frappe.db.set_value(
		"Job Applicant", applicant.name, "careers_acknowledged_on", now_datetime(), update_modified=False
	)
	return True


def notify_recruiters(applicant_name: str, review: dict | None = None, updated: bool = False) -> bool:
	applicant = frappe.get_doc("Job Applicant", applicant_name)
	if applicant.get("careers_recruiter_notified_on") and not updated:
		return False
	to = recipients(applicant)
	if not to:
		frappe.log_error(
			"Careers page: nobody to notify",
			f"Job Applicant {applicant.name}: no recruiter, no address, no HR Manager",
		)
		return False
	opening = frappe.get_doc("Job Opening", applicant.job_title) if applicant.job_title else None
	with _language(_site_language()):
		what = opening.job_title if opening else _("Unsolicited application")
		subject = (
			_("Application completed: {0} — {1}") if updated else _("New application: {0} — {1}")
		).format(what, applicant.applicant_name)
		message = frappe.render_template(
			"templates/emails/careers_new_application.html",
			{
				"applicant": applicant,
				"opening": opening,
				"updated": updated,
				"received_on": format_datetime(applicant.creation, "dd.MM.yyyy HH:mm"),
				"documents": _documents(applicant),
				"answers": applicant.get("careers_answers") or [],
				"review": review,
				"reading_pending": applicant.get("careers_review_status") == "Queued" and not review,
				"url": get_url_to_form("Job Applicant", applicant.name),
			},
		)
	frappe.sendmail(
		recipients=to,
		sender=_sender(),
		subject=subject,
		message=message,
		reference_doctype="Job Applicant",
		reference_name=applicant.name,
	)
	frappe.db.set_value(
		"Job Applicant",
		applicant.name,
		"careers_recruiter_notified_on",
		now_datetime(),
		update_modified=False,
	)
	return True


def send_overdue():
	"""Scheduler: an application nobody has heard of after 15 minutes is announced without its reading."""
	cutoff = add_to_date(now_datetime(), minutes=-OVERDUE_MINUTES)
	for name in frappe.get_all(
		"Job Applicant",
		filters={
			"careers_recruiter_notified_on": ("is", "not set"),
			"careers_privacy_consent_on": ("is", "set"),
			"creation": ("<", cutoff),
		},
		pluck="name",
		limit=50,
	):
		try:
			notify_recruiters(name)
		except Exception:
			frappe.log_error("Careers page: recruiter e-mail not sent", frappe.get_traceback())
