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
from frappe.utils import cint

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


def plugin_enabled(fresh: bool = False) -> bool:
	"""True unless the site switched the plugin off.

	Defaults to True when no registry answers, as every plugin does: the registry takes a capability
	away, it never grants one. The registry lives in `builder` on our v15 fleet, `unpress_core` on
	Unpress.

	`fresh` reads the registry row in this transaction instead of the registry's cache: the menu is
	synced while the switch is being saved, and a request served meanwhile can put the old state back
	in the cache (measured on osiris, 2026-10-07).
	"""
	if fresh and frappe.db.exists("DocType", "Website Plugin"):
		enabled = frappe.db.get_value("Website Plugin", PLUGIN_NAME, "enabled")
		return True if enabled is None else bool(enabled)
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


def switchable() -> bool:
	"""The site's plugin registry holds the jobs page, so HR's settings may switch it too."""
	return bool(frappe.db.exists("DocType", "Website Plugin")) and bool(
		frappe.db.exists("Website Plugin", PLUGIN_NAME)
	)


def accepts_spontaneous() -> bool:
	if not frappe.db.exists("DocType", "Careers Settings"):
		return False
	return bool(frappe.db.get_single_value("Careers Settings", "accept_spontaneous"))


def page_state() -> dict:
	"""What HR's settings say of the page: switched on or off, open or not, and why."""
	from hrms.hr.careers.openings import published_openings
	from hrms.hr.careers.share import page_url

	enabled = plugin_enabled(fresh=True)
	published = len(published_openings())
	spontaneous = accepts_spontaneous()
	return {
		"switchable": switchable(),
		"enabled": enabled,
		"open": enabled and bool(published or spontaneous),
		"published": published,
		"spontaneous": spontaneous,
		"url": page_url(ROUTE_PREFIX),
	}


@frappe.whitelist(methods=["POST"])
def set_page_enabled(enabled) -> dict:
	"""Switch the jobs page on or off from HR's settings.

	The very switch of the website's plugins, not a copy of it (Jérémy, 2026-10-07: « deux endroits
	où on gère ça »): two flags would end up disagreeing. The plugin's own hooks then forget the
	registry's cache and move the menu entry (events.website_plugin_on_update).
	"""
	from frappe import _

	frappe.has_permission("Careers Settings", "write", throw=True)
	if not switchable():
		frappe.throw(_("This site has no plugin registry: its jobs page cannot be switched off."))
	plugin = frappe.get_doc("Website Plugin", PLUGIN_NAME)
	plugin.enabled = 1 if cint(enabled) else 0
	plugin.save(ignore_permissions=True)
	return page_state()


def page_is_open(company: str | None = None, fresh: bool = False) -> bool:
	"""Open for the site being browsed, or for a given company (a site of a multi-site instance)."""
	from hrms.hr.careers.openings import has_open_openings

	if not plugin_enabled(fresh):
		return False
	return has_open_openings(company) or accepts_spontaneous()


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


def _variant_menus():
	"""The menu of each site of a multi-site instance.

	A site served through a Website Profile draws the menu of its header/footer variant, which
	neither the theme's `menu_entry` nor Builder's own sync touches: on such a site the entry was
	written to the main menu and the page still had none (measured on osiris, 2026-10-07). Each
	variant gets the entry when the page is open for its profile's company.
	"""
	if not frappe.db.exists("DocType", "Website Header Footer Variant"):
		return
	from frappe import _

	site_lang = frappe.db.get_default("lang") or "fr"
	for row in frappe.get_all("Website Header Footer Variant", fields=["name", "website_profile"]):
		company, lang = None, site_lang
		if row.website_profile:
			company, lang = frappe.db.get_value(
				"Website Profile", row.website_profile, ["careers_company", "language"]
			) or (None, None)
			lang = lang or site_lang
		on = page_is_open(company, fresh=True)
		variant = frappe.get_doc("Website Header Footer Variant", row.name)
		present = [r for r in variant.get("menu_items") or [] if (r.url or "").rstrip("/") == MENU_URL]
		if on and not present:
			variant.append("menu_items", {"label": _(MENU_LABEL, lang=lang), "url": MENU_URL})
		elif not on and present:
			for item in present:
				variant.remove(item)
		else:
			continue
		variant.flags.ignore_permissions = True
		variant.save(ignore_permissions=True)


def sync_menu(*args, **kwargs):
	"""Put the menu entry where the page is, on the main site and on each site of a multi-site
	instance. Safe to call from any hook: it never raises."""
	try:
		_menu_entry(page_is_open(fresh=True))
		_variant_menus()
	except Exception:
		frappe.log_error("Careers page: menu entry not synced", frappe.get_traceback())
