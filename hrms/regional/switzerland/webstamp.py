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
	from swisspost_barcode.swisspost_barcode.doctype.swisspost_webstamp_settings.swisspost_webstamp_settings import (
		get_webstamp_products,
	)

	from hrms.regional.switzerland.utils import get_webstamp_image

	products = [
		p for p in get_webstamp_products(config) if STANDARD_LETTER in (p.get("product_name") or "").lower()
	]
	return {
		"config": config,
		"environment": frappe.db.get_value("SwissPost Webstamp Settings", config, "environment"),
		"recipient": payslip_recipient(slip),
		"products": products,
		"stamp_url": get_webstamp_image(slip),
		"submitted": slip.docstatus == 1,
	}


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
