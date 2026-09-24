# //// Neoffice — added file (no upstream equivalent): tests of the payslip distribution step of the
# //// monthly cycle (distribution.py) and of the cycle holding the e-mail back at submission.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import calendar
from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from hrms.regional.switzerland import distribution, monthly_cycle

YEAR, MONTH = 2032, 3  # a period no other test and no site data uses


def _male_gender():
	from hrms.regional.switzerland.insurance_solutions import normalize_sex

	for name in frappe.get_all("Gender", pluck="name"):
		if normalize_sex(name) == "male":
			return name
	return frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert(ignore_permissions=True).name


class DistributionCase(FrappeTestCase):
	def setUp(self):
		from hrms.regional.switzerland.setup import make_custom_fields

		if not frappe.db.has_column("Employee", "ch_payslip_delivery") or not frappe.db.has_column(
			"Salary Slip", "ch_printed_on"
		):
			make_custom_fields()
		self.company = frappe.db.get_value(
			"Company", {"country": "Switzerland"}, "name"
		) or frappe.db.get_value("Company", {}, "name")
		self.employee = self._employee("Payslip", "Distribution", "Rue du Test 1\n1000 Lausanne")
		self.slip = self._slip(self.employee, "Payslip Distribution")
		self.addCleanup(frappe.db.rollback)

	def _employee(self, first_name, last_name, address, **fields):
		return (
			frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": first_name,
					"last_name": last_name,
					"company": self.company,
					"gender": _male_gender(),
					"date_of_birth": "1990-01-01",
					"date_of_joining": "2020-01-01",
					"status": "Active",
					"permanent_address": address,
					**fields,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def _slip(self, employee, employee_name):
		last = calendar.monthrange(YEAR, MONTH)[1]
		name = f"_T-Swiss-Distribution-{employee}"
		doc = frappe.get_doc(
			{
				"doctype": "Salary Slip",
				"employee": employee,
				"employee_name": employee_name,
				"company": self.company,
				"currency": "CHF",
				"exchange_rate": 1,
				"payroll_frequency": "Monthly",
				"start_date": date(YEAR, MONTH, 1),
				"end_date": date(YEAR, MONTH, last),
				"posting_date": date(YEAR, MONTH, last),
				"docstatus": 1,
				"gross_pay": 6000,
				"total_deduction": 318,
				"net_pay": 5682,
			}
		)
		doc.name = name
		doc.db_insert()
		return name

	def _row(self):
		rows = distribution.get_distribution(self.company, YEAR, MONTH)["rows"]
		return next(r for r in rows if r["slip"] == self.slip)


class TestPayslipChannels(DistributionCase):
	def test_email_when_the_employee_has_an_address_else_by_hand(self):
		self.assertEqual(self._row()["channel"], "By Hand")
		frappe.db.set_value("Employee", self.employee, "prefered_email", "payslip-test@yopmail.com")
		self.assertEqual(self._row()["channel"], "Email")

	def test_the_channel_chosen_is_remembered(self):
		distribution.set_channel(self.company, self.employee, "By Post")
		self.assertEqual(self._row()["channel"], "By Post")
		with self.assertRaises(frappe.ValidationError):
			distribution.set_channel(self.company, self.employee, "Pigeon")


class TestPayslipPrinted(DistributionCase):
	"""A print leaves a trace: nothing else says a payslip was handed out or posted."""

	def test_a_payslip_printed_by_hand_is_delivered_and_the_channel_remembered(self):
		self.assertIsNone(self._row()["printed_on"])
		with patch.object(distribution, "get_webstamp_image", return_value=None):
			marked = distribution.mark_printed(self.company, YEAR, MONTH, [self.slip])
		self.assertEqual(marked, [self.slip])
		self.assertTrue(self._row()["printed_on"])
		self.assertEqual(frappe.db.get_value("Employee", self.employee, "ch_payslip_delivery"), "By Hand")

	def test_a_franked_payslip_printed_keeps_going_by_post(self):
		distribution.set_channel(self.company, self.employee, "By Post")
		with patch.object(distribution, "get_webstamp_image", return_value="/files/stamp.png"):
			distribution.mark_printed(self.company, YEAR, MONTH, [self.slip])
			row = self._row()
		self.assertTrue(row["printed_on"])
		self.assertEqual(row["channel"], "By Post")

	def test_only_the_period_payslips_are_marked(self):
		self.assertEqual(distribution.mark_printed(self.company, YEAR, MONTH + 1, [self.slip]), [])
		self.assertIsNone(self._row()["printed_on"])


class TestFrankingPlan(DistributionCase):
	"""The payslips to post, grouped by Swiss Post zone, each group with the letters that serve it."""

	def test_a_cross_border_worker_abroad_gets_an_international_letter(self):
		from hrms.regional.switzerland import webstamp
		from hrms.regional.switzerland.test_webstamp import CATALOGUE

		abroad = self._employee("Cross", "Border", "Hauptstrasse 5\n79539 Lörrach", ch_residence_country="DE")
		abroad_slip = self._slip(abroad, "Cross Border")
		with (
			patch.object(webstamp, "_require_app", return_value="CFG"),
			patch.object(webstamp, "_catalogue", return_value=CATALOGUE),
			patch.object(webstamp, "_environment", return_value="Integration"),
			patch.object(webstamp, "_country_zones", return_value={}),
		):
			plan = distribution.get_stamp_plan(self.company, YEAR, MONTH, [self.slip, abroad_slip])
		self.assertEqual(plan["environment"], "Integration")
		home, europe = plan["groups"]  # at home first
		self.assertEqual((home["zone"], home["slips"]), (webstamp.DOMESTIC_ZONE, [self.slip]))
		self.assertEqual(home["products"][0]["product_name"], "Courrier A Lettre standard")
		self.assertEqual((europe["zone"], europe["slips"]), (webstamp.EUROPE_ZONE, [abroad_slip]))
		self.assertEqual(europe["products"][0]["product_name"], "Documents Std 20g Z1")
		recipient = europe["recipients"][0]
		self.assertEqual(recipient["address"], "Hauptstrasse 5, 79539 Lörrach")
		self.assertTrue(recipient["country"])  # said, so a wrong country shows before ordering
		self.assertEqual(home["recipients"][0]["country"], "")


OUTGOING = "frappe.email.doctype.email_account.email_account.EmailAccount.find_outgoing"


class TestPayslipByEmail(DistributionCase):
	def test_the_payslip_leaves_by_email_with_the_swiss_print(self):
		frappe.db.set_value("Employee", self.employee, "prefered_email", "payslip-test@yopmail.com")
		# The PDF is wkhtmltopdf's business (it needs the site's host) and the queue Frappe's (it needs
		# an outgoing account): what is checked is what the payslip asks of them.
		pdf = {"fname": "payslip.pdf", "fcontent": b"%PDF-1.4"}
		with (
			patch("frappe.attach_print", return_value=pdf) as attach_print,
			patch("frappe.sendmail") as sendmail,
			patch(OUTGOING),
		):
			result = distribution.send_payslips(self.company, YEAR, MONTH, [self.slip])
		self.assertEqual(result["sent"], [self.slip])
		self.assertEqual(attach_print.call_args.args[:2], ("Salary Slip", self.slip))
		# attach_print drops spaces: the words must stay apart in the file name.
		file_name = attach_print.call_args.kwargs["file_name"]
		self.assertNotIn(" ", file_name)
		self.assertTrue(file_name.endswith("-Payslip-Distribution"), file_name)
		if frappe.db.exists("Print Format", distribution.PRINT_FORMAT):
			self.assertEqual(attach_print.call_args.kwargs["print_format"], distribution.PRINT_FORMAT)
		mail = sendmail.call_args.kwargs
		self.assertEqual(mail["recipients"], ["payslip-test@yopmail.com"])
		self.assertEqual((mail["reference_doctype"], mail["reference_name"]), ("Salary Slip", self.slip))
		self.assertEqual(mail["attachments"], [pdf])
		self.assertIn("Payslip Distribution", mail["message"])
		self.assertEqual(frappe.db.get_value("Employee", self.employee, "ch_payslip_delivery"), "Email")

	def test_no_outgoing_account_is_said_before_anything_is_queued(self):
		"""Without it the background e-mails would fail unseen while the page said they had left."""
		frappe.db.set_value("Employee", self.employee, "prefered_email", "payslip-test@yopmail.com")
		with (
			patch(OUTGOING, side_effect=frappe.OutgoingEmailError),
			patch("frappe.sendmail") as sendmail,
			self.assertRaises(frappe.OutgoingEmailError),
		):
			distribution.send_payslips(self.company, YEAR, MONTH, [self.slip])
		sendmail.assert_not_called()

	def test_an_employee_without_address_is_reported_not_sent(self):
		with patch(OUTGOING):
			result = distribution.send_payslips(self.company, YEAR, MONTH, [self.slip])
		self.assertEqual((result["sent"], result["without_email"]), ([], ["Payslip Distribution"]))

	def test_a_payslip_already_sent_shows_as_sent(self):
		frappe.get_doc(
			{
				"doctype": "Email Queue",
				"reference_doctype": "Salary Slip",
				"reference_name": self.slip,
				"status": "Sent",
				"sender": "payroll@example.com",
				"message": "x",
			}
		).db_insert()
		self.assertTrue(self._row()["emailed"])


class TestTheCycleHoldsTheEmailBack(FrappeTestCase):
	"""Submitting in the cycle must not e-mail the slip: the distribution step does, when chosen."""

	def test_submission_runs_with_the_hold_back_flag(self):
		seen = []

		class Slip:
			def submit(self):
				seen.append(bool(frappe.flags.via_payroll_entry))

		company = frappe.db.get_value("Company", {}, "name")
		with (
			patch.object(monthly_cycle, "_check_payroll_read_permission"),
			patch("frappe.has_permission", return_value=True),
			patch("frappe.get_all", return_value=[frappe._dict(name="SLIP-1", employee_name="X")]),
			patch("frappe.get_doc", return_value=Slip()),
		):
			result = monthly_cycle.submit_cycle(company, 2032, 3)
		self.assertEqual(result["submitted"], ["SLIP-1"])
		self.assertEqual(seen, [True])
		self.assertFalse(frappe.flags.via_payroll_entry)  # restored afterwards
