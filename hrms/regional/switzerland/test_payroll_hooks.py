#//// Neoffice — added file (no upstream equivalent): the Salary Slip validate hook that computes
#//// the Swiss contributions decides how much is withheld from a real payslip. Its defects are
#//// silent — a slip comes out looking normal with a contribution missing or halved — so each
#//// one is pinned here by the amount it must produce, not by the code path it takes.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, getdate, nowdate

#//// Neoffice — tests of an added file (no upstream equivalent).
from hrms.regional.switzerland.payroll_hooks import (
	_resolve_component_by_wage_type,
	update_swiss_social_contributions,
)

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
	if not frappe.db.has_column("Salary Component", "ch_subject_to_avs"):
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


#//// Neoffice — tests of an added file (no upstream equivalent).
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
				"tariff_type": "Salaires",
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
