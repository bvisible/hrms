# //// Neoffice — added file (no upstream equivalent): the application endpoint of the careers page
# //// (neoffice-maintenance#1294).
"""Applying for an opening, as a visitor with no account.

Upstream's web form cannot take a CV from a visitor: Frappe refuses any guest upload while System
Settings → "Allow Guests to Upload Files" is off, and switching it on opens anonymous uploads to the
whole site. This endpoint takes the files itself, and only what the opening asked for:

- one upload field per requested document, each file typed by its field (`documents`);
- a file accepted for what its bytes are (PDF, DOCX, JPEG, PNG), 10 MB, 25 MB in all, 10 files;
- **private** files, attached to the applicant;
- a hidden field a person never fills, a signed time token (a form sent in under 3 s is a robot's),
  10 applications an hour per address, 3 an hour per e-mail;
- the same e-mail for the same opening completes the application already there instead of making a
  second one: a double click, or a candidate who forgot a document;
- an opening closed while the visitor was typing refuses the application, plainly — no orphan;
- where the visitor came from (the share link's `utm_source`, an employee's `ref`) becomes the
  applicant's source.

Nothing is decided here: the application is stored, the applicant gets an acknowledgement and the
recruiter an e-mail, and Nora's reading is queued (`review.process_new_application`).
"""

import hashlib
import hmac
import time

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days, add_months, cint, getdate, now_datetime, today, validate_email_address

from hrms.hr.careers import documents
from hrms.hr.careers.openings import _open_filters
from hrms.hr.careers.plugin import accepts_spontaneous, plugin_enabled
from hrms.hr.careers.share import source_of

MIN_FILL_SECONDS = 3
MAX_TOKEN_AGE = 24 * 60 * 60
MAX_TEXT = 2000
PER_EMAIL_PER_HOUR = 3
OPEN_STATUSES = ("Open", "Replied", "Hold")


# --------------------------------------------------------------------------- the time token


def _secret() -> bytes:
	from frappe.utils.password import get_encryption_key

	return get_encryption_key().encode()


def make_token() -> str:
	"""Printed in the form when the page is rendered: the time it was shown, signed."""
	stamp = str(int(time.time()))
	return f"{stamp}.{hmac.new(_secret(), stamp.encode(), hashlib.sha256).hexdigest()[:24]}"


def token_age(token: str | None) -> float | None:
	"""Seconds since the form was shown, or None when the token is missing or forged."""
	try:
		stamp, signature = (token or "").split(".", 1)
	except ValueError:
		return None
	expected = hmac.new(_secret(), stamp.encode(), hashlib.sha256).hexdigest()[:24]
	if not hmac.compare_digest(signature, expected):
		return None
	return time.time() - cint(stamp)


# --------------------------------------------------------------------------- reading the form


def _text(name: str, limit: int = 140) -> str:
	return (frappe.form_dict.get(name) or "").strip()[:limit]


def _checked(name: str) -> bool:
	return str(frappe.form_dict.get(name) or "").lower() in ("1", "on", "true", "yes")


def _opening(name: str | None):
	"""The opening applied for, if it still takes applications; None for an unsolicited one."""
	if not name:
		return None
	found = frappe.db.get_value(
		"Job Opening", {"name": name, **_open_filters()}, ["name", "closes_on"], as_dict=True
	)
	if not found or (found.closes_on and getdate(found.closes_on) < getdate(today())):
		return False
	return frappe.get_doc("Job Opening", found.name)


def _answers(opening, errors: dict) -> list[dict]:
	answers = []
	for row in (opening.get("careers_questions") or []) if opening else []:
		key = f"answer_{row.idx}"
		value = (frappe.form_dict.get(key) or "").strip()[:MAX_TEXT]
		if not value:
			if row.required:
				errors[key] = _("Please answer this question.")
			continue
		if row.answer_type == "Yes/No" and value not in ("yes", "no"):
			errors[key] = _("Please answer yes or no.")
			continue
		if row.answer_type == "Number":
			try:
				float(value.replace("'", "").replace(",", "."))
			except ValueError:
				errors[key] = _("Please enter a number.")
				continue
		if row.answer_type == "Choice":
			choices = [c.strip() for c in (row.options or "").split("\n") if c.strip()]
			if value not in choices:
				errors[key] = _("Please choose one of the answers.")
				continue
		if row.answer_type == "Yes/No":
			value = _("Yes") if value == "yes" else _("No")
		answers.append({"question": row.question, "answer": value})
	return answers


def _uploads(requested: list, errors: dict) -> list[tuple]:
	"""[(requested row, file name, bytes, kind)] for the files the form sent, checked."""
	accepted, total, count = [], 0, 0
	files = getattr(frappe.request, "files", None) or {}
	for row in requested:
		key = f"doc_{row.idx}"
		sent = [f for f in (files.getlist(key) if hasattr(files, "getlist") else []) if f and f.filename]
		if not sent:
			if row.required:
				errors[key] = _("This document is required.")
			continue
		if len(sent) > 1 and not row.allow_multiple:
			errors[key] = _("Only one file here.")
			continue
		for upload in sent:
			content = upload.stream.read(documents.MAX_FILE_BYTES + 1)
			if len(content) > documents.MAX_FILE_BYTES:
				errors[key] = _("{0} is larger than 10 MB.").format(upload.filename)
				break
			kind = documents.sniff(content)
			if not kind:
				errors[key] = _("{0} is not a PDF, a Word document (DOCX), a JPEG or a PNG.").format(
					upload.filename
				)
				break
			total += len(content)
			count += 1
			accepted.append((row, documents.safe_file_name(upload.filename, kind), content, kind))
	if count > documents.MAX_FILES:
		errors["documents"] = _("Please send at most {0} files.").format(documents.MAX_FILES)
	if total > documents.MAX_TOTAL_BYTES:
		errors["documents"] = _("The files weigh more than 25 MB in all.")
	return accepted


# --------------------------------------------------------------------------- the endpoint


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=60 * 60)
def submit_application():
	if not plugin_enabled():
		raise frappe.PermissionError(_("The jobs page is turned off."))

	form = frappe.form_dict
	thanks = "/jobs?applied=1"

	# a field no person sees: whoever filled it is answered as if it had worked
	if (form.get("website") or "").strip():
		return {"ok": True, "redirect": thanks}

	errors = {}
	age = token_age(form.get("form_token"))
	if age is None or age > MAX_TOKEN_AGE:
		return {
			"ok": False,
			"errors": {},
			"message": _("This page is too old. Please reload it and send your application again."),
		}
	if age < MIN_FILL_SECONDS:
		return {"ok": False, "errors": {}, "message": _("Please take a moment to check your application.")}

	opening = _opening(form.get("job_opening"))
	if opening is False:
		return {
			"ok": False,
			"errors": {},
			"message": _("This opening has just been closed. Your application has not been sent."),
		}
	if opening is None and not accepts_spontaneous():
		return {"ok": False, "errors": {}, "message": _("Unsolicited applications are not accepted.")}

	first_name, last_name = _text("first_name", 70), _text("last_name", 70)
	email = validate_email_address(_text("email", 140).lower()) or ""
	phone = _text("phone", 40)
	if not first_name:
		errors["first_name"] = _("Please enter your first name.")
	if not last_name:
		errors["last_name"] = _("Please enter your last name.")
	if not email:
		errors["email"] = _("Please enter a valid e-mail address.")
	if not _checked("consent"):
		errors["consent"] = _("Please confirm that you have read the information on your data.")

	answers = _answers(opening, errors)
	requested = documents.requested_documents(opening)
	uploads = _uploads(requested, errors)
	if errors:
		return {"ok": False, "errors": errors, "message": _("Please check the fields marked in red.")}

	one_hour_ago = add_days(now_datetime(), -1 / 24)
	if (
		frappe.db.count("Job Applicant", {"email_id": email, "creation": (">", one_hour_ago)})
		>= PER_EMAIL_PER_HOUR
	):
		return {
			"ok": False,
			"errors": {},
			"message": _("You have sent several applications in the last hour. Please try again later."),
		}

	applicant, updated = _store(opening, first_name, last_name, email, phone, answers, uploads)
	frappe.enqueue(
		"hrms.hr.careers.review.process_new_application",
		queue="short",
		applicant=applicant.name,
		updated=updated,
		enqueue_after_commit=True,
	)
	return {"ok": True, "updated": updated, "redirect": f"/{opening.route}?applied=1" if opening else thanks}


def _settings():
	return frappe.get_cached_doc("Careers Settings")


def _existing(email: str, opening) -> str | None:
	filters = {"email_id": email, "status": ("in", OPEN_STATUSES)}
	filters["job_title"] = opening.name if opening else ("is", "not set")
	return frappe.db.get_value("Job Applicant", filters, "name", order_by="creation desc")


def _store(opening, first_name, last_name, email, phone, answers, uploads):
	"""Create the applicant, or complete the open one for the same e-mail and opening."""
	settings = _settings()
	existing = _existing(email, opening)
	updated = bool(existing)

	if existing:
		applicant = frappe.get_doc("Job Applicant", existing)
		if phone:
			applicant.phone_number = phone
		applicant.set("careers_answers", [])
	else:
		applicant = frappe.new_doc("Job Applicant")
		applicant.update(
			{
				"applicant_name": f"{first_name} {last_name}",
				"email_id": email,
				"phone_number": phone,
				"job_title": opening.name if opening else None,
				"status": "Open",
				"careers_language": frappe.local.lang,
				**source_of(frappe.form_dict.get("utm_source"), frappe.form_dict.get("ref")),
			}
		)
		if not opening:
			# an unsolicited application has no decision to wait for: its clock starts now
			applicant.careers_retention_until = add_days(today(), cint(settings.retention_days) or 90)

	applicant.careers_privacy_consent_on = now_datetime()
	if _checked("talent_pool"):
		applicant.careers_talent_pool_until = add_months(today(), cint(settings.talent_pool_months) or 12)
	for answer in answers:
		applicant.append("careers_answers", answer)
	applicant.flags.ignore_permissions = True
	applicant.flags.from_careers_page = True
	if existing:
		applicant.save()
	else:
		applicant.insert()

	cv_url = applicant.get("resume_attachment") or None
	for row, file_name, content, _kind in uploads:
		is_first_cv = row.document_type == "CV" and not cv_url
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"content": content,
				"is_private": 1,
				"attached_to_doctype": "Job Applicant",
				"attached_to_name": applicant.name,
				# upstream's own CV field shows it too; naming the field keeps Frappe from attaching
				# the same file a second time when the applicant is saved
				"attached_to_field": "resume_attachment" if is_first_cv else None,
			}
		).insert(ignore_permissions=True)
		if is_first_cv:
			cv_url = file_doc.file_url
			applicant.resume_attachment = cv_url
		applicant.append(
			"careers_documents",
			{
				"document_type": row.document_type,
				"label": row.get("label") or "",
				"file": file_doc.file_url,
			},
		)

	applicant.careers_review_status = "Queued" if settings.ai_review_enabled else ""
	applicant.careers_review_attempts = 0
	applicant.careers_next_attempt = None
	applicant.save()
	return applicant, updated
