# //// Neoffice — added file (no upstream equivalent): tests of the payslip WebStamp (webstamp.py).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import base64

import frappe
from frappe.tests.utils import FrappeTestCase

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


def _male_gender():
	from hrms.regional.switzerland.insurance_solutions import normalize_sex

	for name in frappe.get_all("Gender", pluck="name"):
		if normalize_sex(name) == "male":
			return name
	return frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert(ignore_permissions=True).name
