# //// Neoffice — added file (no upstream equivalent): tests of the vacation balance paid at the exit
# //// (vacation.py).
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest
from unittest.mock import patch

import frappe

from hrms.regional.switzerland import vacation

WITH_13TH = {"thirteenth_month_mode": "Annual"}


class TestTheValueOfADay(unittest.TestCase):
	def rate(self, config, base=8000, variable=300, entitlement=20):
		with (
			patch.object(vacation, "monthly_base", return_value=base),
			patch.object(vacation, "variable_average", return_value=variable),
			patch.object(vacation, "yearly_entitlement", return_value=entitlement),
		):
			return vacation.daily_rate("_T-emp", "_T-co", "2027-05-31", config, "_T-vacation")

	def test_the_divisor_on_the_salary_with_the_13th_and_the_variable_pay(self):
		rate, detail = self.rate(dict(WITH_13TH))
		self.assertEqual(rate, round((8000 * 13 / 12 + 300) / 21.75, 2))
		self.assertEqual((detail["divisor"], detail["salaries_per_year"]), (21.75, 13))
		rate, _detail = self.rate({**WITH_13TH, "vacation_payout_divisor": 21.7})
		self.assertEqual(rate, round((8000 * 13 / 12 + 300) / 21.7, 2))

	def test_after_the_contract_and_calendar_days(self):
		rate, detail = self.rate({**WITH_13TH, "vacation_payout_method": vacation.AFTER_CONTRACT})
		self.assertEqual((rate, detail["divisor"]), (round((8000 * 13 / 12 + 300) * 12 / 240, 2), 240))
		rate, _detail = self.rate({"vacation_payout_method": vacation.CALENDAR_DAYS}, variable=0)
		self.assertEqual(rate, round(8000 / 30, 2))


class TestTheBalanceAtTheExit(unittest.TestCase):
	def test_the_entitlement_of_the_year_worked(self):
		allocation = frappe._dict(new_leaves_allocated=20, from_date="2027-01-01", to_date="2027-12-31")
		with (
			patch(
				"hrms.hr.doctype.leave_application.leave_application.get_leave_balance_on", return_value=20
			),
			patch("frappe.get_cached_value", return_value=0),
			patch("frappe.db.get_value", return_value=allocation),
		):
			balance = vacation.exit_balance("_T-emp", "_T-vacation", "2027-05-31")
		# 151 days of 365 worked: 20 x 151/365 = 8.27 days earned, none taken.
		self.assertEqual(balance, round(20 - 20 * (1 - 151 / 365), 2))

	def test_the_warnings_of_the_leavers(self):
		rows = [
			{"employee": "A", "employee_name": "Anne", "relieving_date": "2027-05-31", "balance": 3.5, "encashment": None, "rate": 400, "amount": 1400},
			{"employee": "B", "employee_name": "Bruno", "relieving_date": "2027-05-15", "balance": -2, "encashment": None, "rate": 0, "amount": 0},
			{"employee": "C", "employee_name": "Cleo", "relieving_date": "2027-05-20", "balance": 4, "encashment": "LE-1", "rate": 380, "amount": 1520},
		]  # fmt: skip
		with patch.object(vacation, "exit_balances", return_value=rows):
			issues = vacation.exit_warnings("_T-co", "2027-05-01", "2027-05-31")
		self.assertEqual(
			[(i["code"], i["employee"]) for i in issues],
			[("vacation_balance", "A"), ("vacation_negative", "B")],
		)


class TestTheEncashmentHook(unittest.TestCase):
	"""The whole fleet is Swiss: only a company on the Swiss payroll gets its days valued here."""

	def value(self, config, rate):
		doc = frappe._dict(
			employee="_T-emp", leave_type="_T-vacation", encashment_days=5, encashment_date="2027-05-31"
		)
		doc.encashment_amount = 999
		with (
			patch("frappe.db.get_value", return_value="_T-co"),
			patch("frappe.get_cached_value", return_value="Switzerland"),
			patch.object(vacation, "vacation_leave_type", return_value="_T-vacation"),
			patch("hrms.regional.switzerland.utils.get_swiss_social_insurance_config", return_value=config),
			patch("hrms.regional.switzerland.utils.get_company_payroll_config", return_value=config),
			patch.object(vacation, "daily_rate", return_value=(rate, {})),
		):
			vacation.value_leave_encashment(doc)
		return doc.encashment_amount

	def test_a_company_on_the_swiss_payroll_values_the_days_from_the_salary(self):
		self.assertEqual(self.value({"name": "_T-config"}, 400), 2000)

	def test_a_company_without_the_swiss_payroll_keeps_the_standard_amount(self):
		self.assertEqual(self.value(None, 400), 999)

	def test_no_salary_to_value_a_day_from_keeps_the_standard_amount(self):
		self.assertEqual(self.value({"name": "_T-config"}, 0), 999)


# A site installed in French, and what its leave types are called there.
FRENCH = {
	"Privilege Leave": "Congé de privilège",
	"Accident": "Congé Accident",
	"Sick Leave": "Congé Maladie",
}
ON_THE_SITE = {"Congé de privilège", "Congé Accident", "Congé Maladie", "Congé Sans Solde"}


class TestTheLeaveTypesWhateverTheLanguage(unittest.TestCase):
	"""A leave type keeps the name it was created under: a user reading English on a site installed
	in French still finds the vacation and the absences."""

	def lookup(self):
		from hrms.regional.switzerland import setup

		def translate(msg, lang=None, context=None):
			return FRENCH.get(msg, msg) if lang == "fr" else msg  # the user reads English

		return (
			patch.object(setup, "_", side_effect=translate),
			patch("frappe.db.get_single_value", return_value="fr"),
			patch("frappe.db.exists", side_effect=lambda doctype, name: name in ON_THE_SITE),
		)

	def test_the_vacation_under_the_site_language(self):
		from hrms.regional.switzerland import setup

		first, second, third = self.lookup()
		with first, second, third:
			self.assertEqual(vacation.vacation_leave_type(), "Congé de privilège")
			self.assertIsNone(setup.existing_leave_type("Compensatory Off"))

	def test_the_absences_that_interrupt_a_flat_rate_allowance(self):
		from hrms.regional.switzerland import expenses

		first, second, third = self.lookup()
		with first, second, third, patch("frappe.get_all", return_value=["Congé Sans Solde"]):
			self.assertEqual(
				expenses.absence_types(), {"Congé Maladie", "Congé Accident", "Congé Sans Solde"}
			)


class TestTheLeavePeriodOfAnEncashment(unittest.TestCase):
	"""A Leave Encashment requires a leave period, which a company allocating by year never set up."""

	def test_the_company_period_covering_the_exit(self):
		with patch("frappe.db.get_value", return_value="LP-2026"), patch("frappe.get_doc") as get_doc:
			self.assertEqual(vacation.leave_period_for("_T-co", "2026-09-30"), "LP-2026")
		get_doc.assert_not_called()

	def test_the_calendar_year_when_the_company_has_none(self):
		with patch("frappe.db.get_value", return_value=None), patch("frappe.get_doc") as get_doc:
			get_doc.return_value.name = "LP-new"
			self.assertEqual(vacation.leave_period_for("_T-co", "2026-09-30"), "LP-new")
		values = get_doc.call_args.args[0]
		self.assertEqual(
			(values["from_date"], values["to_date"], values["company"]), ("2026-01-01", "2026-12-31", "_T-co")
		)
