# //// Neoffice — added file (no upstream equivalent): frank a Swiss payslip with a Swiss Post
# //// WebStamp, through the swisspost_barcode app when the site has it.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""WebStamp for a payslip mailed in a window envelope.

A WebStamp "franking + address" image carries the postage and the recipient address in one block
of 74 x 35 mm. The Swiss payslip prints it in the envelope window in place of the address lines
(salary_slip_swiss.html), so a slip can go to the post without an envelope to address or a stamp
to stick.

The order itself belongs to the swisspost_barcode app: its preview is free and never billed, its
order is billed by Swiss Post (on a test environment it falls back to a preview marked TEST).
This module only knows the payslip: who receives it, at which address, and who may frank it.
"""

import re

import frappe
from frappe import _

from hrms.regional.switzerland.permissions import check_payroll_staff
from hrms.regional.switzerland.utils import _parse_address, employee_salutation

APP = "swisspost_barcode"
# "8001 Zürich", "CH-8001 Zürich", "F-74100 Annemasse"
TOWN_LINE = re.compile(r"^(?:(?P<prefix>[A-Z]{1,2})-)?(?P<zip>\d{4,5})\s+(?P<city>.+)$")
# Country prefixes of a postcode line, as written on Swiss mail.
PREFIX_COUNTRY = {"CH": "CH", "FL": "LI", "F": "FR", "D": "DE", "I": "IT", "A": "AT"}
STANDARD_LETTER = "lettre standard"
# Swiss Post zones (the WebStamp get_zones list): a product serves one of them only, and an order
# whose address lies in another zone is refused ("une adresse ne peut pas être utilisée avec le
# produit sélectionné") — a payslip for a cross-border worker living in Germany needs an
# international letter, not an A-mail stamp.
EUROPE_ZONE, WORLD_ZONE, DOMESTIC_ZONE = 1, 2, 3
DOMESTIC = ("CH", "LI")
# Zone 1 when the WebStamp country list cannot be read — and for the names it spells its own way
# ("Grande-Bretagne", "Russie (Fédération de)"): the 52 countries of zone 1 in Swiss Post's
# "Documents et petites marchandises International — zone tarifaire et durées d'acheminement par
# pays" (2024), Russia and Turkey included.
EUROPE = {
	"AD", "AL", "AT", "AX", "BA", "BE", "BG", "BY", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FO",
	"FR", "GB", "GG", "GI", "GL", "GR", "HR", "HU", "IE", "IM", "IS", "IT", "JE", "LT", "LU", "LV",
	"MC", "MD", "ME", "MK", "MT", "NL", "NO", "PL", "PT", "RO", "RS", "RU", "SE", "SI", "SK", "SM",
	"TR", "UA", "VA", "XK",
}  # fmt: skip
# An international standard letter up to 20 g, "Documents Std 20g Z1" (a payslip weighs 5 to 10 g).
INTERNATIONAL_LETTER = "documents std 20g"


def payslip_recipient(slip):
	"""The postal recipient of a payslip as WebStamp takes it.

	Returns name (salutation and name, within the 35 characters of the field), street, zip, city
	and country from the employee's postal address, whose last "postcode town" line gives zip and
	city and whose first line the street; missing fields stay empty for the caller to refuse.
	"""
	employee = frappe.get_cached_doc("Employee", slip.employee)
	name = " ".join(part for part in (employee_salutation(employee), slip.employee_name) if part)
	if len(name) > 35:
		name = (slip.employee_name or "")[:35]
	lines = _parse_address(employee)
	recipient = {"name": name, "street": "", "zip": "", "city": "", "country": "CH"}
	town_index = None
	for index in range(len(lines) - 1, -1, -1):
		match = TOWN_LINE.match(lines[index])
		if match:
			town_index = index
			recipient["zip"], recipient["city"] = match.group("zip"), match.group("city").strip()
			if match.group("prefix"):
				recipient["country"] = PREFIX_COUNTRY.get(match.group("prefix"), "CH")
			break
	street_lines = lines[:town_index] if town_index is not None else lines
	if street_lines:
		recipient["street"] = street_lines[0]
	residence = (employee.get("ch_residence_country") or "").strip().upper()
	if len(residence) == 2 and recipient["country"] == "CH":
		recipient["country"] = residence
	# The order record links a Country by its name ("Switzerland"), the API takes the code.
	recipient["country_name"] = (
		frappe.db.get_value("Country", {"code": recipient["country"].lower()}, "name") or "Switzerland"
	)
	return recipient


def recipient_zone(country, config=None):
	"""The Swiss Post zone of a recipient country: domestic, Europe (1) or the other countries (2)."""
	code = (country or "CH").upper()
	if code in DOMESTIC:
		return DOMESTIC_ZONE
	zones = _country_zones(config) if config else {}
	return zones.get(code) or (EUROPE_ZONE if code in EUROPE else WORLD_ZONE)


def _country_zones(config):
	"""ISO code -> zone, from the WebStamp country list, cached for a day.

	The list gives names only, in the service's language ("Allemagne"): they are matched to codes
	through the territory names Babel (a Frappe dependency) knows in the national languages.
	"""
	key = f"hrms_webstamp_zones_{config}"
	zones = frappe.cache.get_value(key)
	if zones is not None:
		return zones
	zones = {}
	try:
		from babel import Locale
		from swisspost_barcode.swisspost_barcode.webstamp.client import WebstampClient

		codes = {}
		for language in ("fr", "de", "it", "en"):
			for code, name in Locale(language).territories.items():
				if len(code) == 2 and code.isalpha():
					codes.setdefault(name.casefold(), code)
		for country in WebstampClient(config).get_countries():
			code = (country.get("code") or "").upper() or codes.get((country.get("name") or "").casefold())
			if code and country.get("zone"):
				zones[code] = int(country["zone"])
	except Exception:
		# The static European list stands in; said once an hour, not at every payslip.
		frappe.log_error("WebStamp country zones unavailable", frappe.get_traceback())
		frappe.cache.set_value(key, {}, expires_in_sec=3600)
		return {}
	frappe.cache.set_value(key, zones, expires_in_sec=86400)
	return zones


def letter_products(products, zone):
	"""The catalogue's standard letters for a zone, the plain one (no registered or other option)
	first: A- and B-mail letters at home, "Documents Std 20g Z1/Z2" abroad."""

	def serves(product):
		name = (product.get("product_name") or "").lower()
		if zone == DOMESTIC_ZONE:
			return STANDARD_LETTER in name
		return name.startswith(INTERNATIONAL_LETTER) and f"z{zone}" in name.split()

	chosen = [p for p in products if serves(p)]
	# Stable sort: the catalogue's own order (favourites first) within plain, then optioned.
	return sorted(chosen, key=lambda p: "&" in (p.get("product_name") or ""))


def _slip_for_payroll_staff(salary_slip):
	slip = frappe.get_doc("Salary Slip", salary_slip)
	check_payroll_staff(slip.company)
	return slip


def _require_app():
	if APP not in frappe.get_installed_apps() or not frappe.db.table_exists("SwissPost Webstamp Settings"):
		frappe.throw(_("WebStamp needs the Swiss Post app (swisspost_barcode) on this site."))
	from swisspost_barcode.swisspost_barcode.doctype.swisspost_webstamp_settings.swisspost_webstamp_settings import (
		get_default_config,
	)

	config = get_default_config()
	if not config:
		frappe.throw(_("Set up one WebStamp configuration (SwissPost Webstamp Settings) to frank payslips."))
	return config


@frappe.whitelist()
def get_stamp_options(salary_slip):
	"""What the franking dialog shows: the recipient, the standard-letter products and the stamp
	already ordered for this slip."""
	slip = _slip_for_payroll_staff(salary_slip)
	config = _require_app()
	from hrms.regional.switzerland.utils import get_webstamp_image

	recipient = payslip_recipient(slip)
	zone = recipient_zone(recipient["country"], config)
	return {
		"config": config,
		"environment": _environment(config),
		"recipient": recipient,
		"zone": zone,
		"products": letter_products(_catalogue(config), zone),
		"stamp_url": get_webstamp_image(slip),
		"submitted": slip.docstatus == 1,
	}


def _catalogue(config):
	"""The live WebStamp product catalogue (swisspost_barcode, cached there for an hour)."""
	from swisspost_barcode.swisspost_barcode.doctype.swisspost_webstamp_settings.swisspost_webstamp_settings import (
		get_webstamp_products,
	)

	return get_webstamp_products(config)


def _environment(config):
	"""Production bills the stamps; the test environment answers with a preview marked TEST."""
	return frappe.db.get_value("SwissPost Webstamp Settings", config, "environment")


@frappe.whitelist(methods=["POST"])
def stamp_salary_slip(salary_slip, product_number, product_name=None, product_price=None, preview=1):
	"""Preview (free) or order (billed by Swiss Post) the WebStamp of a payslip.

	The order is linked to the slip, whose Swiss print then shows it in the envelope window. Only a
	submitted slip is franked: its amounts no longer change.
	"""
	slip = _slip_for_payroll_staff(salary_slip)
	config = _require_app()
	preview = frappe.utils.cint(preview)
	if not preview and slip.docstatus != 1:
		frappe.throw(_("Only a submitted salary slip can be franked."))
	recipient = payslip_recipient(slip)
	if not (recipient["street"] and recipient["zip"] and recipient["city"]):
		frappe.throw(
			_(
				"The postal address of {0} is incomplete: a street line and a postcode and town line are needed."
			).format(slip.employee_name)
		)
	from swisspost_barcode.swisspost_barcode.doctype.swisspost_webstamp_order.swisspost_webstamp_order import (
		order_stamp,
		preview_stamp,
	)

	args = {
		"config": config,
		"product_number": product_number,
		"product_name": product_name,
		"recipient_name": recipient["name"],
		"recipient_street": recipient["street"],
		"recipient_zip": recipient["zip"],
		"recipient_city": recipient["city"],
		"recipient_country": recipient["country_name"],
		"reference": slip.name,
	}
	if preview:
		return preview_stamp(**args)
	return order_stamp(
		**args, product_price=product_price, document_type="Salary Slip", document_name=slip.name
	)
