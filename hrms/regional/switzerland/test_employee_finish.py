# //// Neoffice — added file (no upstream equivalent): the « finish » mode of the Swiss employee wizard. The Neoffice
# //// theme gives every desk account an Employee record that knows a name, a company and a date; the wizard completes it
# //// instead of creating one. Vault note Neoffice/03-DevOps/269.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import employee_wizard as wizard

PREFIX = "Finish Test "
AVS = "756.1234.5678.97"
IBAN = "CH9300762011623852957"
CLERK = "finish-test-clerk@yopmail.com"


def _ensure_mark():
	"""The mark is a custom field of the Neoffice theme; a site without it gets it here."""
	if not frappe.get_meta("Employee").has_field(wizard.COMPLETION_FIELD):
		from frappe.custom.doctype.custom_field.custom_field import create_custom_field

		create_custom_field(
			"Employee",
			{
				"fieldname": wizard.COMPLETION_FIELD,
				"fieldtype": "Check",
				"label": "Record to complete",
				"insert_after": "status",
				"default": "0",
				"hidden": 1,
				"read_only": 1,
			},
		)
		frappe.clear_cache(doctype="Employee")


def _drafts(employee):
	if not frappe.db.exists("DocType", "Swissdec EMA Notification"):
		return 0
	return frappe.db.count("Swissdec EMA Notification", {"employee": employee})


class TestFinishTheRecord(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_mark()
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Employee", filters={"first_name": ["like", f"{PREFIX}%"]}, pluck="name"):
			if frappe.db.exists("DocType", "Swissdec EMA Notification"):
				frappe.db.delete("Swissdec EMA Notification", {"employee": name})
			frappe.delete_doc("Employee", name, force=1, ignore_permissions=True)
		if frappe.db.exists("User", CLERK):
			frappe.delete_doc("User", CLERK, force=1, ignore_permissions=True)
		super().tearDown()

	def _record(self, tag, marked=1, **values):
		"""A record as the theme's catch-up makes it: a name, a company, a date, and the mark."""
		doc = frappe.new_doc("Employee")
		doc.update(
			{
				"naming_series": (doc.meta.get_field("naming_series").options or "").split("\n")[0] or "HR-EMP-",
				"first_name": f"{PREFIX}{tag}",
				"last_name": "Record",
				"company": self.company,
				"status": "Active",
				"date_of_joining": "2026-10-29",
				wizard.COMPLETION_FIELD: marked,
				**values,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_permissions = True
		doc.flags.neo_account_employee = True
		doc.insert()
		return doc

	def _gender(self):
		return frappe.get_all("Gender", pluck="name", limit=1)[0]

	def _data(self, record, **over):
		data = {
			"first_name": record.first_name,
			"last_name": record.last_name,
			"company": record.company,
			"date_of_joining": "2026-10-29",
			"gender": self._gender(),
			"date_of_birth": "1991-03-14",
			"nationality": "Switzerland",
			"permit_type": "Swiss Citizen",
			"marital_status": "Single",
			"work_percentage": 100,
			"qst_subject": 0,
		}
		data.update(over)
		return data

	# -- what the assistant is given ------------------------------------------------------------------------------

	def test_a_bare_record_starts_on_the_person_step_with_what_is_known(self):
		record = self._record("bare")
		info = wizard.employee_to_finish(record.name)
		self.assertEqual(info["first_step"], "person")
		self.assertEqual(info["data"]["first_name"], record.first_name)
		self.assertEqual(info["data"]["company"], self.company)
		self.assertNotIn("gender", info["data"])
		self.assertGreaterEqual(info["remaining"], 1)

	def test_a_step_already_complete_is_skipped(self):
		record = self._record(
			"person-done",
			gender=self._gender(),
			date_of_birth="1990-01-01",
			permanent_address="Rue du Lac 12\n1950 Sion",
			ch_avs_number=AVS,
		)
		self.assertEqual(wizard.employee_to_finish(record.name)["first_step"], "job")

	def test_a_record_with_nothing_missing_goes_to_the_check(self):
		record = self._record(
			"all-done",
			gender=self._gender(),
			date_of_birth="1990-01-01",
			permanent_address="Rue du Lac 12\n1950 Sion",
			ch_avs_number=AVS,
			designation=None,
			bank_ac_no=IBAN,
		)
		designation = frappe.get_all("Designation", pluck="name", limit=1)
		if not designation:
			self.skipTest("no designation on this site")
		frappe.db.set_value("Employee", record.name, "designation", designation[0])
		with patch.object(wizard, "_latest_assignment", return_value=frappe._dict(base=5000, salary_structure="x")):
			self.assertEqual(wizard.employee_to_finish(record.name)["first_step"], "review")

	# -- finishing -------------------------------------------------------------------------------------------------

	def test_finishing_needs_gender_and_date_of_birth(self):
		record = self._record("needs-two")
		for missing in ("gender", "date_of_birth"):
			data = self._data(record)
			data.pop(missing)
			with self.assertRaises(frappe.ValidationError):
				wizard.complete_employee(record.name, data)
		self.assertEqual(frappe.db.get_value("Employee", record.name, wizard.COMPLETION_FIELD), 1)

	def test_finishing_writes_what_is_given_and_lifts_the_mark(self):
		record = self._record("finish")
		data = self._data(
			record,
			avs_number="756.1234.5678.97",
			iban=IBAN,
			address_street="Rue du Lac 12",
			address_town="1950 Sion",
			email="finish.test@example.ch",
			mobile="079 000 00 00",
			designation="Finish Test Designation",
			canton="VS",
		)
		out = wizard.complete_employee(record.name, data)
		doc = frappe.get_doc("Employee", record.name)
		self.assertEqual(out["employee"], record.name)
		self.assertEqual(doc.get(wizard.COMPLETION_FIELD), 0)
		self.assertEqual(str(doc.date_of_birth), "1991-03-14")
		self.assertEqual(doc.ch_avs_number, AVS)
		self.assertEqual(doc.bank_ac_no, IBAN)
		self.assertEqual(doc.permanent_address, "Rue du Lac 12\n1950 Sion")
		self.assertEqual(doc.personal_email, "finish.test@example.ch")
		self.assertEqual(doc.designation, "Finish Test Designation")
		self.addCleanup(frappe.delete_doc, "Designation", "Finish Test Designation", force=1, ignore_permissions=True)

	def test_a_blank_never_erases_what_the_record_holds(self):
		record = self._record("keeps", personal_email="keeps@example.ch", cell_number="079 111 11 11")
		wizard.complete_employee(record.name, self._data(record, email="", mobile=""))
		doc = frappe.get_doc("Employee", record.name)
		self.assertEqual((doc.personal_email, doc.cell_number), ("keeps@example.ch", "079 111 11 11"))

	def test_a_wrong_avs_number_or_iban_is_refused_and_nothing_is_written(self):
		record = self._record("refused")
		for bad in ({"avs_number": "756.1234.5678.90"}, {"iban": "CH0000000000000000000"}):
			with self.assertRaises(frappe.ValidationError):
				wizard.complete_employee(record.name, self._data(record, **bad))
		doc = frappe.get_doc("Employee", record.name)
		self.assertFalse(doc.gender)
		self.assertEqual(doc.get(wizard.COMPLETION_FIELD), 1)

	def test_a_record_that_was_never_marked_can_be_finished_too(self):
		record = self._record("unmarked", marked=0)
		wizard.complete_employee(record.name, self._data(record))
		self.assertTrue(frappe.db.get_value("Employee", record.name, "gender"))

	def test_finishing_drops_no_swissdec_draft_not_even_a_mutation(self):
		if not frappe.db.exists("DocType", "Swissdec EMA Notification"):
			self.skipTest("Swissdec notifications are not installed")
		record = self._record("swiss")
		with patch("hrms.regional.switzerland.ema_hooks._is_swiss_company", return_value=True):
			wizard.complete_employee(record.name, self._data(record, avs_number=AVS, canton="VS"))
		self.assertEqual(_drafts(record.name), 0)

	def test_the_mark_is_found_by_the_series_in_the_order_of_creation(self):
		first, second, third = (self._record(tag) for tag in ("one", "two", "three"))
		names = [row.name for row in wizard._to_finish()]
		mine = [first.name, second.name, third.name]
		self.assertEqual([n for n in names if n in mine], mine)
		following = wizard.next_employee_to_finish(after=first.name)
		self.assertEqual(following["name"], names[names.index(first.name) + 1])
		self.assertEqual(wizard.next_employee_to_finish(after=names[-1])["name"], names[0] if names[0] != names[-1] else None)

	def test_the_series_ends_when_nothing_is_left(self):
		record = self._record("last")
		with patch.object(wizard, "_to_finish", return_value=[]):
			out = wizard.complete_employee(record.name, self._data(record))
			self.assertIsNone(wizard.next_employee_to_finish())
		self.assertIsNone(out["next"])
		self.assertEqual(out["remaining"], 0)

	# -- who may ---------------------------------------------------------------------------------------------------

	def test_only_who_may_write_the_record_finishes_it(self):
		record = self._record("guarded")
		if not frappe.db.exists("User", CLERK):
			user = frappe.new_doc("User")
			user.update({"email": CLERK, "first_name": "Clerk", "send_welcome_email": 0, "user_type": "System User"})
			user.append("roles", {"role": "Accounts User"})
			user.flags.ignore_permissions = True
			user.insert()
		frappe.set_user(CLERK)
		with self.assertRaises(frappe.PermissionError):
			wizard.employee_to_finish(record.name)
		with self.assertRaises(frappe.PermissionError):
			wizard.complete_employee(record.name, self._data(record))
		# Who cannot write is offered no series at all, not even the record they may read.
		self.assertIsNone(wizard.next_employee_to_finish())
		self.assertEqual(wizard._to_finish(), [])
