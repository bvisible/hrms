# //// Neoffice — added file (no upstream equivalent): tests of the payslip WebStamp (webstamp.py).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import base64
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import webstamp
from hrms.regional.switzerland.utils import get_webstamp_image
from hrms.regional.switzerland.webstamp import payslip_recipient

# A 1 x 1 PNG: the stamp file the lookup finds, not an image anyone looks at.
PIXEL = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


class TestPayslipRecipient(FrappeTestCase):
	"""Who receives a payslip by post, read from the employee's postal address."""

	def setUp(self):
		company = frappe.db.get_value("Company", {}, "name")
		self.employee = (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "Stamp",
					"last_name": "Recipient",
					"company": company,
					"gender": _male_gender(),
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"status": "Active",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		self.addCleanup(frappe.db.rollback)

	def _recipient(self, address, **employee):
		frappe.db.set_value("Employee", self.employee, {"permanent_address": address, **employee})
		frappe.clear_document_cache("Employee", self.employee)
		return payslip_recipient(frappe._dict(employee=self.employee, employee_name="Stamp Recipient"))

	def test_street_and_town_of_a_swiss_address(self):
		recipient = self._recipient("Bahnhofstrasse 10\n8001 Zürich")
		self.assertEqual(
			(recipient["street"], recipient["zip"], recipient["city"], recipient["country"]),
			("Bahnhofstrasse 10", "8001", "Zürich", "CH"),
		)
		# The order record links the Country by name: "CH" alone was refused ("Country CH not found").
		self.assertEqual(recipient["country_name"], frappe.db.get_value("Country", {"code": "ch"}, "name"))
		self.assertTrue(recipient["name"].endswith("Stamp Recipient"))  # after the salutation

	def test_a_country_prefix_or_the_residence_gives_the_country(self):
		self.assertEqual(self._recipient("Rue des Alpes 3\nF-74100 Annemasse")["country"], "FR")
		recipient = self._recipient("Rue des Alpes 3\n74100 Annemasse", ch_residence_country="FR")
		self.assertEqual((recipient["zip"], recipient["country"]), ("74100", "FR"))

	def test_an_address_without_a_town_line_leaves_zip_and_city_empty(self):
		"""The order refuses such a recipient instead of stamping an undeliverable letter."""
		recipient = self._recipient("Bahnhofstrasse 10")
		self.assertEqual((recipient["zip"], recipient["city"]), ("", ""))


class TestTheStampOfASlip(FrappeTestCase):
	"""The print finds the stamp ordered for the slip and puts it in the envelope window."""

	SLIP = "_Test WebStamp Slip"

	def test_the_stamp_attached_to_the_slip_is_found(self):
		self.assertIsNone(get_webstamp_image(frappe._dict(doctype="Salary Slip", name=self.SLIP)))
		stamp = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "stamp_TEST-webstamp-slip.png",
				"attached_to_doctype": "Salary Slip",
				"attached_to_name": self.SLIP,
				"content": PIXEL,
				"is_private": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "File", stamp.name, force=True, ignore_permissions=True)
		self.assertEqual(
			get_webstamp_image(frappe._dict(doctype="Salary Slip", name=self.SLIP)), stamp.file_url
		)


# A slice of the WebStamp catalogue, as get_webstamp_products returns it (names in French).
CATALOGUE = [
	{"product_number": 38610, "product_name": "Courrier A Lettre standard", "price": 1.2},
	{"product_number": 38617, "product_name": "Courrier B Lettre standard", "price": 1.0},
	{"product_number": 38611, "product_name": "Courrier A Lettre standard & pj", "price": 1.7},
	{"product_number": 38635, "product_name": "Courrier B standard en nombre", "price": 0.64},
	{"product_number": 38642, "product_name": "Documents Std 20g Z1 & R", "price": 8.7},
	{"product_number": 38641, "product_name": "Documents Std 20g Z1", "price": 2.3},
	{"product_number": 38647, "product_name": "Documents Std 50g Z1 ", "price": 3.1},
	{"product_number": 38695, "product_name": "Documents Std 20g Z2", "price": 2.5},
	{"product_number": 38616, "product_name": "Grande lettre A (001 - 1000g)", "price": 2.5},
]


class TestPostalZones(FrappeTestCase):
	"""A product serves one Swiss Post zone: an A-mail stamp is refused for an address in Germany."""

	def test_the_zone_of_a_country(self):
		self.assertEqual(webstamp.recipient_zone("CH"), webstamp.DOMESTIC_ZONE)
		self.assertEqual(webstamp.recipient_zone("li"), webstamp.DOMESTIC_ZONE)
		self.assertEqual(webstamp.recipient_zone("DE"), webstamp.EUROPE_ZONE)
		self.assertEqual(webstamp.recipient_zone("US"), webstamp.WORLD_ZONE)
		# Swiss Post's zone 1 reaches beyond the EU: Turkey and Russia are in it.
		self.assertEqual(webstamp.recipient_zone("TR"), webstamp.EUROPE_ZONE)
		self.assertEqual(webstamp.recipient_zone("RU"), webstamp.EUROPE_ZONE)
		# The WebStamp country list decides over the static European list.
		with patch.object(webstamp, "_country_zones", return_value={"US": 1}):
			self.assertEqual(webstamp.recipient_zone("US", "CFG"), webstamp.EUROPE_ZONE)

	def test_the_letters_of_each_zone_plain_first(self):
		def names(zone):
			return [p["product_name"] for p in webstamp.letter_products(CATALOGUE, zone)]

		self.assertEqual(
			names(webstamp.DOMESTIC_ZONE),
			["Courrier A Lettre standard", "Courrier B Lettre standard", "Courrier A Lettre standard & pj"],
		)
		self.assertEqual(names(webstamp.EUROPE_ZONE), ["Documents Std 20g Z1", "Documents Std 20g Z1 & R"])
		self.assertEqual(names(webstamp.WORLD_ZONE), ["Documents Std 20g Z2"])

	def test_the_country_list_is_read_by_name(self):
		"""The service lists names only, in its language: "Allemagne" is Germany."""
		countries = [
			{"code": "", "name": "Allemagne", "zone": 1},
			{"code": "", "name": "États-Unis", "zone": 2},
			{"code": "", "name": "Atlantide", "zone": 1},
		]
		client = types.ModuleType("swisspost_barcode.swisspost_barcode.webstamp.client")
		client.WebstampClient = lambda config: SimpleNamespace(get_countries=lambda: countries)
		packages = (
			"swisspost_barcode",
			"swisspost_barcode.swisspost_barcode",
			"swisspost_barcode.swisspost_barcode.webstamp",
		)
		modules = {name: types.ModuleType(name) for name in packages}
		modules[client.__name__] = client
		key = "hrms_webstamp_zones_CFG-TEST"
		frappe.cache.delete_value(key)
		self.addCleanup(frappe.cache.delete_value, key)
		with patch.dict(sys.modules, modules):
			self.assertEqual(webstamp._country_zones("CFG-TEST"), {"DE": 1, "US": 2})


def _male_gender():
	from hrms.regional.switzerland.insurance_solutions import normalize_sex

	for name in frappe.get_all("Gender", pluck="name"):
		if normalize_sex(name) == "male":
			return name
	return frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert(ignore_permissions=True).name
