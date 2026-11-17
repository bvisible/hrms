# //// Neoffice — added file (no upstream equivalent): the vacation leave type is found by its mark in HR Settings,
# //// whatever the company calls it, and the pass names it in the site's language (neoffice-maintenance#2793).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import setup, vacation

CHOSEN = "_Test annual holidays"
TARGET = "_Test vacation name"


class TestTheVacationLeaveTypeKeepsItsMark(FrappeTestCase):
	"""A company calls its vacation as it wants: the payroll finds it by the mark HR Settings keeps, and the pass that
	names it in the site's language touches only a type that still carries the install's name, and never doubles one."""

	def setUp(self):
		frappe.db.savepoint("vacation_mark")
		create_custom_fields({"HR Settings": [setup.vacation_field()]}, update=True)
		frappe.clear_cache(doctype="HR Settings")
		# the site's vacation as the install left it, under its translated name: put back where a pass renamed it
		install_names = setup.leave_type_names("Privilege Leave")
		marked = setup._named_vacation()
		found = setup.existing_leave_type("Privilege Leave")
		if not found and marked:
			found = frappe.rename_doc("Leave Type", marked, install_names[0], force=True)
		if not found:
			found = (
				frappe.get_doc({"doctype": "Leave Type", "leave_type_name": install_names[0]}).insert().name
			)
		frappe.db.set_single_value("HR Settings", setup.VACATION_FIELD, None)
		self.vacation = found

	def tearDown(self):
		frappe.db.rollback(save_point="vacation_mark")
		frappe.clear_cache(doctype="HR Settings")
		frappe.clear_cache(doctype="Leave Type")

	def test_a_renamed_vacation_is_still_found(
		self,
	):  # role-check: ok a configuration of the site, run as the system
		self.assertEqual(setup.mark_vacation_leave_type(), self.vacation)
		chosen = frappe.rename_doc("Leave Type", self.vacation, CHOSEN, force=True)
		self.assertEqual(vacation.vacation_leave_type(), chosen)
		# the mark is a link: the rename carried it along
		self.assertEqual(frappe.db.get_single_value("HR Settings", setup.VACATION_FIELD), chosen)

	def test_the_mark_is_set_once(self):  # role-check: ok a configuration of the site, run as the system
		self.assertEqual(setup.mark_vacation_leave_type(), self.vacation)
		other = (
			frappe.get_doc({"doctype": "Leave Type", "leave_type_name": "_Test other leave"}).insert().name
		)
		frappe.db.set_single_value("HR Settings", setup.VACATION_FIELD, other)
		self.assertEqual(setup.mark_vacation_leave_type(), other)  # a type already named stays named
		self.assertEqual(vacation.vacation_leave_type(), other)

	def test_the_pass_names_the_vacation_once(self):  # role-check: ok a migration pass, run as the system
		self.assertEqual(setup.name_vacation_leave_type(TARGET), {"from": self.vacation, "to": TARGET})
		self.assertTrue(frappe.db.exists("Leave Type", TARGET))
		self.assertFalse(frappe.db.exists("Leave Type", self.vacation))
		self.assertEqual(vacation.vacation_leave_type(), TARGET)
		# the new name is no install name: a second pass leaves it
		self.assertIsNone(setup.name_vacation_leave_type("_Test encore"))

	def test_a_name_the_company_chose_stays(self):  # role-check: ok a migration pass, run as the system
		setup.mark_vacation_leave_type()
		chosen = frappe.rename_doc("Leave Type", self.vacation, CHOSEN, force=True)
		self.assertIsNone(setup.name_vacation_leave_type(TARGET))
		self.assertTrue(frappe.db.exists("Leave Type", chosen))
		self.assertFalse(frappe.db.exists("Leave Type", TARGET))

	def test_never_a_second_vacation(self):  # role-check: ok a migration pass, run as the system
		frappe.get_doc({"doctype": "Leave Type", "leave_type_name": TARGET}).insert()
		self.assertIsNone(setup.name_vacation_leave_type(TARGET))
		self.assertTrue(frappe.db.exists("Leave Type", self.vacation))
		self.assertEqual(vacation.vacation_leave_type(), self.vacation)
