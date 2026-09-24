# //// Neoffice — added file (no upstream equivalent): the Salary Slip validate hook that computes
# //// the Swiss contributions decides how much is withheld from a real payslip. Its defects are
# //// silent — a slip comes out looking normal with a contribution missing or halved — so each
# //// one is pinned here by the amount it must produce, not by the code path it takes.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, getdate, money_in_words, nowdate

# //// Neoffice — tests of an added file (no upstream equivalent).
from hrms.regional.switzerland.payroll_hooks import (
	_resolve_component_by_wage_type,
	update_swiss_social_contributions,
)
from hrms.regional.switzerland.utils import get_salary_slip_print_data

# A canton nobody configures in the demo data: the canton-specific config lookup wins over the
# company default, so the rates asserted below are ours and not the site's.
TEST_CANTON = "GR"
HOURLY_COMPONENT = "_Test CH Hourly Wage"
MONTHLY_COMPONENT = "_Test CH Monthly Salary"

# Rates of the config created in setUpClass — every expected amount below derives from these.
AVS_RATE_EE = 5.3
AVS_RATE_ER = 5.3
AC_RATE_EE = 1.1
AC_RATE_ER = 1.1
LAA_NP_RATE = 1.0
IJM_RATE_EE = 0.7

DEDUCTION_COMPONENTS = (
	"AVS/AI/APG Employee",
	"AVS/AI/APG Employer",
	"AC/ALV Employee",
	"AC/ALV Employer",
	"LAA Professional Employer",
	"LAA Non-Professional Employee",
	"IJM/KTG Employee",
	"IJM/KTG Employer",
	"Family Allowances Employer",
	"LPP/BVG Employee",
	"LPP/BVG Employer",
)


def _ensure_custom_fields():
	"""The ch_* fields live in Custom Fields created by the Swiss setup, which only runs for a
	Swiss company. A test site set up in India (hrms.tests.test_utils.before_tests) has none, and
	every lookup below would fail on an unknown column."""
	if (
		not frappe.db.has_column("Salary Component", "ch_subject_to_avs")
		or not frappe.db.has_column("Salary Slip", "ch_contribution_bases")
		or not frappe.db.has_column("Salary Slip", "ch_accrual_entry")
		or not frappe.db.has_column("Salary Component Account", "ch_expense_account")
		or not frappe.db.has_column("Employee", "ch_lpp_after_reference_age")
	):
		from hrms.regional.switzerland.setup import make_custom_fields

		make_custom_fields()


def _ensure_wage_type(code, name):
	doc_name = f"CH-WT-{code}"
	if not frappe.db.exists("Swiss Wage Type", doc_name):
		frappe.get_doc(
			{
				"doctype": "Swiss Wage Type",
				"code": code,
				"wage_type_name": name,
				"type": "Earning",
				"statistical_category": "BS",
			}
		).insert(ignore_permissions=True)
	return doc_name


def _ensure_component(name, component_type, wage_type=None, subject_to=1):
	if not frappe.db.exists("Salary Component", name):
		frappe.get_doc(
			{
				"doctype": "Salary Component",
				"salary_component": name,
				"salary_component_abbr": "".join(w[0] for w in name.split())[:8],
				"type": component_type,
			}
		).insert(ignore_permissions=True)

	# Force the fields the calculation depends on, whatever the site already had.
	frappe.db.set_value(
		"Salary Component",
		name,
		{
			"depends_on_payment_days": 1,
			"do_not_include_in_total": 0,
			"ch_wage_type": wage_type,
			"ch_subject_to_avs": subject_to,
			"ch_subject_to_ac": subject_to,
			"ch_subject_to_laa": subject_to,
			"ch_subject_to_ijm": subject_to,
			"ch_subject_to_lpp": subject_to,
			"ch_subject_to_imp": subject_to,
		},
		update_modified=False,
	)
	return name


class SwissPayrollHookCase(FrappeTestCase):
	"""One Swiss company, one employee, one config in TEST_CANTON — no site data relied upon."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_custom_fields()

		cls.company = frappe.db.get_value("Company", {"country": "Switzerland"}, "name")
		if not cls.company:
			# A site set up outside Switzerland: borrow a company for the class (rolled back).
			cls.company = frappe.db.get_value("Company", {}, "name")
			frappe.db.set_value("Company", cls.company, "country", "Switzerland")

		cls.wage_type_monthly = _ensure_wage_type("1000", "Salaire mensuel")
		cls.wage_type_hourly = _ensure_wage_type("1005", "Salaire horaire")
		_ensure_component(MONTHLY_COMPONENT, "Earning", wage_type=cls.wage_type_monthly)
		_ensure_component(HOURLY_COMPONENT, "Earning", wage_type=cls.wage_type_hourly)
		for name in DEDUCTION_COMPONENTS:
			_ensure_component(name, "Deduction")

		cls.config = cls._make_config()
		cls.employee = cls._make_employee()

	@classmethod
	def _make_config(cls):
		name = f"CH-SIC-{cls.company}-{TEST_CANTON}"
		if frappe.db.exists("Swiss Social Insurance Config", name):
			frappe.delete_doc("Swiss Social Insurance Config", name, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "Swiss Social Insurance Config",
				"company": cls.company,
				"canton": TEST_CANTON,
				"is_default": 0,
				"avs_rate_employee": AVS_RATE_EE,
				"avs_rate_employer": AVS_RATE_ER,
				"ac_rate_employee": AC_RATE_EE,
				"ac_rate_employer": AC_RATE_ER,
				"laa_professional_rate": 0,
				"laa_nonprofessional_rate": LAA_NP_RATE,
				"ijm_rate_employee": IJM_RATE_EE,
				"ijm_rate_employer": 0,
				"family_allowance_rate": 0,
				"thirteenth_month_mode": "Disabled",
				"qst_enabled": 0,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	@classmethod
	def _make_employee(cls):
		email = "swiss-payroll-hook-test@yopmail.com"
		existing = frappe.db.get_value("Employee", {"personal_email": email}, "name")
		if existing:
			frappe.db.set_value("Employee", existing, "ch_fiscal_canton", TEST_CANTON)
			return existing
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Swiss",
				"last_name": "HookTest",
				"company": cls.company,
				# Gender is a mandatory Link and its records are localized ("Masculin" on a
				# French site): take whatever the site has, it changes no contribution.
				"gender": frappe.db.get_value("Gender", {"name": "Male"}, "name")
				or frappe.db.get_value("Gender", {}, "name"),
				"date_of_birth": "1985-03-10",
				"date_of_joining": "2020-01-01",
				"status": "Active",
				"personal_email": email,
				"ch_fiscal_canton": TEST_CANTON,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_slip(self, earnings, payment_days=None, total_working_days=20, deduction_rows=True):
		"""A Salary Slip document that never reaches the database: the hook runs on validate,
		before the insert, so a document object is the real subject under test.

		deduction_rows mirrors what a Salary Structure produces — every Swiss component present
		with a zero amount, which is what the 48 submitted slips of the demo company look like.
		Pass False to exercise the path that ADDS a row the structure did not carry."""
		slip = frappe.new_doc("Salary Slip")
		slip.employee = self.employee
		slip.employee_name = "Swiss HookTest"
		slip.company = self.company
		slip.currency = "CHF"
		slip.exchange_rate = 1
		slip.payroll_frequency = "Monthly"
		year = getdate(nowdate()).year
		slip.start_date = f"{year}-03-01"
		slip.end_date = f"{year}-03-31"
		slip.posting_date = f"{year}-03-31"
		slip.total_working_days = total_working_days
		slip.payment_days = total_working_days if payment_days is None else payment_days
		# validate() sets this before the hook runs; get_amount_based_on_payment_days reads it.
		slip._salary_structure_doc = frappe._dict(salary_component=None)
		for component, amount in earnings:
			row = slip.append("earnings", {})
			row.salary_component = component
			row.abbr = frappe.db.get_value("Salary Component", component, "salary_component_abbr")
			row.depends_on_payment_days = 1
			row.default_amount = amount
			row.amount = amount
		if deduction_rows:
			for component in DEDUCTION_COMPONENTS:
				row = slip.append("deductions", {})
				row.salary_component = component
				row.abbr = frappe.db.get_value("Salary Component", component, "salary_component_abbr")
				row.depends_on_payment_days = 1
				row.default_amount = 0
				row.amount = 0
		return slip

	def _deduction(self, slip, component):
		for row in slip.get("deductions"):
			if row.salary_component == component:
				return row
		return None

	def _amount(self, slip, component):
		row = self._deduction(slip, component)
		return flt(row.amount, 2) if row else None


class TestHourlyEmployeeContributions(SwissPayrollHookCase):
	"""An employee paid by the hour owes exactly the same contributions as a monthly one."""

	def test_hourly_wage_is_charged_avs_ac_laa_ijm(self):
		slip = self._make_slip([(HOURLY_COMPONENT, 6000)])
		update_swiss_social_contributions(slip, "validate")

		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 318.00)  # 6000 x 5.3%
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employer"), 318.00)
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 66.00)  # 6000 x 1.1%
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 60.00)  # 6000 x 1.0%
		self.assertEqual(self._amount(slip, "IJM/KTG Employee"), 42.00)  # 6000 x 0.7%

	def test_hourly_wage_is_an_lpp_base(self):
		"""No monthly salary component means no fixed annual salary — annualize what was paid."""
		slip = self._make_slip([(HOURLY_COMPONENT, 6000)])
		update_swiss_social_contributions(slip, "validate")

		lpp = self._amount(slip, "LPP/BVG Employee")
		self.assertIsNotNone(lpp, "LPP was not computed for an hourly employee")
		self.assertGreater(lpp, 0)

	def test_monthly_employee_is_unchanged(self):
		"""Witness: the monthly path this fix must not move."""
		slip = self._make_slip([(MONTHLY_COMPONENT, 6000)])
		update_swiss_social_contributions(slip, "validate")

		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 318.00)
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 66.00)


class TestComponentSubjectToNothing(SwissPayrollHookCase):
	"""A wage type subject to nothing stays out of every base — found by the Odoo bench."""

	EXPENSES = "_Test CH Travel Expenses"
	LEGACY = "_Test CH Legacy Allowance"

	def test_expenses_are_not_charged(self):
		"""500 of travel expenses (6000) on a 6'000 salary: the contributions of 6'000 only."""
		_ensure_component(self.EXPENSES, "Earning", subject_to=0)
		frappe.db.set_value(
			"Salary Component", self.EXPENSES, "ch_wage_type_code", "6000", update_modified=False
		)
		slip = self._make_slip([(MONTHLY_COMPONENT, 6000), (self.EXPENSES, 500)])
		update_swiss_social_contributions(slip, "validate")

		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 318.00)  # was 344.50
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 66.00)
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 60.00)
		self.assertEqual(self._amount(slip, "IJM/KTG Employee"), 42.00)

	def test_a_component_without_wage_type_nor_flag_still_counts_everywhere(self):
		"""Installations that predate the flags: such a component feeds every base, as before."""
		_ensure_component(self.LEGACY, "Earning", subject_to=0)
		frappe.db.set_value(
			"Salary Component",
			self.LEGACY,
			{"ch_wage_type": None, "ch_wage_type_code": None},
			update_modified=False,
		)
		slip = self._make_slip([(MONTHLY_COMPONENT, 6000), (self.LEGACY, 500)])
		update_swiss_social_contributions(slip, "validate")

		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 344.50)  # 6'500 x 5.3 %


# //// Neoffice — tests of an added file (no upstream equivalent).
class TestPartialMonthIsProratedOnce(SwissPayrollHookCase):
	"""A base already built from the amounts paid must not be prorated a second time."""

	def _half_month_slip(self, deduction_rows):
		slip = self._make_slip([], payment_days=10, total_working_days=20, deduction_rows=deduction_rows)
		row = slip.append("earnings", {})
		row.salary_component = MONTHLY_COMPONENT
		row.abbr = frappe.db.get_value("Salary Component", MONTHLY_COMPONENT, "salary_component_abbr")
		row.depends_on_payment_days = 1
		# What frappe itself writes on a half month: the full salary in default_amount, the
		# amount actually paid in amount.
		row.default_amount = 6000
		row.amount = 3000
		return slip

	def test_row_added_by_the_hook(self):
		"""The path that ADDS a missing row — where the second proration used to happen."""
		slip = self._half_month_slip(deduction_rows=False)
		update_swiss_social_contributions(slip, "validate")
		# 3000 paid x 5.3%, NOT 3000 x 5.3% x 10/20
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 159.00)
		self.assertEqual(self._amount(slip, "IJM/KTG Employee"), 21.00)

	def test_row_already_on_the_slip(self):
		"""The witness: the update path was already right, so the two must agree."""
		slip = self._half_month_slip(deduction_rows=True)
		update_swiss_social_contributions(slip, "validate")
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 159.00)
		self.assertEqual(self._amount(slip, "IJM/KTG Employee"), 21.00)


class TestSourceTaxBase(SwissPayrollHookCase):
	"""Source tax is withheld on the components subject to it, not on the whole gross."""

	QST_CANTON = "ZH"
	QST_CODE = "Z9N"  # a code no canton publishes: the fixture below is alone on it
	QST_RATE = 0.10
	EXEMPT_COMPONENT = "_Test CH Expense Refund"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# An earning explicitly NOT subject to source tax (an expense refund is the real case).
		_ensure_component(cls.EXEMPT_COMPONENT, "Earning", subject_to=0)
		frappe.db.set_value("Salary Component", cls.EXEMPT_COMPONENT, "ch_subject_to_avs", 1)
		_ensure_component("Source Tax Employee", "Deduction")

		frappe.db.set_value("Swiss Social Insurance Config", cls.config, "qst_enabled", 1)
		frappe.db.set_value(
			"Employee",
			cls.employee,
			{
				"ch_qst_subject": 1,
				"ch_qst_taxation_canton": cls.QST_CANTON,
				"ch_qst_tariff_code": cls.QST_CODE,
			},
		)
		cls.tariff = cls._make_tariff()

	@classmethod
	def _make_tariff(cls):
		name = f"QST-{cls.QST_CANTON}-2099-SAL"
		if frappe.db.exists("Swiss QST Tariff", name):
			frappe.delete_doc("Swiss QST Tariff", name, force=True)
		tariff = frappe.get_doc(
			{
				"doctype": "Swiss QST Tariff",
				"canton": cls.QST_CANTON,
				"year": 2099,
				# //// Neoffice — was the French "Salaires" (b62d7bdeb "fix(swiss-payroll): the tariff
				# //// type, the field labels and the payslip wording leave French behind")
				"tariff_type": "Salary",
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Swiss QST Tariff Bracket",
				"parent_tariff": tariff.name,
				"canton": cls.QST_CANTON,
				"tariff_code": cls.QST_CODE,
				"tariff_type": "SAL",
				"valid_from": "2020-01-01",
				"income_from": 0,
				"income_step": 100,
				"tax_rate": cls.QST_RATE,
			}
		).insert(ignore_permissions=True)
		return tariff.name

	def _source_tax_amount(self, slip):
		component = _resolve_component_by_wage_type(5060, "Source Tax Employee")
		return self._amount(slip, component)

	def test_exempt_earning_is_not_taxed(self):
		slip = self._make_slip([(MONTHLY_COMPONENT, 5000), (self.EXEMPT_COMPONENT, 2000)])
		update_swiss_social_contributions(slip, "validate")
		# 5000 subject to source tax x 10%, not 7000 x 10%
		self.assertEqual(self._source_tax_amount(slip), 500.00)

	def test_subject_earnings_are_taxed_in_full(self):
		"""Witness: without an exempt component the base is the whole gross, as before."""
		slip = self._make_slip([(MONTHLY_COMPONENT, 5000)])
		update_swiss_social_contributions(slip, "validate")
		self.assertEqual(self._source_tax_amount(slip), 500.00)

	def test_exempt_earning_still_feeds_avs(self):
		"""The flags are per insurance: the refund is out of the source-tax base only."""
		slip = self._make_slip([(MONTHLY_COMPONENT, 5000), (self.EXEMPT_COMPONENT, 2000)])
		update_swiss_social_contributions(slip, "validate")
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 371.00)  # 7000 x 5.3%

	# //// Neoffice — added: the slip keeps the canton its source tax was computed with.
	def test_the_slip_keeps_the_canton_it_was_settled_with(self):
		"""The recap per canton reads it: the employee may live elsewhere by year end."""
		slip = self._make_slip([(MONTHLY_COMPONENT, 5000)])
		update_swiss_social_contributions(slip, "validate")
		self.assertEqual((slip.ch_qst_canton, slip.ch_qst_tariff_code), (self.QST_CANTON, self.QST_CODE))


# //// Neoffice — added: the annual AC ceiling is the only contribution here whose amount depends
# //// on the MONTHS BEFORE the slip, so it is the only one a unit test on a single slip cannot
# //// catch. These tests put real submitted slips behind the current one and read the amount
# //// withheld in the month that crosses the ceiling.
class TestAcCeilingTracksTheAcBase(SwissPayrollHookCase):
	"""The ceiling is measured against the AC-SUBJECT cumulative, not against gross pay — and
	cumulated over the year, prorated to the contribution days (Swissdec guidelines 7.12.3).

	It used to be compared to SUM(gross_pay) of the prior slips: any earning that owes no AC
	still pushed the employee towards the ceiling. And it used to be the whole yearly ceiling
	from January, never prorated to the months elapsed.
	"""

	NON_AC_COMPONENT = "_Test CH Meal Allowance"
	CEILING = 36000  # 3'000 a month, 100 a day: every room below reads at a glance
	AC_PER_MONTH = 2000
	NON_AC_PER_MONTH = 1000

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# An earning subject to AVS but explicitly NOT to AC — a meal allowance is the real case.
		_ensure_component(cls.NON_AC_COMPONENT, "Earning", subject_to=0)
		frappe.db.set_value("Salary Component", cls.NON_AC_COMPONENT, "ch_subject_to_avs", 1)
		frappe.db.set_value("Swiss Social Insurance Config", cls.config, "ac_annual_ceiling", cls.CEILING)

	def setUp(self):
		self.year = getdate(nowdate()).year
		self.slips = []

	def tearDown(self):
		# The class shares one transaction across its tests, so the history one test builds
		# would still be there for the next — and the fixed names would collide. Delete exactly
		# the rows this test created, nothing broader.
		for name in self.slips:
			frappe.db.delete("Salary Detail", {"parent": name, "parenttype": "Salary Slip"})
			frappe.db.delete("Salary Slip", {"name": name})
		super().tearDown()

	def _submitted_slip(self, month, earnings):
		"""A submitted Salary Slip written straight to the tables.

		db_insert() skips validate() on purpose: the subject under test is what the YTD reader
		SEES in the database, and running the Swiss hook while building the history would make
		the fixture depend on the very code being measured. FrappeTestCase rolls it all back.
		"""
		last_day = 31 if month in (1, 3, 5, 7, 8, 10, 12) else (28 if month == 2 else 30)
		name = f"_T-Swiss-AC-{self.year}-{month:02d}"
		slip = frappe.get_doc(
			{
				"doctype": "Salary Slip",
				"employee": self.employee,
				"company": self.company,
				"currency": "CHF",
				"exchange_rate": 1,
				"payroll_frequency": "Monthly",
				"start_date": f"{self.year}-{month:02d}-01",
				"end_date": f"{self.year}-{month:02d}-{last_day}",
				"posting_date": f"{self.year}-{month:02d}-{last_day}",
				"docstatus": 1,
				"gross_pay": sum(amount for _c, amount in earnings),
			}
		)
		slip.name = name
		slip.db_insert()
		for idx, (component, amount) in enumerate(earnings, 1):
			row = frappe.get_doc(
				{
					"doctype": "Salary Detail",
					"parent": name,
					"parenttype": "Salary Slip",
					"parentfield": "earnings",
					"idx": idx,
					"salary_component": component,
					"abbr": frappe.db.get_value("Salary Component", component, "salary_component_abbr"),
					"amount": amount,
					"default_amount": amount,
					"do_not_include_in_total": 0,
				}
			)
			row.name = f"{name}-{idx}"
			row.db_insert()
		self.slips.append(name)
		return name

	def _two_months_of_history(self):
		"""January and February: 3'000 gross each, of which 2'000 is subject to AC."""
		for month in (1, 2):
			self._submitted_slip(
				month,
				[
					(MONTHLY_COMPONENT, self.AC_PER_MONTH),
					(self.NON_AC_COMPONENT, self.NON_AC_PER_MONTH),
				],
			)

	def _slip_for(self, month, earnings):
		slip = self._make_slip(earnings)
		last_day = 31 if month in (1, 3, 5, 7, 8, 10, 12) else (28 if month == 2 else 30)
		slip.start_date = f"{self.year}-{month:02d}-01"
		slip.end_date = slip.posting_date = f"{self.year}-{month:02d}-{last_day}"
		update_swiss_social_contributions(slip, "validate")
		return slip

	def test_ytd_ac_base_is_not_the_ytd_gross(self):
		"""The two figures must differ — that difference is the first defect."""
		from hrms.regional.switzerland.utils import (
			get_ytd_ac_base_for_employee,
			get_ytd_gross_for_employee,
		)

		self._two_months_of_history()
		march = f"{self.year}-03-01"

		ytd_gross = get_ytd_gross_for_employee(self.employee, self.company, march, march)
		ytd_ac = get_ytd_ac_base_for_employee(self.employee, self.company, march, march)

		self.assertEqual(flt(ytd_gross, 2), 6000.00)  # 2 x 3'000, everything
		self.assertEqual(flt(ytd_ac, 2), 4000.00)  # 2 x 2'000, AC-subject only

	def test_a_big_month_uses_the_room_the_year_left(self):
		"""March, with a bonus: 8'000 of AC base after two months at 2'000.

		End of February, 60 days: room 6'000, insured 4'000. End of March, 90 days: room 9'000,
		cumulated base 12'000 — insured 9'000. March insures 9'000 - 4'000 = 5'000: 55.00.
		Read against the gross cumulative, February would already have filled its room (6'000)
		and March insured 3'000 only: 33.00, employee and employer each undercharged.
		"""
		self._two_months_of_history()
		slip = self._slip_for(3, [(MONTHLY_COMPONENT, 8000), (self.NON_AC_COMPONENT, self.NON_AC_PER_MONTH)])
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 55.00)  # 5000 x 1.1%
		self.assertEqual(self._amount(slip, "AC/ALV Employer"), 55.00)

	def test_the_first_month_paid_here_has_one_month_of_room(self):
		"""No history: the months of the year paid elsewhere are unknown, so they lend no room.

		11'000 in March against 3'000 of room: 33.00. The old rule charged the whole 11'000 —
		121.00 — to a company onboarded in March, whatever it had paid before.
		"""
		slip = self._slip_for(3, [(MONTHLY_COMPONENT, 11000)])
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 33.00)

	def test_six_months_insure_six_months_of_room(self):
		"""Six months at 6'000 against 3'000 of room a month: every month insures 3'000.

		The old rule measured the whole 36'000 yearly ceiling from January: June still had
		6'000 of room left and was charged in full, 66.00. A leaver at the end of June had
		paid AC on 36'000 — twice what six months of employment allow.
		"""
		for month in (1, 2, 3, 4, 5):
			self._submitted_slip(month, [(MONTHLY_COMPONENT, 6000)])
		slip = self._slip_for(6, [(MONTHLY_COMPONENT, 6000)])
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 33.00)  # 3000 x 1.1%

	def test_a_13th_month_in_december_keeps_the_laa_room_of_the_year(self):
		"""11'000 a month, and the 13th month on top in December: 22'000.

		The year insures 143'000, under the 148'200 LAA ceiling: December is insured in full,
		220.00 of non-occupational premium at 1 %. Capped at 12'350 on its own, it was 123.50.
		"""
		for month in range(1, 12):
			self._submitted_slip(month, [(MONTHLY_COMPONENT, 11000)])
		slip = self._slip_for(12, [(MONTHLY_COMPONENT, 22000)])
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 220.00)

	def test_a_slip_with_no_flag_at_all_counts_in_full(self):
		"""Backward compatibility: an installation that never configured the flags.

		_get_insurance_base_totals falls back to the whole earnings total when NO component of
		the slip carries a flag; the cumulative has to fall back the same way, slip by slip, or
		the history of such an installation would read as zero and the ceiling would never bite.
		"""
		from hrms.regional.switzerland.utils import get_ytd_ac_base_for_employee

		unflagged = "_Test CH Unflagged Earning"
		_ensure_component(unflagged, "Earning", subject_to=0)
		self._submitted_slip(1, [(unflagged, 9000)])

		ytd_ac = get_ytd_ac_base_for_employee(
			self.employee, self.company, f"{self.year}-03-01", f"{self.year}-03-01"
		)
		self.assertEqual(flt(ytd_ac, 2), 9000.00)

	def test_a_row_excluded_from_the_total_is_excluded_from_the_cumulative(self):
		"""do_not_include_in_total is skipped when the month is computed; so it must be here."""
		from hrms.regional.switzerland.utils import get_ytd_ac_base_for_employee

		self._submitted_slip(1, [(MONTHLY_COMPONENT, 11000)])
		frappe.db.set_value("Salary Detail", f"_T-Swiss-AC-{self.year}-01-1", "do_not_include_in_total", 1)

		ytd_ac = get_ytd_ac_base_for_employee(
			self.employee, self.company, f"{self.year}-03-01", f"{self.year}-03-01"
		)
		self.assertEqual(flt(ytd_ac, 2), 0.00)


# //// Neoffice — tests of an added file (no upstream equivalent).
class TestInsuranceSolutionsThroughTheHook(SwissPayrollHookCase):
	"""LAA cap, LAA code scopes and business units, LAAC / IJM codes — through the real hook.

	Swissdec guidelines 7.4.2 (LAA code: business unit + scope 0/1/2/3) and 7.6.1 / 7.7
	(LAAC / IJM codes, rates by category, wage bracket and sex).
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for name in ("LAA Non-Professional Employer", "LAAC Employee", "LAAC Employer"):
			_ensure_component(name, "Deduction")
		# A site may carry a single Gender record ("Masculin" on the test site): skipping
		# would leave the rates-by-sex path unverified, so the record is created instead.
		cls.female = frappe.db.get_value("Gender", {"name": ["in", ["Female", "Féminin"]]}, "name")
		if not cls.female:
			cls.female = (
				frappe.get_doc({"doctype": "Gender", "gender": "Female"}).insert(ignore_permissions=True).name
			)

	def setUp(self):
		self._gender = frappe.db.get_value("Employee", self.employee, "gender")

	def tearDown(self):
		frappe.db.set_value(
			"Employee",
			self.employee,
			{
				"ch_laa_code": None,
				"ch_laac_code": None,
				"ch_laac_code_2": None,
				"ch_ijm_code": None,
				"ch_ijm_code_2": None,
				"gender": self._gender,
			},
			update_modified=False,
		)
		self._set_solutions([])

	def _set_solutions(self, rows):
		config = frappe.get_doc("Swiss Social Insurance Config", self.config)
		config.set("insurance_solutions", rows)
		config.save(ignore_permissions=True)

	def _employee(self, **values):
		frappe.db.set_value("Employee", self.employee, values, update_modified=False)

	def _run(self, monthly_salary):
		slip = self._make_slip([(MONTHLY_COMPONENT, monthly_salary)])
		update_swiss_social_contributions(slip, "validate")
		return slip

	def test_laa_is_capped_at_12350_a_month(self):
		"""CHF 148'200 a year: above CHF 12'350 a month nothing more is insured, nor charged."""
		slip = self._run(20000)
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 123.50)  # not 200.00

	def test_under_the_cap_nothing_moves(self):
		"""Witness: the ordinary case keeps its amount to the centime."""
		self.assertEqual(self._amount(self._run(6000), "LAA Non-Professional Employee"), 60.00)

	def test_scope_3_charges_no_non_occupational_premium(self):
		"""Under 8 hours a week: insured for occupational accidents only."""
		self._employee(ch_laa_code="A3")
		self.assertEqual(self._amount(self._run(2000), "LAA Non-Professional Employee"), 0.0)

	def test_scope_2_moves_the_premium_to_the_employer(self):
		self._employee(ch_laa_code="A2")
		slip = self._run(6000)
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 0.0)
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employer"), 60.00)

	def test_scope_0_is_not_insured(self):
		self._employee(ch_laa_code="A0")
		self.assertEqual(self._amount(self._run(6000), "LAA Non-Professional Employee"), 0.0)

	def test_business_unit_rates(self):
		"""The guidelines' own example rates for business unit B."""
		self._set_solutions(
			[
				{
					"insurance": "LAA",
					"solution_code": "B",
					"rate_employer_male": 0.34,
					"rate_employee_male": 1.701,
				}
			]
		)
		self._employee(ch_laa_code="B1")
		slip = self._run(10000)
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 170.10)
		self.assertEqual(self._amount(slip, "LAA Professional Employer"), 34.00)

	def test_ijm_rates_by_sex(self):
		self._set_solutions(
			[
				{
					"insurance": "IJM",
					"solution_code": "A1",
					"rate_employee_male": 0.5,
					"rate_employer_male": 0.5,
					"rate_employee_female": 0.9,
					"rate_employer_female": 0.9,
				}
			]
		)
		self._employee(ch_ijm_code="A1", gender=self.female)
		self.assertEqual(self._amount(self._run(6000), "IJM/KTG Employee"), 54.00)  # 6000 x 0.9 %

	def test_laac_above_the_laa_cap(self):
		"""A LAAC solution covering the salary between CHF 148'200 and 300'000 a year."""
		self._set_solutions(
			[
				{
					"insurance": "LAAC",
					"solution_code": "A2",
					"wage_from": 148200,
					"wage_to": 300000,
					"rate_employee_male": 1.0,
					"rate_employer_male": 1.0,
				}
			]
		)
		self._employee(ch_laac_code="A2")
		# The bracket starts at 12'350 a month: 20'000 - 12'350 = 7'650 insured, at 1 %.
		self.assertEqual(self._amount(self._run(20000), "LAAC Employee"), 76.50)

	def _printed(self, slip):
		data = get_salary_slip_print_data(slip)
		return data, {row["name"]: row for row in data["deductions_ee"] + data["deductions_er"]}

	def test_the_payslip_prints_the_capped_laa_base(self):
		"""The amount is computed on 12'350; the payslip used to print 20'000 next to it."""
		data, rows = self._printed(self._run(20000))
		self.assertEqual(rows["LAA Non-Professional Employee"]["determinant"], 12350.0)
		self.assertEqual(data["insurance_bases"]["laa"], 12350.0)

	def test_the_payslip_prints_the_business_unit_rate(self):
		"""Not the configuration's flat rate: the rate the amount was computed with."""
		self._set_solutions(
			[
				{
					"insurance": "LAA",
					"solution_code": "B",
					"rate_employer_male": 0.34,
					"rate_employee_male": 1.701,
				}
			]
		)
		self._employee(ch_laa_code="B1")
		_data, rows = self._printed(self._run(10000))
		self.assertEqual(rows["LAA Non-Professional Employee"]["rate"], "1.701")
		self.assertEqual(rows["LAA Non-Professional Employee"]["determinant"], 10000.0)

	def test_no_single_rate_is_printed_for_two_brackets(self):
		self._set_solutions(
			[
				{
					"insurance": "LAAC",
					"solution_code": "A1",
					"wage_to": 148200,
					"rate_employee_male": 0.5,
					"rate_employer_male": 0.5,
				},
				{
					"insurance": "LAAC",
					"solution_code": "A1",
					"wage_from": 148200,
					"wage_to": 300000,
					"rate_employee_male": 1.0,
					"rate_employer_male": 1.0,
				},
			]
		)
		self._employee(ch_laac_code="A1")
		slip = self._run(20000)
		# 12'350 x 0.5 % + 7'650 x 1 % = 61.75 + 76.50
		self.assertEqual(self._amount(slip, "LAAC Employee"), 138.25)
		_data, rows = self._printed(slip)
		self.assertEqual(rows["LAAC Employee"]["rate"], "")
		self.assertEqual(rows["LAAC Employee"]["determinant"], 20000.0)

	def test_an_unconfigured_code_stops_the_slip(self):
		"""A guessed rate would produce a payslip that is accepted and wrong."""
		self._employee(ch_ijm_code="Z9")
		with self.assertRaises(frappe.ValidationError):
			self._run(6000)


# //// Neoffice — tests of an added file (no upstream equivalent).
class TestFiveCentimesAndWhatThePayslipStates(SwissPayrollHookCase):
	"""Every amount computed rounds to 5 centimes (Swissdec guidelines 4.1.1), the slip records
	the base and rate each contribution was computed with, and the net it announces is the net
	paid."""

	SALARY = 5001.10  # no contribution of it falls on a 5-centime step by itself

	def _slip(self):
		slip = self._make_slip([(MONTHLY_COMPONENT, self.SALARY)])
		update_swiss_social_contributions(slip, "validate")
		return slip

	def test_contributions_round_to_5_centimes(self):
		slip = self._slip()
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 265.05)  # 265.0583
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 55.00)  # 55.0121
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 50.00)  # 50.011
		self.assertEqual(self._amount(slip, "IJM/KTG Employee"), 35.00)  # 35.0077

	def test_the_bases_used_are_recorded_on_the_slip(self):
		bases = json.loads(self._slip().ch_contribution_bases)
		self.assertEqual(bases["AVS/AI/APG Employee"], {"base": self.SALARY, "rate": AVS_RATE_EE})
		# 55.00 / 1.1 % reads back as 5'000.00: the recorded base is the one computed with.
		self.assertEqual(bases["AC/ALV Employee"]["base"], self.SALARY)
		self.assertGreater(bases["LPP/BVG Employee"]["base"], 0)  # the coordinated salary

	def test_the_payslip_prints_the_recorded_base(self):
		data = get_salary_slip_print_data(self._slip())
		rows = {row["name"]: row for row in data["deductions_ee"] + data["deductions_er"]}
		self.assertEqual(rows["AC/ALV Employee"]["determinant"], self.SALARY)

	def test_the_net_announced_is_the_net_paid(self):
		"""Upstream rounded rounded_total to the whole franc and wrote it out in words."""
		frappe.db.set_single_value("Payroll Settings", "disable_rounded_total", 0)
		slip = self._slip()
		self.assertNotEqual(flt(slip.net_pay, 2), round(flt(slip.net_pay)), "the case needs centimes")
		self.assertEqual(flt(slip.rounded_total, 2), flt(slip.net_pay, 2))
		self.assertEqual(slip.total_in_words, money_in_words(slip.net_pay, "CHF"))
		self.assertEqual(get_salary_slip_print_data(slip)["totals"]["rounded"], 0)  # no second line

	def test_a_prorated_salary_rounds_to_5_centimes(self):
		slip = self._make_slip([(MONTHLY_COMPONENT, 5000)], payment_days=17, total_working_days=30)
		slip.salary_structure = "_Test CH structure (never saved)"
		row = slip.earnings[0]
		self.assertEqual(slip.get_amount_based_on_payment_days(row)[0], 2833.35)  # 2'833.333...
		# Outside Switzerland upstream is untouched.
		slip._rounds_to_5_centimes = lambda: False
		self.assertEqual(slip.get_amount_based_on_payment_days(row)[0], 2833.33)


def _catalogue_component(name, code):
	"""A component made from our catalogue entry, as api.create_component_from_wage_type makes it."""
	from hrms.regional.switzerland.wage_type_data import get_swiss_wage_types

	wt = {w["code"]: w for w in get_swiss_wage_types()}[code]
	_ensure_component(name, wt["type"])
	frappe.db.set_value(
		"Salary Component",
		name,
		{
			"type": wt["type"],
			"ch_wage_type_code": code,
			**{
				f"ch_subject_to_{k}": wt[f"subject_to_{k}"] for k in ("avs", "ac", "laa", "ijm", "lpp", "imp")
			},
			"ch_negative_wage_type": wt["is_negative"],
			"ch_bases_only": wt["bases_only"],
			"do_not_include_in_total": wt.get("do_not_include_in_total", 0),
		},
		update_modified=False,
	)
	return name


# //// Neoffice — the worked examples of the Swissdec guidelines 6.0 (8.7.2) on a real slip.
class TestSwissdecWageTypesOnTheSlip(SwissPayrollHookCase):
	APG = "_Test CH 2000 APG"
	CORRECTION = "_Test CH 2050 Correction"
	TIPS = "_Test CH 1920 Tips"
	LOSS = "_Test CH 2065 Short-time Loss"
	UNEMPLOYMENT = "_Test CH 2070 Unemployment"
	WAITING = "_Test CH 2075 Waiting Day"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		for name, code in (
			(cls.APG, "2000"),
			(cls.CORRECTION, "2050"),
			(cls.TIPS, "1920"),
			(cls.LOSS, "2065"),
			(cls.UNEMPLOYMENT, "2070"),
			(cls.WAITING, "2075"),
		):
			_catalogue_component(name, code)

	def _slip(self, earnings):
		slip = self._make_slip(earnings)
		for row in slip.earnings:
			# What the framework copies from the component when it builds the row.
			row.do_not_include_in_total = frappe.db.get_value(
				"Salary Component", row.salary_component, "do_not_include_in_total"
			)
		update_swiss_social_contributions(slip, "validate")
		return slip

	def _earning(self, slip, component):
		return next(flt(r.amount, 2) for r in slip.earnings if r.salary_component == component)

	def test_apg_with_the_salary_continued(self):
		"""7'000 + APG 550 + correction 550: gross 7'000, AVS/AC on 7'000, LAA on 6'450 (8.7.2.1)."""
		slip = self._slip([(MONTHLY_COMPONENT, 7000), (self.APG, 550), (self.CORRECTION, 550)])
		self.assertEqual(self._earning(slip, self.CORRECTION), -550)  # entered positive
		self.assertEqual(flt(slip.gross_pay, 2), 7000)
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 371.00)  # 7'000 x 5.3 %
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 77.00)
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 64.50)  # 6'450 x 1 %
		self.assertEqual(self._amount(slip, "IJM/KTG Employee"), 49.00)  # 7'000 x 0.7 %

	def test_a_second_validate_keeps_the_correction_negative(self):
		slip = self._slip([(MONTHLY_COMPONENT, 7000), (self.APG, 550), (self.CORRECTION, 550)])
		update_swiss_social_contributions(slip, "validate")
		self.assertEqual(self._earning(slip, self.CORRECTION), -550)
		self.assertEqual(flt(slip.gross_pay, 2), 7000)
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 64.50)

	def test_tips_raise_the_bases_without_being_paid(self):
		"""800 of tips (1920) on 6'000: contributions on 6'800, 6'000 paid."""
		slip = self._slip([(MONTHLY_COMPONENT, 6000), (self.TIPS, 800)])
		self.assertEqual(flt(slip.gross_pay, 2), 6000)
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 360.40)  # 6'800 x 5.3 %
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 68.00)

	def test_short_time_work_without_the_salary_continued(self):
		"""Hourly 4'600 + loss 900 + 600 + 120: gross 5'320, AVS/AC, LAA and IJM on 5'500 (8.7.2.5)."""
		slip = self._slip(
			[(HOURLY_COMPONENT, 4600), (self.LOSS, 900), (self.UNEMPLOYMENT, 600), (self.WAITING, 120)]
		)
		self.assertEqual(flt(slip.gross_pay, 2), 5320)
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 291.50)  # 5'500 x 5.3 %
		self.assertEqual(self._amount(slip, "LAA Non-Professional Employee"), 55.00)
		self.assertEqual(self._amount(slip, "IJM/KTG Employee"), 38.50)


# //// Neoffice — the payslip laid out as the certified engine prints it (compared 2026-09-24).
class TestThePayslipPrintsTheSwissdecLayout(SwissPayrollHookCase):
	TRAVEL = "_Test CH 6000 Travel Expenses"
	ADVANCE = "_Test CH 6510 Advance"
	TIPS = "_Test CH 1920 Tips on the print"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_catalogue_component(cls.TRAVEL, "6000")
		_catalogue_component(cls.ADVANCE, "6510")
		_catalogue_component(cls.TIPS, "1920")
		# As the Swiss setup makes them: employer contributions are not taken from the net.
		for name in DEDUCTION_COMPONENTS:
			if name.endswith("Employer"):
				frappe.db.set_value(
					"Salary Component",
					name,
					{"is_employer_contribution": 1, "do_not_include_in_total": 1},
					update_modified=False,
				)

	def _slip(self, earnings, deductions=(), **kwargs):
		slip = self._make_slip(earnings, **kwargs)
		for component, amount in deductions:
			row = slip.append("deductions", {})
			row.salary_component = component
			row.abbr = frappe.db.get_value("Salary Component", component, "salary_component_abbr")
			row.depends_on_payment_days = 0
			row.default_amount = amount
			row.amount = amount
		for row in slip.earnings + slip.deductions:
			# What the framework copies from the component when it builds the row.
			row.do_not_include_in_total = frappe.db.get_value(
				"Salary Component", row.salary_component, "do_not_include_in_total"
			)
		update_swiss_social_contributions(slip, "validate")
		return slip

	def _adds_up(self, data):
		t = data["totals"]
		self.assertEqual(flt(t["gross"] - t["ee_deductions"] + t["expenses"], 2), t["net_salary"])

	def test_expenses_come_after_the_deductions_not_in_the_gross(self):
		slip = self._slip([(MONTHLY_COMPONENT, 6000), (self.TRAVEL, 250)])
		data = get_salary_slip_print_data(slip)
		self.assertEqual([row["name"] for row in data["expenses"]], [self.TRAVEL])
		self.assertNotIn(self.TRAVEL, [row["name"] for row in data["earnings"]])
		self.assertEqual(data["totals"]["gross"], 6000)
		self.assertEqual(data["totals"]["expenses"], 250)
		self.assertEqual(data["totals"]["net"], flt(slip.net_pay, 2))
		self.assertEqual(data["totals"]["net_salary"], data["totals"]["net"])
		self._adds_up(data)

	def test_an_advance_comes_off_the_net_salary(self):
		slip = self._slip([(MONTHLY_COMPONENT, 6000)], deductions=[(self.ADVANCE, 500)])
		data = get_salary_slip_print_data(slip)
		self.assertEqual([row["name"] for row in data["after_net"]], [self.ADVANCE])
		self.assertNotIn(self.ADVANCE, [row["name"] for row in data["deductions_ee"]])
		self.assertEqual(data["totals"]["net"], flt(slip.net_pay, 2))
		self.assertEqual(data["totals"]["net_salary"], flt(slip.net_pay + 500, 2))
		self._adds_up(data)

	def test_a_row_not_paid_is_not_summed_in_the_gross(self):
		"""1920 tips raise the bases, nobody pays them: printed as a base, outside the CHF column."""
		data = get_salary_slip_print_data(self._slip([(MONTHLY_COMPONENT, 6000), (self.TIPS, 800)]))
		tips = next(row for row in data["earnings"] if row["name"] == self.TIPS)
		self.assertFalse(tips["paid"])
		self.assertEqual(data["totals"]["gross"], 6000)
		self.assertEqual(data["insurance_bases"]["avs"], 6800)
		self._adds_up(data)

	def test_the_source_tax_tariff_the_slip_was_settled_with(self):
		slip = self._slip([(MONTHLY_COMPONENT, 6000)])
		slip.ch_qst_tariff_code = "A0N"
		slip.ch_qst_canton = "ZH"
		self.assertEqual(get_salary_slip_print_data(slip)["source_tax"], {"canton": "ZH", "tariff": "A0N"})
		slip.ch_qst_tariff_code = ""
		self.assertIsNone(get_salary_slip_print_data(slip)["source_tax"])

	def test_paid_days_show_for_a_partial_month_only(self):
		full = get_salary_slip_print_data(self._slip([(MONTHLY_COMPONENT, 6000)], total_working_days=31))
		self.assertEqual(full["employment"]["pay_days"], "")
		partial = self._slip([(MONTHLY_COMPONENT, 6000)], payment_days=16, total_working_days=31)
		self.assertEqual(get_salary_slip_print_data(partial)["employment"]["pay_days"], "16 / 31")

	def test_the_account_is_masked_and_named_iban(self):
		from hrms.regional.switzerland.utils import _mask_account

		self.assertEqual(_mask_account("CH56 0483 5012 3456 7800 9"), "CH56 •••• •••• •••• •800 9")
		slip = self._slip([(MONTHLY_COMPONENT, 6000)])
		slip.bank_account_no = "CH5604835012345678009"
		bank = get_salary_slip_print_data(slip)["bank"]
		self.assertTrue(bank["is_iban"])
		self.assertEqual(bank["masked"], "CH56 •••• •••• •••• •800 9")

	def test_the_print_format_renders_the_layout(self):
		slip = self._slip([(MONTHLY_COMPONENT, 6000), (self.TRAVEL, 250)], deductions=[(self.ADVANCE, 500)])
		slip.ch_qst_tariff_code = "A0N"
		slip.ch_qst_canton = "ZH"
		path = frappe.get_app_path(
			"hrms", "payroll", "print_format", "salary_slip_swiss", "salary_slip_swiss.html"
		)
		with open(path) as template:
			html = frappe.render_template(template.read(), {"doc": slip})
		self.assertIn("Expense reimbursements", html)
		self.assertIn("Net to Pay", html)
		self.assertIn("ZH · A0N", html)
		self.assertNotIn("Work days", html)
		if slip.total_in_words:
			self.assertNotIn(slip.total_in_words, html)
		# A letter for a window envelope: the recipient in the right-hand window (SN 010 130),
		# "personal" above it, fold marks at the thirds of the sheet, and no filled background.
		self.assertIn('class="ss-window"', html)
		self.assertIn("left: 118mm", html)
		self.assertIn("Personal and confidential", html)
		self.assertEqual(html.count('class="ss-fold"'), 2)
		self.assertNotIn(
			"background:", html.split("<style>")[1].split("</style>")[0].replace("background: none", "")
		)


def _male_gender():
	from hrms.regional.switzerland.insurance_solutions import normalize_sex

	for name in frappe.get_all("Gender", pluck="name"):
		if normalize_sex(name) == "male":
			return name
	return frappe.get_doc({"doctype": "Gender", "gender": "Male"}).insert(ignore_permissions=True).name


# //// Neoffice — the ages follow the calendar year and the AVS 21 reference age (2026-09-23).
class TestAgesOnTheSlip(SwissPayrollHookCase):
	def _employee_born(self, date_of_birth, avs_status="", **extra):
		values = {
			"date_of_birth": date_of_birth,
			"gender": _male_gender(),
			"ch_avs_status": avs_status,
			**extra,
		}
		before = frappe.db.get_value("Employee", self.employee, list(values), as_dict=True)
		frappe.db.set_value("Employee", self.employee, values, update_modified=False)
		self.addCleanup(frappe.db.set_value, "Employee", self.employee, dict(before), update_modified=False)

	def _slip(self):
		slip = self._make_slip([(MONTHLY_COMPONENT, 6000)])
		update_swiss_social_contributions(slip, "validate")
		return slip

	def test_an_apprentice_born_in_november_pays_avs_from_january(self):
		"""17 to the day in March, but liable since 1 January of the year he turns 18."""
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 18}-11-15")
		slip = self._slip()
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 318.00)  # was 0
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 66.00)

	def test_a_man_past_the_reference_age_is_a_pensioner_without_declaring_it(self):
		"""Guidelines 8.1.1: the birth date and the sex decide — AVS above 1'400, no AC."""
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 66}-01-15")
		slip = self._slip()
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 243.80)  # (6'000 - 1'400) x 5.3 %
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 0)

	def test_a_declared_waiver_keeps_the_full_avs(self):
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 66}-01-15", avs_status="retired_waive_exemption")
		slip = self._slip()
		self.assertEqual(self._amount(slip, "AVS/AI/APG Employee"), 318.00)
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 0)

	def test_the_lpp_credit_follows_the_calendar_year(self):
		"""LPP age 35 from January: 10 % of 45'540, half of it a month — not 7 % until the birthday."""
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 35}-11-20")
		slip = self._slip()
		self.assertEqual(self._amount(slip, "LPP/BVG Employee"), 189.75)  # 4'554 / 2 / 12

	def test_no_lpp_credit_once_past_the_reference_age(self):
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 66}-01-15")
		slip = self._slip()
		self.assertFalse(self._amount(slip, "LPP/BVG Employee"))

	def test_lpp_continued_after_the_reference_age(self):
		"""LPP art. 33b: the employee who keeps working may stay insured, at the last bracket."""
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 66}-01-15", ch_lpp_after_reference_age=1)
		slip = self._slip()
		self.assertEqual(self._amount(slip, "LPP/BVG Employee"), 341.55)  # 18 % of 45'540 / 2 / 12
		# AVS and AC stay those of a pensioner: the continuation is the fund's, not the AVS's.
		self.assertEqual(self._amount(slip, "AC/ALV Employee"), 0)

	def test_lpp_continuation_ends_at_70(self):
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 71}-01-15", ch_lpp_after_reference_age=1)
		slip = self._slip()
		self.assertFalse(self._amount(slip, "LPP/BVG Employee"))

	def test_lpp_maintained_salary_from_58(self):
		"""LPP art. 33a: insured on 120'000 after a cut to 72'000, the difference on the employee."""
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 60}-01-15", ch_lpp_maintained_salary=120000)
		slip = self._slip()
		self.assertEqual(self._amount(slip, "LPP/BVG Employee"), 622.35)
		self.assertEqual(self._amount(slip, "LPP/BVG Employer"), 341.55)

	def test_no_maintained_salary_before_58(self):
		year = getdate(nowdate()).year
		self._employee_born(f"{year - 50}-01-15", ch_lpp_maintained_salary=120000)
		slip = self._slip()
		self.assertEqual(self._amount(slip, "LPP/BVG Employee"), 284.65)  # 15 % of 45'540 / 2 / 12


# //// Neoffice — the compensation fund's administrative fees (2026-09-23).
class TestAvsAdministrativeFees(SwissPayrollHookCase):
	FEES = "AVS Administrative Fees Employer"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_ensure_component(cls.FEES, "Deduction")
		frappe.db.set_value(
			"Salary Component",
			cls.FEES,
			{"is_employer_contribution": 1, "do_not_include_in_total": 1, "depends_on_payment_days": 0},
			update_modified=False,
		)

	def _with_rate(self, rate):
		frappe.db.set_value("Swiss Social Insurance Config", self.config, "avs_admin_fee_rate", rate)
		self.addCleanup(
			frappe.db.set_value, "Swiss Social Insurance Config", self.config, "avs_admin_fee_rate", 0
		)

	def test_a_share_of_the_avs_contributions(self):
		"""1.2 % of 318 + 318: 7.632, rounded to 7.65 — the certified engine's figure."""
		self._with_rate(1.2)
		slip = self._make_slip([(MONTHLY_COMPONENT, 6000)])
		update_swiss_social_contributions(slip, "validate")
		self.assertEqual(self._amount(slip, self.FEES), 7.65)
		recorded = json.loads(slip.ch_contribution_bases)[self.FEES]
		self.assertEqual(recorded, {"base": 636.00, "rate": 1.2})

	def test_an_employer_cost_never_taken_from_the_net(self):
		self._with_rate(1.2)
		with_fees = self._make_slip([(MONTHLY_COMPONENT, 6000)])
		update_swiss_social_contributions(with_fees, "validate")
		frappe.db.set_value("Swiss Social Insurance Config", self.config, "avs_admin_fee_rate", 0)
		without = self._make_slip([(MONTHLY_COMPONENT, 6000)])
		update_swiss_social_contributions(without, "validate")
		self.assertEqual(flt(with_fees.net_pay, 2), flt(without.net_pay, 2))

	def test_no_rate_no_fees(self):
		slip = self._make_slip([(MONTHLY_COMPONENT, 6000)])
		update_swiss_social_contributions(slip, "validate")
		self.assertIsNone(self._amount(slip, self.FEES))
