# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Tests for Swissdec ELM 5.0 XML generation, validation, and data aggregation.

All tests use pure functions with mock data — no Frappe DB dependency.
"""

import unittest
from xml.etree.ElementTree import fromstring

from hrms.regional.switzerland.swissdec_validation import (
	ValidationResult,
	_validate_company,
	_validate_employee,
	_validate_salary_data,
	get_validation_summary,
	validate_avs_number,
	validate_declaration,
	validate_uid_bfs,
)
from hrms.regional.switzerland.swissdec_xml import (
	SWISSDEC_NS,
	_build_activity,
	_build_avs_salary,
	_build_ac_salary,
	_build_company_element,
	_build_fak_salary,
	_build_ijm_salary,
	_build_laa_salary,
	_build_lpp_salary,
	_build_particulars,
	_build_qst_salary,
	_format_date,
	_prettify_xml,
	generate_salary_declaration,
)


# --- Test Helpers ---


def _make_employee(**kwargs):
	"""Create a mock employee dict with sensible defaults."""
	defaults = {
		"name": "HR-EMP-00001",
		"employee": "HR-EMP-00001",
		"employee_name": "Max Muster",
		"first_name": "Max",
		"last_name": "Muster",
		"date_of_birth": "1985-06-15",
		"gender": "Male",
		"ch_avs_number": "756.1234.5678.97",
		"ch_fiscal_canton": "ZH",
		"ch_nationality": "Switzerland",
		"ch_permit_type": "Swiss Citizen",
		"ch_work_percentage": 100,
		"ch_entry_date": "2020-01-01",
		"ch_qst_subject": 0,
		"ch_is_cross_border": 0,
		"marital_status": "Single",
	}
	defaults.update(kwargs)
	return defaults


def _make_salary_data(**kwargs):
	"""Create a mock annual salary summary dict."""
	defaults = {
		"total_gross": 96000.0,
		"total_net": 80000.0,
		"months_worked": 12,
		"component_totals": {
			"Basic": 96000.0,
			"AVS/AI/APG Employee": 5088.0,
			"AVS/AI/APG Employer": 5088.0,
			"AC/ALV Employee": 1056.0,
			"AC/ALV Employer": 1056.0,
			"LPP/BVG Employee": 1593.96,
			"LPP/BVG Employer": 1593.96,
		},
		"avs_salary": 96000.0,
		"ac_salary": 96000.0,
		"laa_salary": 96000.0,
		"lpp_coordinated": 45540.0,
		"source_tax_total": 0,
		"employee_age": 40,
		"avs_employee": 5088.0,
		"avs_employer": 5088.0,
		"ac_employee": 1056.0,
		"ac_employer": 1056.0,
		"ac_solidarity_employee": 0,
		"ac_solidarity_employer": 0,
		"lpp_employee": 1593.96,
		"lpp_employer": 1593.96,
		"laa_professional": 480.0,
		"laa_nonprofessional": 960.0,
		"ijm_employee": 384.0,
		"ijm_employer": 384.0,
		"fak_employer": 1056.0,
		"period_start": "2025-01-01",
		"period_end": "2025-12-31",
	}
	defaults.update(kwargs)
	return defaults


def _make_company(**kwargs):
	"""Create a mock company data dict."""
	defaults = {
		"company_name": "Test AG",
		"abbr": "TAG",
		"ch_uid_bfs": "CHE-123.456.789",
		"ch_contact_person": "Hans Müller",
		"ch_contact_phone": "+41 44 123 45 67",
		"ch_contact_email": "hans@test.ch",
		"address_line1": "Bahnhofstrasse 1",
		"pincode": "8001",
		"city": "Zürich",
	}
	defaults.update(kwargs)
	return defaults


def _make_config(**kwargs):
	"""Create a mock config dict."""
	defaults = {
		"ac_annual_ceiling": 148200,
		"laa_insurable_salary_cap": 148200,
		"avs_rate_employee": 5.3,
		"avs_rate_employer": 5.3,
	}
	defaults.update(kwargs)
	return defaults


# === AVS NUMBER VALIDATION ===


class TestAvsNumberValidation(unittest.TestCase):
	"""Tests for AVS number format and check digit validation."""

	def test_valid_avs_number(self):
		"""Standard valid AVS number passes."""
		self.assertTrue(validate_avs_number("756.1234.5678.97"))

	def test_valid_avs_number_no_dots(self):
		"""AVS number without dots passes."""
		self.assertTrue(validate_avs_number("7561234567897"))

	def test_invalid_avs_wrong_prefix(self):
		"""AVS number not starting with 756 fails."""
		self.assertFalse(validate_avs_number("757.1234.5678.97"))

	def test_invalid_avs_too_short(self):
		"""AVS number with too few digits fails."""
		self.assertFalse(validate_avs_number("756.1234.5678"))

	def test_invalid_avs_too_long(self):
		"""AVS number with too many digits fails."""
		self.assertFalse(validate_avs_number("756.1234.5678.970"))

	def test_invalid_avs_bad_check_digit(self):
		"""AVS number with wrong check digit fails."""
		self.assertFalse(validate_avs_number("756.1234.5678.98"))

	def test_empty_avs(self):
		"""Empty AVS number fails."""
		self.assertFalse(validate_avs_number(""))

	def test_none_avs(self):
		"""None AVS number fails."""
		self.assertFalse(validate_avs_number(None))

	def test_avs_with_spaces(self):
		"""AVS number with spaces passes (spaces stripped)."""
		self.assertTrue(validate_avs_number("756 1234 5678 97"))

	def test_non_numeric(self):
		"""AVS number with letters fails."""
		self.assertFalse(validate_avs_number("756.ABCD.5678.97"))


class TestUidBfsValidation(unittest.TestCase):
	"""Tests for UID-BFS format validation."""

	def test_valid_uid(self):
		"""Standard CHE-XXX.XXX.XXX format passes."""
		self.assertTrue(validate_uid_bfs("CHE-123.456.789"))

	def test_valid_uid_no_separators(self):
		"""UID without separators passes."""
		self.assertTrue(validate_uid_bfs("CHE123456789"))

	def test_invalid_uid_wrong_prefix(self):
		"""UID not starting with CHE fails."""
		self.assertFalse(validate_uid_bfs("CHF-123.456.789"))

	def test_invalid_uid_too_few_digits(self):
		"""UID with too few digits fails."""
		self.assertFalse(validate_uid_bfs("CHE-123.456"))

	def test_empty_uid(self):
		"""Empty UID fails."""
		self.assertFalse(validate_uid_bfs(""))

	def test_none_uid(self):
		"""None UID fails."""
		self.assertFalse(validate_uid_bfs(None))


# === EMPLOYEE VALIDATION ===


class TestEmployeeValidation(unittest.TestCase):
	"""Tests for employee data validation."""

	def test_valid_employee_passes(self):
		"""Complete employee with all required fields passes."""
		emp = _make_employee()
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertEqual(len(errors), 0)

	def test_missing_avs_number(self):
		"""Missing AVS number is flagged as error."""
		emp = _make_employee(ch_avs_number="")
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("AVS number" in r.message for r in errors))

	def test_invalid_avs_number_format(self):
		"""Invalid AVS format is flagged as error."""
		emp = _make_employee(ch_avs_number="756.0000.0000.00")
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("Invalid AVS" in r.message for r in errors))

	def test_missing_date_of_birth(self):
		"""Missing DOB is flagged as error."""
		emp = _make_employee(date_of_birth="")
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("Date of birth" in r.message for r in errors))

	def test_missing_canton(self):
		"""Missing fiscal canton is flagged as error."""
		emp = _make_employee(ch_fiscal_canton="")
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("canton" in r.message.lower() for r in errors))

	def test_invalid_canton(self):
		"""Invalid canton code is flagged as error."""
		emp = _make_employee(ch_fiscal_canton="XX")
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("Invalid canton" in r.message for r in errors))

	def test_missing_nationality_warning(self):
		"""Missing nationality is flagged as warning."""
		emp = _make_employee(ch_nationality="")
		results = _validate_employee(emp)
		warnings = [r for r in results if r.level == "warning"]
		self.assertTrue(any("Nationality" in r.message for r in warnings))

	def test_qst_subject_without_tariff(self):
		"""QST-subject employee without tariff code is flagged."""
		emp = _make_employee(ch_qst_subject=1, ch_qst_tariff_letter="", ch_qst_tariff_code="")
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("tariff" in r.message.lower() for r in errors))

	def test_cross_border_without_country(self):
		"""Cross-border worker without residence country is flagged."""
		emp = _make_employee(ch_is_cross_border=1, ch_residence_country="")
		results = _validate_employee(emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("Residence country" in r.message for r in errors))

	def test_foreign_employee_without_permit_warning(self):
		"""Non-Swiss employee without permit type gets warning."""
		emp = _make_employee(ch_nationality="Germany", ch_permit_type="")
		results = _validate_employee(emp)
		warnings = [r for r in results if r.level == "warning"]
		self.assertTrue(any("Permit type" in r.message for r in warnings))


# === SALARY DATA VALIDATION ===


class TestSalaryDataValidation(unittest.TestCase):
	"""Tests for salary data consistency validation."""

	def test_valid_salary_data(self):
		"""Valid salary data passes."""
		salary = _make_salary_data()
		emp = _make_employee()
		results = _validate_salary_data(salary, emp)
		errors = [r for r in results if r.level == "error"]
		self.assertEqual(len(errors), 0)

	def test_no_salary_slips(self):
		"""No salary slips flagged as error."""
		salary = {"months_worked": 0}
		emp = _make_employee()
		results = _validate_salary_data(salary, emp)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("No salary slips" in r.message for r in errors))

	def test_empty_salary_data(self):
		"""Empty salary data flagged as error."""
		results = _validate_salary_data({}, _make_employee())
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(len(errors) > 0)

	def test_zero_gross_warning(self):
		"""Zero gross salary gets warning."""
		salary = _make_salary_data(total_gross=0, months_worked=12)
		results = _validate_salary_data(salary, _make_employee())
		warnings = [r for r in results if r.level == "warning"]
		self.assertTrue(any("gross salary" in r.message.lower() for r in warnings))

	def test_no_avs_contributions_warning(self):
		"""Missing AVS contributions with positive gross gets warning."""
		salary = _make_salary_data(avs_employee=0)
		results = _validate_salary_data(salary, _make_employee())
		warnings = [r for r in results if r.level == "warning"]
		self.assertTrue(any("AVS" in r.message for r in warnings))

	def test_qst_subject_no_tax_warning(self):
		"""QST-subject employee with no tax withheld gets warning."""
		salary = _make_salary_data(source_tax_total=0)
		emp = _make_employee(ch_qst_subject=1)
		results = _validate_salary_data(salary, emp)
		warnings = [r for r in results if r.level == "warning"]
		self.assertTrue(any("source tax" in r.message.lower() for r in warnings))


# === COMPANY VALIDATION ===


class TestCompanyValidation(unittest.TestCase):
	"""Tests for company data validation."""

	def test_valid_company(self):
		"""Complete company data passes."""
		company = _make_company()
		results = _validate_company(company)
		errors = [r for r in results if r.level == "error"]
		self.assertEqual(len(errors), 0)

	def test_missing_uid_bfs_warning(self):
		"""Missing UID-BFS is flagged as warning."""
		company = _make_company(ch_uid_bfs="")
		results = _validate_company(company)
		warnings = [r for r in results if r.level == "warning"]
		self.assertTrue(any("UID-BFS" in r.message for r in warnings))

	def test_invalid_uid_bfs(self):
		"""Invalid UID-BFS format is flagged as error."""
		company = _make_company(ch_uid_bfs="INVALID")
		results = _validate_company(company)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("Invalid UID-BFS" in r.message for r in errors))

	def test_missing_company_name(self):
		"""Missing company name is flagged as error."""
		company = _make_company(company_name="")
		results = _validate_company(company)
		errors = [r for r in results if r.level == "error"]
		self.assertTrue(any("Company name" in r.message for r in errors))


# === VALIDATION SUMMARY ===


class TestValidationSummary(unittest.TestCase):
	"""Tests for validation summary generation."""

	def test_no_issues(self):
		"""No results produces clean summary."""
		summary = get_validation_summary([])
		self.assertFalse(summary["has_errors"])
		self.assertEqual(summary["error_count"], 0)
		self.assertEqual(summary["warning_count"], 0)

	def test_errors_flagged(self):
		"""Errors set has_errors=True."""
		results = [ValidationResult(level="error", message="Test error")]
		summary = get_validation_summary(results)
		self.assertTrue(summary["has_errors"])
		self.assertEqual(summary["error_count"], 1)

	def test_warnings_only(self):
		"""Warnings only: has_errors=False."""
		results = [ValidationResult(level="warning", message="Test warning")]
		summary = get_validation_summary(results)
		self.assertFalse(summary["has_errors"])
		self.assertEqual(summary["warning_count"], 1)

	def test_mixed_results(self):
		"""Mixed errors and warnings counted correctly."""
		results = [
			ValidationResult(level="error", employee="EMP-1", message="Error 1"),
			ValidationResult(level="warning", employee="EMP-1", message="Warning 1"),
			ValidationResult(level="error", employee="EMP-2", message="Error 2"),
		]
		summary = get_validation_summary(results)
		self.assertTrue(summary["has_errors"])
		self.assertEqual(summary["error_count"], 2)
		self.assertEqual(summary["warning_count"], 1)


# === FULL VALIDATION ===


class TestFullValidation(unittest.TestCase):
	"""Integration tests for the full validate_declaration() function."""

	def test_valid_declaration(self):
		"""Complete valid declaration passes."""
		emp = _make_employee()
		salary = _make_salary_data()
		company = _make_company()

		results = validate_declaration(
			[{"employee_doc": emp, "salary_data": salary}],
			company,
		)
		errors = [r for r in results if r.level == "error"]
		self.assertEqual(len(errors), 0)

	def test_multiple_employees(self):
		"""Multiple employees validated independently."""
		emp1 = _make_employee(name="EMP-1", ch_avs_number="756.1234.5678.97")
		emp2 = _make_employee(name="EMP-2", ch_avs_number="")  # missing AVS

		salary1 = _make_salary_data()
		salary2 = _make_salary_data()

		results = validate_declaration(
			[
				{"employee_doc": emp1, "salary_data": salary1},
				{"employee_doc": emp2, "salary_data": salary2},
			],
			_make_company(),
		)

		# EMP-2 should have an AVS error
		emp2_errors = [r for r in results if r.employee == "EMP-2" and r.level == "error"]
		self.assertTrue(len(emp2_errors) > 0)

		# EMP-1 should have no errors
		emp1_errors = [r for r in results if r.employee == "EMP-1" and r.level == "error"]
		self.assertEqual(len(emp1_errors), 0)

	def test_company_errors_included(self):
		"""Company validation errors included in results."""
		results = validate_declaration(
			[{"employee_doc": _make_employee(), "salary_data": _make_salary_data()}],
			_make_company(company_name=""),
		)
		company_errors = [r for r in results if r.employee is None and r.level == "error"]
		self.assertTrue(len(company_errors) > 0)


# === XML GENERATION ===


class TestXmlGeneration(unittest.TestCase):
	"""Tests for ELM 5.0 XML generation."""

	# Namespace dict for ElementTree find/findall queries
	NS = {"sd": SWISSDEC_NS}

	def test_root_element_namespace(self):
		"""Root element has correct Swissdec namespace."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		# ElementTree includes namespace in tag
		self.assertEqual(root.tag, f"{{{SWISSDEC_NS}}}SalaryDeclaration")
		self.assertEqual(root.get("schemaVersion"), "5.0")

	def test_company_element_present(self):
		"""Company element contains name and UID."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		company = root.find("sd:Company", self.NS)
		self.assertIsNotNone(company)

		name = company.find("sd:Name", self.NS)
		self.assertIsNotNone(name)
		self.assertEqual(name.text, "Test AG")

		uid = company.find("sd:UID-BFS", self.NS)
		self.assertIsNotNone(uid)
		self.assertEqual(uid.text, "CHE123456789")

	def test_staff_person_element(self):
		"""Staff contains Person element with Particulars."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		staff = root.find("sd:Company/sd:Staff", self.NS)
		self.assertIsNotNone(staff)

		person = staff.find("sd:Person", self.NS)
		self.assertIsNotNone(person)

		particulars = person.find("sd:Particulars", self.NS)
		self.assertIsNotNone(particulars)

		firstname = particulars.find("sd:Firstname", self.NS)
		self.assertEqual(firstname.text, "Max")

		lastname = particulars.find("sd:Lastname", self.NS)
		self.assertEqual(lastname.text, "Muster")

	def test_avs_salary_element(self):
		"""AVS salary element contains correct amounts."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		avs = root.find("sd:Company/sd:Staff/sd:Person/sd:AHV-AVS-Salaries", self.NS)
		self.assertIsNotNone(avs)

		income = avs.find("sd:AHV-AVS-Income", self.NS)
		self.assertEqual(income.text, "96000.00")

		ee = avs.find("sd:AHV-AVS-EE", self.NS)
		self.assertEqual(ee.text, "5088.00")

		er = avs.find("sd:AHV-AVS-ER", self.NS)
		self.assertEqual(er.text, "5088.00")

	def test_ac_salary_element(self):
		"""AC salary element contains correct amounts."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		ac = root.find("sd:Company/sd:Staff/sd:Person/sd:ALV-AC-Salaries", self.NS)
		self.assertIsNotNone(ac)

		income = ac.find("sd:ALV-AC-Income", self.NS)
		self.assertEqual(income.text, "96000.00")

	def test_lpp_salary_element(self):
		"""LPP salary element contains coordinated salary."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		lpp = root.find("sd:Company/sd:Staff/sd:Person/sd:BVG-LPP-Salaries", self.NS)
		self.assertIsNotNone(lpp)

		coord = lpp.find("sd:BVG-LPP-CoordinatedSalary", self.NS)
		self.assertEqual(coord.text, "45540.00")

	def test_laa_salary_element(self):
		"""LAA salary element contains insured salary and contributions."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		laa = root.find("sd:Company/sd:Staff/sd:Person/sd:UVG-LAA-Salaries", self.NS)
		self.assertIsNotNone(laa)

		income = laa.find("sd:UVG-LAA-Income", self.NS)
		self.assertEqual(income.text, "96000.00")

	def test_ijm_salary_element(self):
		"""IJM salary element present with contributions."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		ijm = root.find("sd:Company/sd:Staff/sd:Person/sd:KTG-IJM-Salaries", self.NS)
		self.assertIsNotNone(ijm)

	def test_qst_salary_element_for_subject(self):
		"""QST salary element included only for QST-subject employees."""
		emp = _make_employee(
			ch_qst_subject=1,
			ch_qst_tariff_code="B2Y",
			ch_qst_taxation_canton="ZH",
		)
		salary = _make_salary_data(source_tax_total=4800.0)

		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[{"employee_doc": emp, "salary_data": salary}],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		qst = root.find("sd:Company/sd:Staff/sd:Person/sd:QST-Salaries", self.NS)
		self.assertIsNotNone(qst)

		canton = qst.find("sd:Canton", self.NS)
		self.assertEqual(canton.text, "ZH")

		tariff = qst.find("sd:TariffCode", self.NS)
		self.assertEqual(tariff.text, "B2Y")

		tax = qst.find("sd:QST-Tax", self.NS)
		self.assertEqual(tax.text, "4800.00")

	def test_qst_salary_not_included_for_non_subject(self):
		"""QST salary element NOT included for non-QST employees."""
		emp = _make_employee(ch_qst_subject=0)

		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[{"employee_doc": emp, "salary_data": _make_salary_data()}],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		qst = root.find("sd:Company/sd:Staff/sd:Person/sd:QST-Salaries", self.NS)
		self.assertIsNone(qst)

	def test_fak_salary_element(self):
		"""FAK salary element contains employer contribution."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		fak = root.find("sd:Company/sd:Staff/sd:Person/sd:FAK-CAF-Salaries", self.NS)
		self.assertIsNotNone(fak)

		er = fak.find("sd:FAK-CAF-ER", self.NS)
		self.assertEqual(er.text, "1056.00")

	def test_cross_border_data_in_qst(self):
		"""Cross-border data included in QST element."""
		emp = _make_employee(
			ch_qst_subject=1,
			ch_qst_tariff_code="G0N",
			ch_is_cross_border=1,
			ch_residence_country="DE",
		)

		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": emp, "salary_data": _make_salary_data(source_tax_total=3600.0)},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		cb = root.find("sd:Company/sd:Staff/sd:Person/sd:QST-Salaries/sd:CrossBorder", self.NS)
		self.assertIsNotNone(cb)

		country = cb.find("sd:ResidenceCountry", self.NS)
		self.assertEqual(country.text, "DE")

	def test_multiple_employees_xml(self):
		"""Multiple employees generate multiple Person elements."""
		emp1 = _make_employee(name="EMP-1", first_name="Max")
		emp2 = _make_employee(name="EMP-2", first_name="Anna", last_name="Müller")

		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": emp1, "salary_data": _make_salary_data()},
				{"employee_doc": emp2, "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		persons = root.findall("sd:Company/sd:Staff/sd:Person", self.NS)
		self.assertEqual(len(persons), 2)

	def test_empty_employees_produces_valid_xml(self):
		"""Empty employee list produces valid XML with empty Staff."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		staff = root.find("sd:Company/sd:Staff", self.NS)
		self.assertIsNotNone(staff)
		persons = staff.findall("sd:Person", self.NS)
		self.assertEqual(len(persons), 0)

	def test_employee_without_salary_skipped(self):
		"""Employee with months_worked=0 is skipped."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": {"months_worked": 0}},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		persons = root.findall("sd:Company/sd:Staff/sd:Person", self.NS)
		self.assertEqual(len(persons), 0)

	def test_xml_is_valid_utf8(self):
		"""Generated XML is valid UTF-8."""
		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
		)
		self.assertIsInstance(xml_bytes, bytes)
		xml_str = xml_bytes.decode("utf-8")
		self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', xml_str)

	def test_institution_selection(self):
		"""Only selected institutions are included."""
		institutions = {
			"include_avs": True,
			"include_ac": False,
			"include_lpp": False,
			"include_laa": False,
			"include_ijm": False,
			"include_qst": False,
			"include_fak": False,
			"include_ofs": False,
		}

		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[
				{"employee_doc": _make_employee(), "salary_data": _make_salary_data()},
			],
			config=_make_config(),
			fiscal_year="2025",
			institutions=institutions,
		)
		root = fromstring(xml_bytes)
		person = root.find("sd:Company/sd:Staff/sd:Person", self.NS)

		# AVS should be present
		self.assertIsNotNone(person.find("sd:AHV-AVS-Salaries", self.NS))
		# Others should not be present
		self.assertIsNone(person.find("sd:ALV-AC-Salaries", self.NS))
		self.assertIsNone(person.find("sd:BVG-LPP-Salaries", self.NS))
		self.assertIsNone(person.find("sd:UVG-LAA-Salaries", self.NS))

	def test_activity_element_details(self):
		"""Activity element contains work details."""
		emp = _make_employee(
			ch_fiscal_canton="BE",
			ch_permit_type="Permit B (Residence)",
			ch_work_percentage=80,
		)

		xml_bytes = generate_salary_declaration(
			company_data=_make_company(),
			employees_data=[{"employee_doc": emp, "salary_data": _make_salary_data()}],
			config=_make_config(),
			fiscal_year="2025",
		)
		root = fromstring(xml_bytes)
		activity = root.find("sd:Company/sd:Staff/sd:Person/sd:Activity", self.NS)
		self.assertIsNotNone(activity)

		canton = activity.find("sd:WorkplaceCanton", self.NS)
		self.assertEqual(canton.text, "BE")

		permit = activity.find("sd:CategoryOfResidencePermit", self.NS)
		self.assertEqual(permit.text, "03")  # Permit B

		rate = activity.find("sd:ActivityRate", self.NS)
		self.assertEqual(rate.text, "80.0")


# === DATE FORMATTING ===


class TestDateFormatting(unittest.TestCase):
	"""Tests for date formatting utility."""

	def test_date_string_formatting(self):
		"""String date formats correctly."""
		self.assertEqual(_format_date("2025-01-15"), "2025-01-15")

	def test_empty_date(self):
		"""Empty date returns empty string."""
		self.assertEqual(_format_date(""), "")
		self.assertEqual(_format_date(None), "")


if __name__ == "__main__":
	unittest.main()
