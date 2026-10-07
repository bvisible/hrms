# //// Neoffice — added file (no upstream equivalent): the context of /jobs, /jobs/<opening> and
# //// /jobs/apply, and the redirect of upstream's /job_application (neoffice-maintenance#1294).
"""The careers pages.

Served by route rules (hooks.website_route_rules) over upstream's own /jobs page, which stays in
the app untouched. They extend `templates/web.html`, so the site's header, page band and footer
dress them (Builder's site chrome); their body is ours, drawn with the site's design tokens and
role classes (`.u-btn`, `.u-card`, `.u-input`). The band receives the title, the introduction and
the trail; the page does not print the title a second time when the band already did.

A page that is not open answers 404 — the plugin is off, nothing is published, or this opening is
closed — and so does /careers itself, which is only the name of the template behind /jobs.
"""

import os

import frappe
from frappe import _
from frappe.utils import cint

from hrms.hr.careers import ROUTE_PREFIX, documents
from hrms.hr.careers.apply import make_token
from hrms.hr.careers.openings import (
	department_label,
	filter_options,
	get_open_opening,
	opening_facts,
	published_openings,
)
from hrms.hr.careers.plugin import accepts_spontaneous, page_is_open, plugin_enabled
from hrms.hr.careers.seo import description_text, job_posting_ld, json_ld, metatags
from hrms.hr.careers.share import copy_link, employee_ref, page_url, share_links

SPONTANEOUS_SLUG = "apply"
ASSETS = ("css/careers.css", "js/careers.js")


def _asset_url(relative: str) -> str:
	"""Cache-busted by modification time: /assets is served with a long max-age."""
	path = frappe.get_app_path("hrms", "public", relative)
	try:
		version = int(os.path.getmtime(path))
	except OSError:
		version = 0
	return f"/assets/hrms/{relative}?v={version}"


def _not_found():
	raise frappe.DoesNotExistError


def _guard(prefixes: tuple):
	path = (frappe.request.path if getattr(frappe.local, "request", None) else "").strip("/")
	if not any(path == p or path.startswith(p + "/") for p in prefixes):
		_not_found()


def _settings():
	return frappe.get_cached_doc("Careers Settings")


def _common(context):
	context.no_cache = 1
	context.careers_css, context.careers_js = (_asset_url(a) for a in ASSETS)
	context.applied = cint(frappe.form_dict.get("applied"))


def _card(opening) -> dict:
	return {
		"title": opening.job_title,
		"url": f"/{opening.route}",
		"facts": [
			f
			for f in opening_facts(opening)
			if f["key"] in ("location", "workload", "employment_type", "remote")
		],
		"excerpt": description_text(opening, 180),
	}


def list_context(context):
	_guard((ROUTE_PREFIX,))
	if not page_is_open():
		_not_found()
	_common(context)
	settings = _settings()

	chosen = {
		k: frappe.form_dict.get(k)
		for k in ("location", "department", "employment_type")
		if frappe.form_dict.get(k)
	}
	every = published_openings()
	shown = published_openings(chosen) if chosen else every

	context.title = settings.intro_title or _("Job openings")
	context.page_header_title = context.title
	context.page_header_subtitle = settings.intro_text or ""
	context.openings = [_card(o) for o in shown]
	context.filters = filter_options(every)
	context.chosen = chosen
	context.filter_labels = {
		"location": _("Job location"),
		"department": _("Department"),
		"employment_type": _("Contract"),
	}
	context.accept_spontaneous = accepts_spontaneous()
	context.spontaneous_url = f"/{ROUTE_PREFIX}/{SPONTANEOUS_SLUG}"
	context.metatags = {
		"title": context.title,
		"description": settings.intro_text or _("Our job openings, and how to apply online."),
		"og:type": "website",
		"og:url": page_url(ROUTE_PREFIX),
	}


def opening_context(context):
	_guard((ROUTE_PREFIX,))
	if not plugin_enabled():
		_not_found()
	slug = (frappe.form_dict.get("job_route") or "").strip("/")
	if slug == SPONTANEOUS_SLUG:
		return _spontaneous_context(context)

	opening = get_open_opening(f"{ROUTE_PREFIX}/{slug}")
	if not opening:
		_not_found()
	_common(context)
	settings = _settings()
	url = page_url(opening.route)
	ref = employee_ref()

	context.opening = opening
	context.title = opening.job_title
	context.page_header_title = opening.job_title
	context.page_header_subtitle = " · ".join(
		p for p in (opening.company, opening.location, department_label(opening.department)) if p
	)
	context.parents = [{"label": _("Job openings"), "route": ROUTE_PREFIX}]
	context.facts = opening_facts(opening)
	context.share = share_links(url, opening.job_title, ref)
	context.copy_link = copy_link(url, ref)
	context.employee_link = bool(ref)
	context.form = _form_context(opening, settings)
	context.others = [_card(o) for o in published_openings() if o.name != opening.name][:3]

	image = opening.get("careers_share_image")
	context.metatags = metatags(opening, image)
	context.jsonld = json_ld(job_posting_ld(opening, _logo_url()))


def _spontaneous_context(context):
	if not accepts_spontaneous():
		_not_found()
	_common(context)
	settings = _settings()
	context.opening = None
	context.title = _("Unsolicited application")
	context.page_header_title = context.title
	context.page_header_subtitle = _("No opening matches your profile today? Tell us about you.")
	context.parents = [{"label": _("Job openings"), "route": ROUTE_PREFIX}]
	context.facts = []
	context.share = []
	context.form = _form_context(None, settings)
	context.others = [_card(o) for o in published_openings()][:3]
	context.metatags = {
		"title": context.title,
		"og:type": "website",
		"og:url": page_url(f"{ROUTE_PREFIX}/{SPONTANEOUS_SLUG}"),
	}


def _form_context(opening, settings) -> dict:
	requested = documents.requested_documents(opening)
	return {
		"job_opening": opening.name if opening else "",
		"documents": [
			{
				"field": f"doc_{row.idx}",
				"label": documents.label_of(row),
				"required": cint(row.get("required")),
				"multiple": cint(row.get("allow_multiple")),
				"help": row.get("help") or "",
			}
			for row in requested
		],
		"questions": [
			{
				"field": f"answer_{row.idx}",
				"question": row.question,
				"type": row.answer_type,
				"required": cint(row.required),
				"options": [c.strip() for c in (row.options or "").split("\n") if c.strip()],
			}
			for row in ((opening.get("careers_questions") or []) if opening else [])
		],
		"privacy_notice": settings.privacy_notice or "",
		"talent_pool_months": cint(settings.talent_pool_months) or 12,
		"token": make_token(),
		"accept": documents.ACCEPT,
		"max_mb": documents.MAX_FILE_BYTES // (1024 * 1024),
		"utm_source": (frappe.form_dict.get("utm_source") or "")[:40],
		"ref": (frappe.form_dict.get("ref") or "")[:40],
	}


def _logo_url() -> str | None:
	from hrms.hr.careers.share_image import _theme

	logo = _theme().get("logo")
	if not logo:
		return None
	return logo if logo.startswith("http") else page_url(logo)


def legacy_context(context):
	"""Upstream's /job_application/new?job_title=<opening>: to the opening's page, or the list."""
	_guard(("job_application",))
	if not page_is_open():
		_not_found()
	target = f"/{ROUTE_PREFIX}"
	name = frappe.form_dict.get("job_title")
	if name:
		route = frappe.db.get_value("Job Opening", {"name": name, "publish": 1, "status": "Open"}, "route")
		if route:
			target = f"/{route}"
	frappe.local.flags.redirect_location = target
	raise frappe.Redirect
