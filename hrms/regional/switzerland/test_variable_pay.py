# //// Neoffice — added file (no upstream equivalent): tests of the variable pay importer (variable_pay.py) — a
# //// commission computed outside the payroll becomes an Additional Salary, once, and never changes a submitted slip.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from hrms.regional.switzerland import variable_pay as vp
from hrms.regional.switzerland import wage_type_data
from hrms.regional.switzerland.test_distribution import _male_gender
from hrms.regional.switzerland.test_payroll_hooks import _ensure_custom_fields, _ensure_wage_type

YEAR, MONTH = 2033, 5  # a period no other test and no site data uses
LAST_DAY = "2033-05-31"
CODE = "1299"  # a wage type of these tests: in no catalogue
TIP_CODE = "1297"  # one that only raises the insurance bases
DEDUCTION_CODE = "1296"
HR_USER = "variable-pay-hr-test@yopmail.com"
HR_MANAGER_USER = "variable-pay-hr-manager-test@yopmail.com"
EMPLOYEE_USER = "variable-pay-employee-test@yopmail.com"
PORTAL_USER = "variable-pay-portal-test@yopmail.com"
PROVIDER = "hrms.regional.switzerland.test_variable_pay.announce"
BROKEN_PROVIDER = "hrms.regional.switzerland.test_variable_pay.announce_and_fail"


def _ensure_user(email, roles, user_type="System User"):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
			"user_type": user_type,
			"roles": [{"role": role} for role in roles],
		}
	).insert(ignore_permissions=True)
	return email


def announce(company, year, month):
	"""A provider of the preflight: one line for the employee the test announced."""
	return list(announce.lines)


announce.lines = []


def announce_and_fail(company, year, month):
	raise RuntimeError("the provider is down")


class VariablePayCase(FrappeTestCase):
	"""A company, a salary structure, a commission component and the accounts that act on the payroll."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_custom_fields()
		if not frappe.db.has_column("Additional Salary", vp.KEY_FIELD):
			from hrms.regional.switzerland.setup import make_custom_fields

			make_custom_fields()
		cls.company = frappe.db.get_value(
			"Company", {"country": "Switzerland"}, "name"
		) or frappe.db.get_value("Company", {}, "name")
		cls.currency = frappe.get_cached_value("Company", cls.company, "default_currency")
		for code, name, kind, bases_only in (
			(CODE, "Test variable pay", "Earning", 0),
			(TIP_CODE, "Test bases only", "Earning", 1),
			(DEDUCTION_CODE, "Test deduction", "Deduction", 0),
		):
			wage_type = _ensure_wage_type(code, name)
			frappe.db.set_value("Swiss Wage Type", wage_type, {"type": kind, "bases_only": bases_only})
		cls.component = cls._component("_Test VP Commission", CODE, prorated=0)
		cls.tip_component = cls._component("_Test VP Bases Only", TIP_CODE, prorated=0)
		cls.prorated_component = cls._component("_Test VP Prorated", None, prorated=1)
		cls.base_component = cls._component("_Test VP Base", None, prorated=1)
		cls.holiday_list = cls._holiday_list()
		cls._fiscal_year()
		cls.structure = cls._structure()
		# the payroll staff of a real company: HR Manager reads the payroll, HR User creates Additional Salaries (the
		# standard rights of the doctype give it to HR User and System Manager only)
		cls.hr = _ensure_user(HR_USER, ["HR Manager", "HR User"])
		cls.hr_manager_only = _ensure_user(HR_MANAGER_USER, ["HR Manager"])
		cls.ordinary = _ensure_user(EMPLOYEE_USER, ["Employee"])
		cls.portal = _ensure_user(PORTAL_USER, [], user_type="Website User")

	@classmethod
	def _component(cls, name, code, prorated):
		if not frappe.db.exists("Salary Component", name):
			frappe.get_doc(
				{
					"doctype": "Salary Component",
					"salary_component": name,
					"salary_component_abbr": "".join(w[0] for w in name.split("_")[-1].split())[:6] or "TVP",
					"type": "Earning",
				}
			).insert(ignore_permissions=True)
		values = {"depends_on_payment_days": prorated}
		if code:
			values.update(ch_wage_type=f"CH-WT-{code}", ch_wage_type_code=code)
		frappe.db.set_value("Salary Component", name, values)
		return name

	@classmethod
	def _fiscal_year(cls):
		"""A slip needs a fiscal year of the company on its dates."""
		if frappe.db.exists("Fiscal Year", "2033"):
			doc = frappe.get_doc("Fiscal Year", "2033")
			if not any(row.company == cls.company for row in doc.companies):
				doc.append("companies", {"company": cls.company})
				doc.save(ignore_permissions=True)
			return
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": "2033",
				"year_start_date": "2033-01-01",
				"year_end_date": "2033-12-31",
				"companies": [{"company": cls.company}],
			}
		).insert(ignore_permissions=True)

	@classmethod
	def _holiday_list(cls):
		name = "_Test VP 2033"
		if not frappe.db.exists("Holiday List", name):
			frappe.get_doc(
				{
					"doctype": "Holiday List",
					"holiday_list_name": name,
					"from_date": "2033-01-01",
					"to_date": "2033-12-31",
				}
			).insert(ignore_permissions=True)
		return name

	@classmethod
	def _structure(cls):
		name = "_Test VP Structure"
		if frappe.db.exists("Salary Structure", name):
			frappe.delete_doc("Salary Structure", name, force=True, ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "Salary Structure",
				"name": name,
				"company": cls.company,
				"currency": cls.currency,
				"payroll_frequency": "Monthly",
				"is_active": "Yes",
				"earnings": [
					{"salary_component": cls.base_component, "amount": 4000, "depends_on_payment_days": 1}
				],
				"deductions": [],
			}
		)
		doc.insert(ignore_permissions=True)
		doc.submit()
		return doc.name

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	# --- the people of a test

	def employee(self, first_name, assign=True, joining="2020-01-01", **fields):
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": first_name,
				"last_name": f"VP{frappe.generate_hash(length=6)}",
				"company": self.company,
				"gender": _male_gender(),
				"date_of_birth": "1985-03-10",
				"date_of_joining": joining,
				"status": "Active",
				"holiday_list": self.holiday_list,
				**fields,
			}
		).insert(ignore_permissions=True)
		if assign:
			frappe.get_doc(
				{
					"doctype": "Salary Structure Assignment",
					"employee": doc.name,
					"salary_structure": self.structure,
					"from_date": joining,
					"company": self.company,
					"currency": self.currency,
					"base": 4000,
				}
			).insert(ignore_permissions=True).submit()
		return doc.name

	def line(self, employee, key="K-1", amount=600, code=CODE, reason="a commission"):
		return {"key": key, "employee": employee, "wage_type_code": code, "amount": amount, "reason": reason}

	def plan(self, lines, **kwargs):
		with as_role(self.hr):
			return vp.plan(self.company, YEAR, MONTH, lines, **kwargs)

	def apply(self, lines, **kwargs):
		with as_role(self.hr):
			return vp.apply(self.company, YEAR, MONTH, lines, **kwargs)

	def verify(self, lines, **kwargs):
		with as_role(self.hr):
			return vp.verify(self.company, YEAR, MONTH, lines, **kwargs)

	def held(self, key):
		return frappe.get_all(
			"Additional Salary", filters={vp.KEY_FIELD: key, "docstatus": ("<", 2)}, pluck="name"
		)

	def slip(self, employee, submit=False):
		with patch("hrms.regional.switzerland.payroll_hooks.update_swiss_social_contributions"):
			slip = frappe.get_doc(
				{
					"doctype": "Salary Slip",
					"employee": employee,
					"start_date": "2033-05-01",
					"end_date": LAST_DAY,
					"posting_date": LAST_DAY,
				}
			)
			slip.insert(ignore_permissions=True)
			if submit:
				slip.submit()
		return slip

	def status(self, result, index=0):
		return result["lines"][index]["status"], result["lines"][index]["code"]


class TestWhatIsPlanned(VariablePayCase):
	def test_a_valid_line_is_to_create_and_the_plan_writes_nothing(self):
		employee = self.employee("Plan")
		before = frappe.db.count("Additional Salary")
		result = self.plan([self.line(employee, "K-PLAN")])
		self.assertEqual(self.status(result), ("to_create", None))
		self.assertEqual(result["period"]["payroll_date"], LAST_DAY)
		self.assertEqual(result["summary"]["to_create"], 1)
		self.assertEqual(result["summary"]["amount_to_create"], 600)
		self.assertEqual(frappe.db.count("Additional Salary"), before)
		self.assertEqual(self.held("K-PLAN"), [])

	def test_the_lines_that_cannot_be_paid_are_refused_and_said(self):
		employee = self.employee("Refused")
		inactive = self.employee("Inactive", status="Inactive")
		leaving = self.employee("Leaving", relieving_date="2033-05-15")
		joining = self.employee("Joining", assign=False, joining="2033-06-01")
		no_structure = self.employee("NoStructure", assign=False)
		cases = [
			("amount_not_positive", self.line(employee, "K-ZERO", amount=0)),
			("amount_not_positive", self.line(employee, "K-NEG", amount=-50)),
			("unknown_wage_type", self.line(employee, "K-WT", code="9999")),
			("not_an_earning", self.line(employee, "K-DED", code=DEDUCTION_CODE)),
			("wage_type_not_enabled", self.line(employee, "K-TIP", code=TIP_CODE)),
			("unknown_employee", self.line("HR-EMP-NOBODY", "K-GONE")),
			("inactive_employee", self.line(inactive, "K-INACTIVE")),
			("outside_employment", self.line(leaving, "K-LEAVING")),
			("outside_employment", self.line(joining, "K-JOINING")),
			("no_salary_structure", self.line(no_structure, "K-NOSTRUCT")),
			("invalid_line", {"key": "", "employee": employee, "wage_type_code": CODE, "amount": 5}),
		]
		result = self.plan([line for _code, line in cases])
		for index, (expected, _line) in enumerate(cases):
			with self.subTest(index=index, expected=expected):
				self.assertEqual(self.status(result, index), ("refused", expected))
				self.assertTrue(result["lines"][index]["message"])
		self.assertEqual(result["summary"]["refused"], len(cases))
		self.assertEqual(result["summary"]["to_create"], 0)

	def test_a_negative_amount_is_never_turned_into_a_deduction(self):
		employee = self.employee("Negative")
		result = self.apply([self.line(employee, "K-NEG2", amount=-80)])
		self.assertEqual(self.status(result), ("refused", "amount_not_positive"))
		self.assertEqual(self.held("K-NEG2"), [])

	def test_a_key_twice_in_a_batch_is_paid_once(self):
		employee = self.employee("Twice")
		result = self.plan([self.line(employee, "K-DUP"), self.line(employee, "K-DUP", amount=10)])
		self.assertEqual(self.status(result, 0), ("to_create", None))
		self.assertEqual(self.status(result, 1), ("refused", "duplicate_key"))

	def test_a_company_that_is_not_the_employees_refuses_the_line(self):
		employee = self.employee("Elsewhere")
		results = vp.classify("Another Company", YEAR, MONTH, [self.line(employee, "K-OTHER")])
		self.assertEqual((results[0]["status"], results[0]["code"]), ("refused", "other_company"))

	def test_a_bases_only_wage_type_is_paid_only_when_the_caller_names_it(self):
		employee = self.employee("Tip")
		off = self.plan([self.line(employee, "K-TIP2", code=TIP_CODE)])
		self.assertEqual(self.status(off), ("refused", "wage_type_not_enabled"))
		on = self.plan([self.line(employee, "K-TIP2", code=TIP_CODE)], allow_wage_types=[TIP_CODE])
		self.assertEqual(self.status(on), ("to_create", None))
		as_json = self.plan([self.line(employee, "K-TIP2", code=TIP_CODE)], allow_wage_types='["1297"]')
		self.assertEqual(self.status(as_json), ("to_create", None))

	def test_a_component_that_depends_on_the_days_paid_is_warned_about(self):
		employee = self.employee("Warned")
		frappe.db.set_value("Salary Component", self.component, "depends_on_payment_days", 1)
		self.addCleanup(frappe.db.set_value, "Salary Component", self.component, "depends_on_payment_days", 0)
		result = self.plan([self.line(employee, "K-WARN")])
		self.assertEqual(result["lines"][0]["warnings"], ["prorated_by_days_paid"])
		frappe.db.set_value("Salary Component", self.component, "depends_on_payment_days", 0)
		self.assertEqual(self.plan([self.line(employee, "K-WARN")])["lines"][0]["warnings"], [])


class TestWhatIsApplied(VariablePayCase):
	def test_an_additional_salary_is_made_submitted_non_recurring_and_dated_the_last_day(self):
		employee = self.employee("Apply")
		result = self.apply([self.line(employee, "K-APPLY", amount=612.35, reason="statement 2033-05")])
		self.assertEqual(result["created"], ["K-APPLY"])
		(name,) = self.held("K-APPLY")
		doc = frappe.get_doc("Additional Salary", name)
		self.assertEqual(
			(doc.docstatus, doc.is_recurring, str(doc.payroll_date), doc.type, doc.salary_component),
			(1, 0, LAST_DAY, "Earning", self.component),
		)
		self.assertEqual((flt(doc.amount), doc.company, doc.currency), (612.35, self.company, self.currency))
		self.assertEqual(doc.get(vp.REASON_FIELD), "statement 2033-05")
		self.assertEqual(result["lines"][0]["additional_salary"], name)

	def test_run_twice_it_creates_nothing_the_second_time(self):
		employee = self.employee("Replay")
		first = self.apply([self.line(employee, "K-REPLAY")])
		second = self.apply([self.line(employee, "K-REPLAY")])
		self.assertEqual(len(first["created"]), 1)
		self.assertEqual(second["created"], [])
		self.assertEqual(self.status(second), ("already_created", None))
		self.assertEqual(len(self.held("K-REPLAY")), 1)
		third = self.plan([self.line(employee, "K-REPLAY")])
		self.assertEqual(third["summary"]["already_created"], 1)

	def test_another_amount_under_the_same_key_is_blocked_and_nothing_changes(self):
		employee = self.employee("Differs")
		self.apply([self.line(employee, "K-DIFF", amount=600)])
		(name,) = self.held("K-DIFF")
		result = self.apply([self.line(employee, "K-DIFF", amount=650)])
		self.assertEqual(self.status(result), ("blocked", "amount_differs"))
		self.assertEqual(result["created"], [])
		self.assertEqual(flt(frappe.db.get_value("Additional Salary", name, "amount")), 600)
		self.assertEqual(self.held("K-DIFF"), [name])

	def test_a_draft_left_by_an_interrupted_import_is_blocked_not_duplicated(self):
		employee = self.employee("Draft")
		self.apply([self.line(employee, "K-DRAFT")])
		(name,) = self.held("K-DRAFT")
		frappe.db.set_value("Additional Salary", name, "docstatus", 0)
		result = self.apply([self.line(employee, "K-DRAFT")])
		self.assertEqual(self.status(result), ("blocked", "draft_exists"))
		self.assertEqual(self.held("K-DRAFT"), [name])

	def test_a_cancelled_additional_salary_is_made_again(self):
		employee = self.employee("Cancelled")
		self.apply([self.line(employee, "K-CANCEL")])
		(name,) = self.held("K-CANCEL")
		frappe.get_doc("Additional Salary", name).cancel()
		self.assertEqual(self.held("K-CANCEL"), [])
		again = self.apply([self.line(employee, "K-CANCEL")])
		self.assertEqual(again["created"], ["K-CANCEL"])
		self.assertEqual(len(self.held("K-CANCEL")), 1)

	def test_the_guard_refuses_a_second_live_document_with_the_same_key(self):
		employee = self.employee("Guard")
		self.apply([self.line(employee, "K-GUARD")])
		twin = frappe.get_doc(
			{
				"doctype": "Additional Salary",
				"employee": employee,
				"company": self.company,
				"salary_component": self.component,
				"type": "Earning",
				"amount": 600,
				"currency": self.currency,
				"payroll_date": LAST_DAY,
				vp.KEY_FIELD: "K-GUARD",
			}
		)
		with self.assertRaises(frappe.DuplicateEntryError):
			twin.insert(ignore_permissions=True)
		# no key, no guard: an Additional Salary typed by hand is none of its business
		twin.set(vp.KEY_FIELD, None)
		twin.insert(ignore_permissions=True)

	def test_a_line_that_fails_does_not_undo_the_lines_before_it(self):
		first, second = self.employee("FailsA"), self.employee("FailsB")
		real = frappe.get_doc

		def failing(*args, **kwargs):
			doc = real(*args, **kwargs)
			if (
				isinstance(args[0], dict)
				and args[0].get("employee") == second
				and args[0].get("doctype") == "Additional Salary"
			):
				raise RuntimeError("a failure of this line")
			return doc

		with patch("frappe.get_doc", side_effect=failing), patch("frappe.log_error"):
			result = self.apply([self.line(first, "K-F1"), self.line(second, "K-F2")])
		self.assertEqual((result["created"], result["failed"]), (["K-F1"], ["K-F2"]))
		self.assertEqual(len(self.held("K-F1")), 1)
		self.assertEqual(self.held("K-F2"), [])


class TestTheSlipOfTheMonth(VariablePayCase):
	"""The slip is the payroll: a draft takes the line, a submitted one is never touched."""

	def row(self, slip_name, component):
		return frappe.db.get_value(
			"Salary Detail",
			{"parent": slip_name, "salary_component": component},
			["amount", "additional_salary"],
			as_dict=True,
		)

	def test_a_draft_slip_takes_the_line_and_the_verification_finds_it(self):
		employee = self.employee("DraftSlip")
		slip = self.slip(employee)
		self.assertIsNone(self.row(slip.name, self.component))
		with patch("hrms.regional.switzerland.payroll_hooks.update_swiss_social_contributions"):
			result = self.apply([self.line(employee, "K-SLIP", amount=600)])
		self.assertEqual(result["created"], ["K-SLIP"])
		row = self.row(slip.name, self.component)
		self.assertEqual(flt(row.amount), 600)
		self.assertEqual(row.additional_salary, self.held("K-SLIP")[0])
		verified = self.verify([self.line(employee, "K-SLIP", amount=600)])
		self.assertTrue(verified["ok"], verified)
		self.assertEqual(verified["lines"][0]["state"], "ok")

	def test_a_submitted_slip_blocks_the_line_and_is_not_touched(self):
		employee = self.employee("SubmittedSlip")
		slip = self.slip(employee, submit=True)
		before = frappe.db.get_value("Salary Slip", slip.name, ["modified", "gross_pay", "docstatus"])
		result = self.apply([self.line(employee, "K-SUB")])
		self.assertEqual(self.status(result), ("blocked", "slip_submitted"))
		self.assertEqual(result["lines"][0]["salary_slip"], slip.name)
		self.assertEqual(self.held("K-SUB"), [])
		self.assertEqual(
			frappe.db.get_value("Salary Slip", slip.name, ["modified", "gross_pay", "docstatus"]), before
		)

	def test_the_commission_is_not_prorated_by_the_days_paid(self):
		"""An employee who joined on the 16th is paid 16 days of 31: a salary is prorated, a commission is not."""
		employee = self.employee("Joiner", joining="2033-05-16")
		slip = self.slip(employee)
		self.apply([self.line(employee, "K-PRO", amount=600)])
		slip.reload()
		slip = frappe.get_doc("Salary Slip", slip.name)
		with patch("hrms.regional.switzerland.payroll_hooks.update_swiss_social_contributions"):
			slip.save()
		self.assertLess(flt(slip.payment_days), flt(slip.total_working_days))
		self.assertLess(flt(self.row(slip.name, self.base_component).amount), 4000)
		self.assertEqual(flt(self.row(slip.name, self.component).amount), 600)

	def test_a_component_that_depends_on_the_days_paid_is_prorated_which_is_why_the_flag_matters(self):
		employee = self.employee("Control", joining="2033-05-16")
		slip = self.slip(employee)
		frappe.db.set_value("Salary Component", self.component, "depends_on_payment_days", 1)
		# a test does not roll back before the next one of its class: the flag goes back to what the fixture made
		self.addCleanup(frappe.db.set_value, "Salary Component", self.component, "depends_on_payment_days", 0)
		self.apply([self.line(employee, "K-CTRL", amount=600)])
		slip = frappe.get_doc("Salary Slip", slip.name)
		with patch("hrms.regional.switzerland.payroll_hooks.update_swiss_social_contributions"):
			slip.save()
		self.assertLess(flt(self.row(slip.name, self.component).amount), 600)

	def test_an_additional_salary_that_is_not_on_the_slip_is_found_by_the_verification(self):
		employee = self.employee("NotOnSlip")
		slip = self.slip(employee)
		# made by hand: the slip was not saved again
		frappe.get_doc(
			{
				"doctype": "Additional Salary",
				"employee": employee,
				"company": self.company,
				"salary_component": self.component,
				"type": "Earning",
				"amount": 600,
				"currency": self.currency,
				"payroll_date": LAST_DAY,
				vp.KEY_FIELD: "K-HAND",
			}
		).insert(ignore_permissions=True).submit()
		verified = self.verify([self.line(employee, "K-HAND", amount=600)])
		self.assertFalse(verified["ok"])
		self.assertEqual(verified["lines"][0]["state"], "not_on_slip")
		self.assertEqual(verified["lines"][0]["salary_slip"], slip.name)


class TestTheVerification(VariablePayCase):
	def test_missing_then_ok_then_mismatch(self):
		employee = self.employee("Verify")
		lines = [self.line(employee, "K-VERIFY")]
		self.assertEqual(self.verify(lines)["lines"][0]["state"], "missing")
		self.apply(lines)
		verified = self.verify(lines)
		self.assertTrue(verified["ok"])
		self.assertEqual(verified["lines"][0]["state"], "no_slip_yet")
		(name,) = self.held("K-VERIFY")
		frappe.db.set_value("Additional Salary", name, "payroll_date", "2033-05-15")
		self.assertEqual(self.verify(lines)["lines"][0]["state"], "mismatch")
		frappe.db.set_value("Additional Salary", name, {"payroll_date": LAST_DAY, "amount": 1})
		mismatch = self.verify(lines)
		self.assertEqual(mismatch["lines"][0]["state"], "mismatch")
		self.assertFalse(mismatch["ok"])

	def test_a_refused_line_is_not_ok(self):
		employee = self.employee("VerifyRefused")
		verified = self.verify([self.line(employee, "K-VR", amount=0)])
		self.assertFalse(verified["ok"])
		self.assertEqual(verified["lines"][0]["state"], "refused")


class TestWhoMayDoIt(VariablePayCase):
	"""Anonymous, a portal account and an employee who holds no payroll role see nothing and create nothing."""

	def lines(self):
		return [self.line(self.employee("Gate"), "K-GATE")]

	def assertRefused(self, user):
		lines = self.lines()
		for method in (vp.plan, vp.apply, vp.verify):
			with self.subTest(user=user, method=method.__name__):
				with as_role(user), self.assertRaises(frappe.PermissionError):
					method(self.company, YEAR, MONTH, lines)
		self.assertEqual(self.held("K-GATE"), [])

	def test_a_visitor_is_refused(self):
		self.assertRefused("Guest")

	def test_a_portal_account_is_refused(self):
		self.assertRefused(self.portal)

	def test_an_employee_without_a_payroll_role_is_refused(self):
		self.assertRefused(self.ordinary)

	def test_an_employee_without_a_payroll_role_cannot_even_read_the_plan_of_a_colleague(self):
		employee = self.employee("Colleague")
		with as_role(self.ordinary):
			with self.assertRaises(frappe.PermissionError):
				vp.plan(self.company, YEAR, MONTH, [self.line(employee, "K-COL")])

	def test_the_payroll_staff_who_cannot_create_an_additional_salary_plans_but_does_not_apply(self):
		employee = self.employee("ManagerOnly")
		line = self.line(employee, "K-MGR")
		with as_role(self.hr_manager_only):
			self.assertEqual(vp.plan(self.company, YEAR, MONTH, [line])["summary"]["to_create"], 1)
			with self.assertRaises(frappe.PermissionError):
				vp.apply(self.company, YEAR, MONTH, [line])
		self.assertEqual(self.held("K-MGR"), [])

	def test_the_payroll_staff_passes(self):
		employee = self.employee("Staff")
		self.assertEqual(self.status(self.plan([self.line(employee, "K-STAFF")])), ("to_create", None))


class TestThePreflightOfTheMonthlyCycle(VariablePayCase):
	def hooks(self, providers):
		original = frappe.get_hooks

		def get_hooks(hook=None, *args, **kwargs):
			if hook == "variable_pay_providers":
				return list(providers)
			return original(hook, *args, **kwargs)

		return patch("frappe.get_hooks", get_hooks)

	def issues(self, providers):
		from hrms.regional.switzerland import monthly_cycle

		with self.hooks(providers), as_role(self.hr):
			return monthly_cycle.preflight(self.company, YEAR, MONTH)["issues"]

	def test_without_a_provider_the_preflight_says_nothing_new(self):
		codes = {issue["code"] for issue in self.issues([])}
		self.assertFalse({c for c in codes if c.startswith("variable_pay")})

	def test_what_a_provider_announced_and_is_not_on_the_payroll_is_a_warning(self):
		employee = self.employee("Announced")
		announce.lines = [self.line(employee, "K-ANN", amount=250)]
		pending = [i for i in self.issues([PROVIDER]) if i["code"] == "variable_pay_pending"]
		self.assertEqual([(i["level"]) for i in pending], ["warning"])
		self.apply(announce.lines)
		self.assertEqual([i for i in self.issues([PROVIDER]) if i["code"] == "variable_pay_pending"], [])

	def test_what_cannot_be_added_is_a_warning_too(self):
		employee = self.employee("AnnouncedBlocked")
		self.slip(employee, submit=True)
		announce.lines = [self.line(employee, "K-ANNB")]
		blocked = [i for i in self.issues([PROVIDER]) if i["code"] == "variable_pay_blocked"]
		self.assertEqual(len(blocked), 1)

	def test_a_provider_that_fails_does_not_fail_the_preflight(self):
		with patch("frappe.log_error"):
			issues = self.issues([BROKEN_PROVIDER])
		self.assertIn("variable_pay_provider_failed", {i["code"] for i in issues})


class TestTheCatalogue(unittest.TestCase):
	def test_a_commission_and_a_tip_do_not_depend_on_the_days_paid(self):
		entries = {entry["code"]: entry for entry in wage_type_data.get_swiss_wage_types()}
		self.assertEqual(entries["1218"]["depends_on_payment_days"], 0)
		self.assertEqual(entries["1920"]["depends_on_payment_days"], 0)

	def test_the_other_bonuses_are_not_changed(self):
		entries = {entry["code"]: entry for entry in wage_type_data.get_swiss_wage_types()}
		self.assertEqual(entries["1217"]["depends_on_payment_days"], 1)
		self.assertEqual(entries["1000"]["depends_on_payment_days"], 1)


class TestThePatch(VariablePayCase):
	def test_it_pushes_the_flag_down_to_the_wage_types_the_components_and_the_structures(self):
		from hrms.patches.v15_0 import switzerland_unprorated_variable_pay as patch_module

		for code in ("1218", "1920"):
			wage_type = _ensure_wage_type(code, f"Test {code}")
			frappe.db.set_value("Swiss Wage Type", wage_type, "depends_on_payment_days", 1)
		component = self._component("_Test VP Patch 1218", "1218", prorated=1)
		structure = frappe.get_doc(
			{
				"doctype": "Salary Structure",
				"name": "_Test VP Patch Structure",
				"company": self.company,
				"currency": self.currency,
				"payroll_frequency": "Monthly",
				"is_active": "Yes",
				"earnings": [{"salary_component": component, "amount": 100, "depends_on_payment_days": 1}],
				"deductions": [],
			}
		)
		structure.insert(ignore_permissions=True)
		with patch("builtins.print"):
			patch_module.execute()
		for code in ("1218", "1920"):
			self.assertEqual(
				frappe.db.get_value("Swiss Wage Type", f"CH-WT-{code}", "depends_on_payment_days"), 0
			)
		self.assertEqual(frappe.db.get_value("Salary Component", component, "depends_on_payment_days"), 0)
		self.assertEqual(
			frappe.db.get_value(
				"Salary Detail",
				{"parent": structure.name, "salary_component": component},
				"depends_on_payment_days",
			),
			0,
		)
		# another component of the same structure is left as it was
		self.assertEqual(
			frappe.db.get_value("Salary Component", self.base_component, "depends_on_payment_days"), 1
		)

	def test_the_second_run_changes_nothing(self):
		from hrms.patches.v15_0 import switzerland_unprorated_variable_pay as patch_module

		with patch("builtins.print"):
			patch_module.execute()
		with patch("builtins.print") as printed:
			patch_module.execute()
		self.assertFalse(printed.called)
