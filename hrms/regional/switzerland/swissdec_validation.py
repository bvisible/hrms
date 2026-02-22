# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Swissdec ELM pre-export validation engine.

Validates employee data, company data, and salary data completeness
before generating the ELM XML export.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

from frappe.utils import flt

from hrms.regional.switzerland.constants import SWISS_CANTONS


@dataclass
class ValidationResult:
	"""Single validation finding."""

	level: str  # "error", "warning", "info"
	employee: Optional[str] = None
	field_name: Optional[str] = None
	message: str = ""


def validate_declaration(employees_data, company_data, config=None):
	"""Run all validation checks on a declaration.

	Args:
		employees_data: list of dicts, each with employee_doc and salary_data.
		company_data: dict with company document fields.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		list of ValidationResult.
	"""
	results = []

	# Validate company
	results.extend(_validate_company(company_data))

	# Validate each employee
	for emp_data in employees_data:
		emp_doc = emp_data.get("employee_doc", {})
		salary_data = emp_data.get("salary_data", {})
		results.extend(_validate_employee(emp_doc))
		results.extend(_validate_salary_data(salary_data, emp_doc, config))

	return results


def _validate_company(company_data):
	"""Check company has required Swissdec fields.

	Args:
		company_data: dict with company fields.

	Returns:
		list of ValidationResult.
	"""
	results = []

	uid_bfs = company_data.get("ch_uid_bfs") or ""
	if not uid_bfs:
		results.append(
			ValidationResult(
				level="warning",
				field_name="ch_uid_bfs",
				message="Company UID-BFS number is missing. Required for Swissdec declarations.",
			)
		)
	elif not validate_uid_bfs(uid_bfs):
		results.append(
			ValidationResult(
				level="error",
				field_name="ch_uid_bfs",
				message=f"Invalid UID-BFS format: {uid_bfs}. Expected: CHE-XXX.XXX.XXX",
			)
		)

	if not company_data.get("company_name"):
		results.append(
			ValidationResult(
				level="error",
				field_name="company_name",
				message="Company name is required.",
			)
		)

	return results


def _validate_employee(employee_doc):
	"""Check employee has required ELM fields.

	Args:
		employee_doc: dict-like with employee fields.

	Returns:
		list of ValidationResult.
	"""
	results = []
	emp_name = employee_doc.get("name") or employee_doc.get("employee") or "Unknown"

	# AVS number
	avs = employee_doc.get("ch_avs_number") or ""
	if not avs:
		results.append(
			ValidationResult(
				level="error",
				employee=emp_name,
				field_name="ch_avs_number",
				message="AVS number is missing.",
			)
		)
	elif not validate_avs_number(avs):
		results.append(
			ValidationResult(
				level="error",
				employee=emp_name,
				field_name="ch_avs_number",
				message=f"Invalid AVS number format: {avs}",
			)
		)

	# Date of birth
	if not employee_doc.get("date_of_birth"):
		results.append(
			ValidationResult(
				level="error",
				employee=emp_name,
				field_name="date_of_birth",
				message="Date of birth is missing.",
			)
		)

	# Fiscal canton
	canton = employee_doc.get("ch_fiscal_canton") or ""
	if not canton:
		results.append(
			ValidationResult(
				level="error",
				employee=emp_name,
				field_name="ch_fiscal_canton",
				message="Fiscal canton is missing.",
			)
		)
	elif canton not in SWISS_CANTONS:
		results.append(
			ValidationResult(
				level="error",
				employee=emp_name,
				field_name="ch_fiscal_canton",
				message=f"Invalid canton: {canton}",
			)
		)

	# Nationality
	if not employee_doc.get("ch_nationality"):
		results.append(
			ValidationResult(
				level="warning",
				employee=emp_name,
				field_name="ch_nationality",
				message="Nationality is not set. Recommended for ELM.",
			)
		)

	# Permit type for non-Swiss
	nationality = employee_doc.get("ch_nationality") or ""
	if nationality and nationality != "Switzerland":
		if not employee_doc.get("ch_permit_type"):
			results.append(
				ValidationResult(
					level="warning",
					employee=emp_name,
					field_name="ch_permit_type",
					message="Permit type not set for non-Swiss employee.",
				)
			)

	# QST fields if subject to source tax
	if employee_doc.get("ch_qst_subject"):
		if not employee_doc.get("ch_qst_tariff_letter") and not employee_doc.get("ch_qst_tariff_code"):
			results.append(
				ValidationResult(
					level="error",
					employee=emp_name,
					field_name="ch_qst_tariff_code",
					message="Source tax tariff code is missing for QST-subject employee.",
				)
			)

	# Cross-border fields
	if employee_doc.get("ch_is_cross_border"):
		if not employee_doc.get("ch_residence_country"):
			results.append(
				ValidationResult(
					level="error",
					employee=emp_name,
					field_name="ch_residence_country",
					message="Residence country is missing for cross-border worker.",
				)
			)

	return results


def _validate_salary_data(salary_data, employee_doc, config=None):
	"""Check salary data consistency.

	Args:
		salary_data: dict from get_annual_salary_summary().
		employee_doc: dict-like with employee fields.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		list of ValidationResult.
	"""
	results = []
	emp_name = employee_doc.get("name") or employee_doc.get("employee") or "Unknown"

	if not salary_data or not salary_data.get("months_worked"):
		results.append(
			ValidationResult(
				level="error",
				employee=emp_name,
				message="No salary slips found for the declaration period.",
			)
		)
		return results

	gross = flt(salary_data.get("total_gross"))
	if gross <= 0:
		results.append(
			ValidationResult(
				level="warning",
				employee=emp_name,
				message="Total gross salary is zero or negative.",
			)
		)

	# Check AVS contributions are present
	avs_ee = flt(salary_data.get("avs_employee"))
	if gross > 0 and avs_ee == 0:
		results.append(
			ValidationResult(
				level="warning",
				employee=emp_name,
				field_name="avs_employee",
				message="No AVS employee contributions found despite positive gross salary.",
			)
		)

	# Check source tax if employee is QST-subject
	if employee_doc.get("ch_qst_subject"):
		qst = flt(salary_data.get("source_tax_total"))
		if qst == 0 and gross > 0:
			results.append(
				ValidationResult(
					level="warning",
					employee=emp_name,
					field_name="source_tax_total",
					message="No source tax withheld for QST-subject employee.",
				)
			)

	return results


def validate_avs_number(avs_number):
	"""Validate AVS number format and check digit.

	Swiss AVS/AHV numbers follow the format 756.XXXX.XXXX.XX
	where the last 2 digits include a check digit (EAN-13 algorithm).

	Args:
		avs_number: String in format "756.XXXX.XXXX.XX".

	Returns:
		True if valid, False otherwise.
	"""
	if not avs_number:
		return False

	# Remove dots and spaces
	cleaned = avs_number.replace(".", "").replace(" ", "")

	# Must be exactly 13 digits
	if not re.match(r"^\d{13}$", cleaned):
		return False

	# Must start with 756
	if not cleaned.startswith("756"):
		return False

	# EAN-13 check digit validation
	digits = [int(d) for d in cleaned]
	total = 0
	for i in range(12):
		weight = 1 if i % 2 == 0 else 3
		total += digits[i] * weight

	check_digit = (10 - (total % 10)) % 10

	return digits[12] == check_digit


def validate_uid_bfs(uid):
	"""Validate UID-BFS format (CHE-XXX.XXX.XXX).

	Args:
		uid: UID string.

	Returns:
		True if valid format, False otherwise.
	"""
	if not uid:
		return False

	# Accept formats: CHE-XXX.XXX.XXX or CHEXXXXXXXXXXX
	cleaned = uid.replace("-", "").replace(".", "").replace(" ", "").upper()

	if not cleaned.startswith("CHE"):
		return False

	# CHE followed by 9 digits
	digits_part = cleaned[3:]
	return bool(re.match(r"^\d{9}$", digits_part))


def get_validation_summary(results):
	"""Summarize validation results.

	Args:
		results: list of ValidationResult.

	Returns:
		dict with error_count, warning_count, info_count, has_errors, text_summary.
	"""
	errors = [r for r in results if r.level == "error"]
	warnings = [r for r in results if r.level == "warning"]
	infos = [r for r in results if r.level == "info"]

	lines = []
	if errors:
		lines.append(f"ERRORS ({len(errors)}):")
		for r in errors:
			prefix = f"  [{r.employee}]" if r.employee else "  [Company]"
			lines.append(f"{prefix} {r.message}")

	if warnings:
		lines.append(f"\nWARNINGS ({len(warnings)}):")
		for r in warnings:
			prefix = f"  [{r.employee}]" if r.employee else "  [Company]"
			lines.append(f"{prefix} {r.message}")

	if not errors and not warnings:
		lines.append("All validations passed.")

	return {
		"error_count": len(errors),
		"warning_count": len(warnings),
		"info_count": len(infos),
		"has_errors": len(errors) > 0,
		"text_summary": "\n".join(lines),
	}
