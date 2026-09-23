# //// Neoffice — added file (no upstream equivalent): who may read, send and repopulate a Swiss
# //// salary certificate.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.payroll.doctype.swiss_salary_certificate import swiss_salary_certificate as certificate_module
from hrms.payroll.doctype.swiss_salary_certificate.swiss_salary_certificate import (
	employee_email_addresses,
	get_permission_query_conditions,
	has_permission,
)
from hrms.regional.switzerland.api import get_my_salary_certificates

MODULE = "hrms.payroll.doctype.swiss_salary_certificate.swiss_salary_certificate"


def certificate(employee="EMP-1", docstatus=1):
	return frappe._dict(doctype="Swiss Salary Certificate", employee=employee, docstatus=docstatus)


class TestCertificateAccessHooks(FrappeTestCase):
	"""An employee reads their own validated certificates, nothing else; payroll staff read all."""

	def hooks(self, roles, employees):
		return (
			patch(f"{MODULE}.frappe.get_roles", return_value=roles),
			patch(f"{MODULE}._employees_of", return_value=employees),
		)

	def test_payroll_staff_defer_to_the_doctype_permissions(self):
		roles, employees = self.hooks(["HR User", "Employee"], [])
		with roles, employees:
			self.assertIsNone(has_permission(certificate(docstatus=0), user="hr@example.com"))
			self.assertEqual(get_permission_query_conditions("hr@example.com"), "")

	def test_an_employee_reads_their_own_validated_certificate(self):
		roles, employees = self.hooks(["Employee"], ["EMP-1"])
		with roles, employees:
			self.assertTrue(has_permission(certificate("EMP-1"), user="emp@example.com"))

	def test_an_employee_never_reads_a_draft(self):
		roles, employees = self.hooks(["Employee"], ["EMP-1"])
		with roles, employees:
			self.assertFalse(has_permission(certificate("EMP-1", docstatus=0), user="emp@example.com"))

	def test_an_employee_never_reads_a_colleague(self):
		roles, employees = self.hooks(["Employee"], ["EMP-1"])
		with roles, employees:
			self.assertFalse(has_permission(certificate("EMP-2"), user="emp@example.com"))

	def test_the_list_is_narrowed_to_the_employee_and_to_validated_ones(self):
		roles, employees = self.hooks(["Employee"], ["EMP-1", "O'Brien"])
		with roles, employees:
			condition = get_permission_query_conditions("emp@example.com")
		self.assertIn("docstatus = 1", condition)
		self.assertIn("'EMP-1'", condition)
		self.assertIn(frappe.db.escape("O'Brien"), condition)

	def test_a_user_without_employee_record_lists_nothing(self):
		roles, employees = self.hooks(["Employee"], [])
		with roles, employees:
			self.assertEqual(get_permission_query_conditions("portal@example.com"), "1=0")


class TestSendingGuards(FrappeTestCase):
	def test_addresses_preferred_first_without_duplicates(self):
		row = frappe._dict(
			prefered_email="me@home.example",
			personal_email="me@home.example",
			company_email="me@work.example",
			user_id="Administrator",
		)
		with patch(f"{MODULE}.frappe.db.get_value", return_value=row):
			self.assertEqual(employee_email_addresses("EMP-1"), ["me@home.example", "me@work.example"])

	def test_a_draft_is_never_sent(self):
		doc = frappe.new_doc("Swiss Salary Certificate")
		doc.docstatus = 0
		with self.assertRaises(frappe.ValidationError):
			doc.send_to_employee("me@home.example")

	def test_only_an_address_of_the_employee_record(self):
		doc = frappe.new_doc("Swiss Salary Certificate")
		doc.docstatus = 1
		doc.employee = "EMP-1"
		with (
			patch.object(certificate_module.SwissSalaryCertificate, "check_permission"),
			patch(f"{MODULE}.employee_email_addresses", return_value=["me@home.example"]),
		):
			with self.assertRaises(frappe.ValidationError):
				doc.send_to_employee("someone@else.example")


class TestRectification(FrappeTestCase):
	def test_an_amended_certificate_is_neither_validated_nor_sent(self):
		"""The desk's Amend copies no_copy fields: a rectification must start blank."""
		doc = frappe.new_doc("Swiss Salary Certificate")
		doc.update(
			{
				"amended_from": "CH-CERT-2026-EMP-1",
				"doc_id": "d78dea25-3971-4f48-a33c-58d534a64ec8",
				"finalized_on": "2027-01-10 09:00:00",
				"sent_to_employee_on": "2027-01-11 10:00:00",
				"sent_to": "me@home.example",
			}
		)
		doc.before_insert()
		for field in ("doc_id", "finalized_on", "sent_to_employee_on", "sent_to"):
			self.assertIsNone(doc.get(field), field)


class TestMyCertificates(FrappeTestCase):
	def test_a_user_without_employee_record_gets_an_empty_list(self):
		frappe.set_user("Guest")
		try:
			self.assertEqual(get_my_salary_certificates(), [])
		finally:
			frappe.set_user("Administrator")
