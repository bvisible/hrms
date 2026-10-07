# //// Neoffice — added file (no upstream equivalent): the careers page as a website plugin, its
# //// switch and its menu entry (neoffice-maintenance#1294).
"""Whether the careers page exists, and its entry in the site's menu.

**Two places, one rule** (Jérémy, 2026-10-07). The site switches the `jobs` plugin on or off
(Builder's plugin registry; off answers 404 on /jobs by itself, `builder.plugins.route_guard`).
HR publishes or withdraws each opening. The page is open when the plugin is on AND something is
open: a published, open opening, or unsolicited applications. The same rule as /reserver:
a page with nothing to apply for promises a job that does not exist.

The menu follows the page, both ways: an entry left behind would lead to a 404, a page without its
entry is a page nobody finds. `neoffice_theme.website_features.menu_entry` writes it when the
theme is there (one implementation for the shop, the bookings, the courses and the jobs).
"""

import frappe

from hrms.hr.careers import PLUGIN_NAME, ROUTE_PREFIX

MENU_URL = f"/{ROUTE_PREFIX}"
MENU_LABEL = "Jobs"


def manifest() -> dict:
	"""Declared to Builder's plugin registry through the `unpress_plugins` hook.

	The registry stores the English texts and translates them when it shows them, so they are not
	translated here (see `_translatable_labels`).
	"""
	return {
		"plugin_name": PLUGIN_NAME,
		"title": "Jobs",
		"description": "Job openings published from HR, with online applications.",
		"app_name": "hrms",
		"icon": "lucide-briefcase",
		"route_prefix": ROUTE_PREFIX,
		"witness_doctype": "Job Opening",
	}


def _translatable_labels():
	"""Never called: lets the extractor see the registry's texts."""
	from frappe import _

	return (
		_("Jobs"),
		_("Job openings published from HR, with online applications."),
	)


def plugin_enabled() -> bool:
	"""True unless the site switched the plugin off.

	Defaults to True when no registry answers, as every plugin does: the registry takes a capability
	away, it never grants one. The registry lives in `builder` on our v15 fleet, `unpress_core` on
	Unpress.
	"""
	for module in ("builder.plugins", "unpress_core.plugins"):
		try:
			registry = frappe.get_module(module)
		except Exception:
			continue
		try:
			return bool(registry.is_enabled(PLUGIN_NAME))
		except Exception:
			return True
	return True


def accepts_spontaneous() -> bool:
	if not frappe.db.exists("DocType", "Careers Settings"):
		return False
	return bool(frappe.db.get_single_value("Careers Settings", "accept_spontaneous"))


def page_is_open() -> bool:
	from hrms.hr.careers.openings import has_open_openings

	if not plugin_enabled():
		return False
	return has_open_openings() or accepts_spontaneous()


def _menu_entry(on: bool):
	try:
		from neoffice_theme.website_features import menu_entry
	except ImportError:
		menu_entry = _local_menu_entry
	menu_entry(MENU_URL, MENU_LABEL, on)


def _local_menu_entry(url: str, label_en: str, on: bool):
	"""The theme's rule, for a site without it: idempotent on the URL, the label in the site's language."""
	from frappe import _

	settings = frappe.get_doc("Website Settings")
	present = [r for r in (settings.get("top_bar_items") or []) if (r.url or "").rstrip("/") == url]
	if on and not present:
		settings.append(
			"top_bar_items", {"label": _(label_en, lang=frappe.db.get_default("lang") or "fr"), "url": url}
		)
	elif not on and present:
		for row in present:
			settings.remove(row)
	else:
		return
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)


def sync_menu(*args, **kwargs):
	"""Put the menu entry where the page is. Safe to call from any hook: it never raises."""
	try:
		_menu_entry(page_is_open())
	except Exception:
		frappe.log_error("Careers page: menu entry not synced", frappe.get_traceback())
