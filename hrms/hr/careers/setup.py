# //// Neoffice — added file (no upstream equivalent): the careers page's fields and defaults
# //// (neoffice-maintenance#1294). Custom Fields, like the Swiss payroll's: nothing is written into
# //// an upstream DocType JSON, so an upstream merge never fights over them.
import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# The channels a share link names (`utm_source`), as Job Applicant Sources. "Website Listing" is
# upstream's own and stays the source of an application that names none.
SOURCES = ("LinkedIn", "WhatsApp", "Facebook", "X", "E-mail", "Google")


def get_custom_fields() -> dict:
	return {
		"Job Opening": [
			{
				"fieldname": "careers_section",
				"fieldtype": "Section Break",
				"label": "Jobs page",
				"insert_after": "description",
			},
			{
				"fieldname": "careers_workload_min",
				"fieldtype": "Int",
				"label": "Workload from (%)",
				"insert_after": "careers_section",
			},
			{
				"fieldname": "careers_workload_max",
				"fieldtype": "Int",
				"label": "Workload to (%)",
				"insert_after": "careers_workload_min",
			},
			{
				"fieldname": "careers_remote_policy",
				"fieldtype": "Select",
				"label": "Place of work",
				"options": "\nOn site\nHybrid\nRemote",
				"insert_after": "careers_workload_max",
			},
			{
				"fieldname": "careers_column_1",
				"fieldtype": "Column Break",
				"insert_after": "careers_remote_policy",
			},
			{
				"fieldname": "careers_start_option",
				"fieldtype": "Select",
				"label": "Starting date",
				"options": "\nImmediately\nTo be agreed\nOn a date",
				"insert_after": "careers_column_1",
			},
			{
				"fieldname": "careers_start_on",
				"fieldtype": "Date",
				"label": "Starting on",
				"depends_on": "eval:doc.careers_start_option=='On a date'",
				"insert_after": "careers_start_option",
			},
			{
				"fieldname": "careers_recruiter",
				"fieldtype": "Link",
				"label": "Recruiter",
				"options": "User",
				"description": "Receives each application by e-mail.",
				"insert_after": "careers_start_on",
			},
			{
				"fieldname": "careers_documents_section",
				"fieldtype": "Section Break",
				"label": "What the applicant sends",
				"insert_after": "careers_recruiter",
			},
			{
				"fieldname": "careers_documents",
				"fieldtype": "Table",
				"label": "Documents requested",
				"options": "Job Opening Document",
				"description": "One upload field per line on the application form. Empty: a CV, required.",
				"insert_after": "careers_documents_section",
			},
			{
				"fieldname": "careers_questions",
				"fieldtype": "Table",
				"label": "Questions to the applicant",
				"options": "Job Opening Question",
				"insert_after": "careers_documents",
			},
			{
				"fieldname": "careers_criteria_section",
				"fieldtype": "Section Break",
				"label": "Reading criteria",
				"collapsible": 1,
				"insert_after": "careers_questions",
			},
			{
				"fieldname": "careers_criteria",
				"fieldtype": "Table",
				"label": "Criteria",
				"options": "Job Opening Criterion",
				"description": "Nora reads every application to this opening against these criteria. "
				"Empty: Nora proposes some from the description at the first application.",
				"insert_after": "careers_criteria_section",
			},
			{
				"fieldname": "careers_criteria_reviewed",
				"fieldtype": "Check",
				"label": "Criteria reviewed by a person",
				"read_only": 1,
				"description": "Off while the criteria are the ones Nora proposed and nobody has saved them.",
				"insert_after": "careers_criteria",
			},
			{
				"fieldname": "careers_criteria_changed_on",
				"fieldtype": "Datetime",
				"hidden": 1,
				"read_only": 1,
				"insert_after": "careers_criteria_reviewed",
			},
			{
				"fieldname": "careers_share_image",
				"fieldtype": "Attach Image",
				"label": "Share picture",
				"read_only": 1,
				"insert_after": "careers_criteria_changed_on",
			},
			{
				"fieldname": "careers_share_image_key",
				"fieldtype": "Data",
				"hidden": 1,
				"read_only": 1,
				"insert_after": "careers_share_image",
			},
		],
		"Job Applicant": [
			{
				"fieldname": "careers_review_section",
				"fieldtype": "Section Break",
				"label": "Reading by Nora",
				"insert_after": "status",
			},
			{
				"fieldname": "careers_review_html",
				"fieldtype": "HTML",
				"label": "Reading",
				"insert_after": "careers_review_section",
			},
			{
				"fieldname": "careers_review_status",
				"fieldtype": "Select",
				"label": "Reading",
				"options": "\nQueued\nDone\nFailed",
				"read_only": 1,
				"hidden": 1,
				"insert_after": "careers_review_html",
			},
			{
				# shown in the list; the form draws them in the reading card instead (careers_job_applicant.js)
				"fieldname": "careers_score",
				"fieldtype": "Int",
				"label": "Score",
				"read_only": 1,
				"in_list_view": 1,
				"insert_after": "careers_review_status",
			},
			{
				"fieldname": "careers_completeness",
				"fieldtype": "Int",
				"label": "Completeness (%)",
				"read_only": 1,
				"in_list_view": 1,
				"insert_after": "careers_score",
			},
			{
				"fieldname": "careers_summary",
				"fieldtype": "Small Text",
				"label": "Summary",
				"read_only": 1,
				"hidden": 1,
				"insert_after": "careers_completeness",
			},
			{
				"fieldname": "careers_review",
				"fieldtype": "Link",
				"label": "Last reading",
				"options": "Job Applicant Review",
				"read_only": 1,
				"hidden": 1,
				"insert_after": "careers_summary",
			},
			{
				"fieldname": "careers_review_attempts",
				"fieldtype": "Int",
				"read_only": 1,
				"hidden": 1,
				"insert_after": "careers_review",
			},
			{
				"fieldname": "careers_next_attempt",
				"fieldtype": "Datetime",
				"read_only": 1,
				"hidden": 1,
				"insert_after": "careers_review_attempts",
			},
			{
				"fieldname": "careers_application_section",
				"fieldtype": "Section Break",
				"label": "Application",
				"insert_after": "careers_next_attempt",
			},
			{
				"fieldname": "careers_documents",
				"fieldtype": "Table",
				"label": "Documents received",
				"options": "Job Applicant Document",
				"insert_after": "careers_application_section",
			},
			{
				"fieldname": "careers_answers",
				"fieldtype": "Table",
				"label": "Answers",
				"options": "Job Applicant Answer",
				"insert_after": "careers_documents",
			},
			{
				"fieldname": "careers_privacy_section",
				"fieldtype": "Section Break",
				"label": "Data protection",
				"collapsible": 1,
				"insert_after": "careers_answers",
			},
			{
				"fieldname": "careers_privacy_consent_on",
				"fieldtype": "Datetime",
				"label": "Information accepted on",
				"read_only": 1,
				"insert_after": "careers_privacy_section",
			},
			{
				"fieldname": "careers_talent_pool_until",
				"fieldtype": "Date",
				"label": "Kept for other openings until",
				"description": "Only with the applicant's agreement.",
				"insert_after": "careers_privacy_consent_on",
			},
			{
				"fieldname": "careers_column_1",
				"fieldtype": "Column Break",
				"insert_after": "careers_talent_pool_until",
			},
			{
				"fieldname": "careers_retention_until",
				"fieldtype": "Date",
				"label": "Deleted on",
				"description": "Set when the application is rejected or the opening closed.",
				"insert_after": "careers_column_1",
			},
			{
				"fieldname": "careers_decision_reason",
				"fieldtype": "Small Text",
				"label": "Reason for the decision",
				"description": "Kept for the applicant who asks for it in writing (Gender Equality Act, art. 8).",
				"depends_on": "eval:in_list(['Rejected', 'Accepted'], doc.status)",
				"insert_after": "careers_retention_until",
			},
			{
				"fieldname": "careers_language",
				"fieldtype": "Data",
				"hidden": 1,
				"read_only": 1,
				"insert_after": "careers_decision_reason",
			},
			{
				"fieldname": "careers_acknowledged_on",
				"fieldtype": "Datetime",
				"hidden": 1,
				"read_only": 1,
				"insert_after": "careers_language",
			},
			{
				"fieldname": "careers_recruiter_notified_on",
				"fieldtype": "Datetime",
				"hidden": 1,
				"read_only": 1,
				"insert_after": "careers_acknowledged_on",
			},
		],
	}


def _website_profile_fields() -> dict:
	"""A site of a multi-site instance lists the openings of its own company only."""
	if not frappe.db.exists("DocType", "Website Profile"):
		return {}
	meta = frappe.get_meta("Website Profile")
	anchor = meta.fields[-1].fieldname if meta.fields else None
	return {
		"Website Profile": [
			{
				"fieldname": "careers_company",
				"fieldtype": "Link",
				"label": "Company of the jobs page",
				"options": "Company",
				"description": "Empty: the jobs page lists the openings of every company.",
				"insert_after": anchor,
			}
		]
	}


def make_custom_fields(update: bool = True):
	create_custom_fields(get_custom_fields(), update=update)

	# Website Profile belongs to the theme, and links to Builder Page: on a bench where Builder is
	# missing (hrms's CI), adding a field re-validates that doctype and fails on its own link. The
	# field is a convenience for multi-site instances; it must never stop an install.
	extra = _website_profile_fields()
	if not extra:
		return
	frappe.db.savepoint("careers_website_profile")
	try:
		create_custom_fields(extra, update=update)
	except Exception:
		frappe.db.rollback(save_point="careers_website_profile")
		frappe.log_error("Careers page: Website Profile field not created", frappe.get_traceback())


def ensure_sources():
	for source in SOURCES:
		if not frappe.db.exists("Job Applicant Source", source):
			frappe.get_doc({"doctype": "Job Applicant Source", "source_name": source}).insert(
				ignore_permissions=True
			)


def default_privacy_notice(lang: str | None = None) -> str:
	return _(
		"Your application is read by the people in charge of recruitment, with the help of Nora, an "
		"artificial intelligence hosted on our own servers in Switzerland, which summarises it. No "
		"decision is taken automatically. Your data serves this recruitment only and is deleted "
		"three months after the decision, unless you agree that we keep it for other openings.",
		lang=lang,
	)


def ensure_settings():
	if not frappe.db.exists("DocType", "Careers Settings"):
		return
	settings = frappe.get_single("Careers Settings")
	changed = False
	lang = frappe.db.get_default("lang") or "fr"
	english, wanted = default_privacy_notice("en"), default_privacy_notice(lang)
	# a notice written before its translation existed was stored in English: put it in the site's language
	if not settings.privacy_notice or (settings.privacy_notice == english and wanted != english):
		settings.privacy_notice = wanted
		changed = True
	if not settings.retention_days:
		settings.retention_days = 90
		changed = True
	if not settings.talent_pool_months:
		settings.talent_pool_months = 12
		changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.flags.from_setup = True
		settings.save()


# Nora's button of the text editor (nora/api/text_editor.py) reads a prompt per DocType and field
# ("AI Text Editor Prompt"): on an opening's description it writes like a careers page.
# The first version, kept to recognise it on a site and replace it: a prompt a customer edited is
# never touched.
JOB_AD_PROMPT_V1 = """You edit the description of a job opening published on the careers page of a Swiss employer.

Layout: a short opening paragraph (the role in one or two sentences), then sections with <h3> headings — the tasks, the profile sought, what the employer offers, the practical details (workload, start, place) — each as a list of short <ul><li> items. Plain, direct and warm language; the reader is addressed as "vous" in French and "Sie" in German.

Never invent: a fact that is not in the text (salary, benefits, years of experience, a diploma, a date) is not added.
Lawful and inclusive: the job title names all genders (e.g. "Comptable (H/F/X)") or uses an epicene form; no requirement on age, sex, origin, nationality, family status or photo — leave such a requirement out.
When asked to translate, translate faithfully into the language requested and keep the layout, with the Swiss terms of that language (taux d'activité / Pensum / grado di occupazione, entrée en fonction / Stellenantritt / entrata in servizio).
Unless asked to translate, write in the language of the text."""

JOB_AD_PROMPT_MARK = "[hrms job-ad prompt v3]"

JOB_AD_PROMPT = """You edit the description of a job opening published on the careers page of a Swiss employer.

Output an HTML fragment. No title line and no <h1> or <h2>: the page prints the job title itself. Start with a short opening paragraph (the role and the team in one or two sentences), then sections with <h3> headings — the tasks, the profile sought, what the employer offers, the practical details (workload, start, place) — each a list of short <ul><li> items. Leave out a section the text says nothing about.

Never add anything the text does not state: no requirement, skill, quality, diploma, certificate, benefit, salary or date — not even a usual one ("autonomie", "rigueur", "expérience confirmée"). You may reword and reorder; you may not enrich.
Swiss vocabulary: CFC, AFP, brevet fédéral, permis de cariste, taux d'activité; never terms of France only (CACES, BTS, Bac+2).
Lawful and inclusive: name the job for every gender in the sentences ("un ou une magasinier·ère") and the title with "(H/F/X)" or an epicene form; no requirement on age, sex, origin, nationality, family status or photo — leave such a requirement out.
Plain, direct and warm language; the reader is addressed as "vous" in French and "Sie" in German.
When asked to translate, translate faithfully into the language requested, sentence by sentence, and keep every tag (each <li> stays a <li>):
- every fact stays as it is, the languages a position requires above all: "très bonne maîtrise du français, allemand un plus" becomes "sehr gute Französischkenntnisse, Deutsch von Vorteil", never the other way round;
- Swiss names of that language: CFC / EFZ / AFC, AFP / EBA / CFP, brevet fédéral / eidgenössischer Fachausweis / attestato professionale federale, diplôme fédéral / eidgenössisches Diplom / diploma federale, AVS / AHV / AVS, LPP / BVG / LPP, taux d'activité / Pensum / grado di occupazione, entrée en fonction / Stellenantritt / entrata in servizio.
Unless asked to translate, write in the language of the text.
{mark}""".replace("{mark}", JOB_AD_PROMPT_MARK)


def ensure_text_editor_prompt():
	"""Created when missing; our own earlier versions are brought up to date; a prompt the customer
	edited is never touched.

	Written with `frappe.db.set_value`, never through the form: the prompt names the tags it wants
	(<h3>, <ul><li>) and the HTML sanitizer of a save closes them at its end, so version 1 stored
	« …</li></ul></h3> », stopped matching itself and was never upgraded (osiris, 2026-10-08). The
	domain is "" and never NULL: Nora looks a prompt up with `domain in ("", None)`, which in SQL never
	matches a NULL, and the editor fell back on its generic instruction.
	"""
	if not frappe.db.exists("DocType", "AI Text Editor Prompt"):
		return
	lang = frappe.db.get_default("lang") or "fr"
	values = {
		"enabled": 1,
		"domain": "",
		"placeholder": _("Describe the job in a few lines: Nora lays it out like a job ad.", lang=lang),
		"default_instruction": _(
			"Lay out this job ad: an introduction, the tasks, the profile, what we offer. Add nothing the text does not say.",
			lang=lang,
		),
		"system_prompt": JOB_AD_PROMPT,
	}
	name = frappe.db.get_value(
		"AI Text Editor Prompt", {"doctype_link": "Job Opening", "fieldname": "description"}
	)
	if not name:
		doc = frappe.get_doc(
			{
				"doctype": "AI Text Editor Prompt",
				"doctype_link": "Job Opening",
				"fieldname": "description",
				**values,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("AI Text Editor Prompt", doc.name, values, update_modified=False)
		return
	current = frappe.db.get_value("AI Text Editor Prompt", name, list(values), as_dict=True)
	prompt = (current.system_prompt or "").strip()
	ours = "[hrms job-ad prompt v" in prompt or prompt.startswith(JOB_AD_PROMPT_V1.strip()[:300])
	# compared as stored: a NULL domain is a difference to write, not an empty string
	if ours and any(current.get(key) != value for key, value in values.items()):
		frappe.db.set_value("AI Text Editor Prompt", name, values)


def after_migrate():
	make_custom_fields()
	ensure_sources()
	ensure_settings()
	try:
		ensure_text_editor_prompt()
	except Exception:
		# the prompt is a help: a missing one must not stop a migrate
		frappe.log_error("Careers page: text editor prompt not created", frappe.get_traceback())


def _translatable_labels():
	"""Never called: lets the extractor see the Custom Fields' labels, descriptions and options,
	which Frappe translates when it shows them."""
	return (
		_("Jobs page"),
		_("Workload from (%)"),
		_("Workload to (%)"),
		_("Place of work"),
		_("On site"),
		_("Hybrid"),
		_("Remote"),
		_("Starting date"),
		_("Immediately"),
		_("To be agreed"),
		_("On a date"),
		_("Starting on"),
		_("Recruiter"),
		_("Receives each application by e-mail."),
		_("What the applicant sends"),
		_("Documents requested"),
		_("One upload field per line on the application form. Empty: a CV, required."),
		_("Questions to the applicant"),
		_("Reading criteria"),
		_("Criteria"),
		_(
			"Nora reads every application to this opening against these criteria. Empty: Nora proposes some from the description at the first application."
		),
		_("Criteria reviewed by a person"),
		_("Off while the criteria are the ones Nora proposed and nobody has saved them."),
		_("Share picture"),
		_("Reading by Nora"),
		_("Reading"),
		_("Queued"),
		_("Done"),
		_("Failed"),
		_("Score"),
		_("Completeness (%)"),
		_("Summary"),
		_("Last reading"),
		_("Application"),
		_("Documents received"),
		_("Answers"),
		_("Data protection"),
		_("Information accepted on"),
		_("Kept for other openings until"),
		_("Only with the applicant's agreement."),
		_("Deleted on"),
		_("Set when the application is rejected or the opening closed."),
		_("Reason for the decision"),
		_("Kept for the applicant who asks for it in writing (Gender Equality Act, art. 8)."),
		_("Company of the jobs page"),
		_("Empty: the jobs page lists the openings of every company."),
	)
