# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Cross-border worker (Grenzgänger/frontalier) tax calculation engine.

Handles country-specific tax rules for employees residing in Germany, France,
or Italy who commute to work in Switzerland. Three bilateral agreements:
- Germany (DTA CH-DE): flat 4.5% withholding
- France (CDI CH-FR): mostly French-taxed, except Geneva (source tax)
- Italy (CDI CH-IT): old frontaliers exempt, new frontaliers at 80% rate
"""

from frappe.utils import flt, getdate

from hrms.regional.switzerland.constants import (
	FRENCH_EXEMPTED_CANTONS,
	GERMAN_FLAT_TAX_RATE,
	GERMAN_NON_RETURN_DAY_LIMIT,
	ITALIAN_FRONTALIER_CANTONS,
	ITALIAN_NEW_FRONTALIER_CUTOFF,
	ITALIAN_NEW_RATE_FACTOR,
)


def classify_cross_border_worker(employee_doc, config=None):
	"""Determine cross-border tax treatment for an employee.

	Args:
		employee_doc: Employee document or dict-like with cross-border fields.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with keys:
		- treatment: classification string
		- rate_factor: multiplier for standard rate (1.0 = unchanged)
		- flat_rate: flat rate decimal (e.g., 0.045) or None
		- skip_source_tax: True if employee is exempt from CH withholding
	"""
	if not employee_doc.get("ch_is_cross_border"):
		return {
			"treatment": "not_cross_border",
			"rate_factor": 1.0,
			"flat_rate": None,
			"skip_source_tax": False,
		}

	country = (employee_doc.get("ch_residence_country") or "").upper()
	canton = (
		employee_doc.get("ch_qst_taxation_canton")
		or employee_doc.get("ch_fiscal_canton")
		or ""
	).upper()

	if not country:
		return {
			"treatment": "standard",
			"rate_factor": 1.0,
			"flat_rate": None,
			"skip_source_tax": False,
		}

	if country == "DE":
		return _classify_german(config)

	if country == "FR":
		return _classify_french(canton)

	if country == "IT":
		return _classify_italian(employee_doc, canton)

	# AT, LI or other: standard source tax rules apply
	return {
		"treatment": "standard",
		"rate_factor": 1.0,
		"flat_rate": None,
		"skip_source_tax": False,
	}


def _classify_german(config=None):
	"""German DTA: flat 4.5% withholding tax."""
	flat_rate = flt(config.get("cb_german_flat_rate") if config else 0) / 100 or GERMAN_FLAT_TAX_RATE
	return {
		"treatment": "german_flat",
		"rate_factor": 1.0,
		"flat_rate": flat_rate,
		"skip_source_tax": False,
	}


def _classify_french(canton):
	"""French CDI: most cantons exempt, GE uses source tax."""
	if canton == "GE":
		return {
			"treatment": "french_ge_source",
			"rate_factor": 1.0,
			"flat_rate": None,
			"skip_source_tax": False,
		}

	if canton in FRENCH_EXEMPTED_CANTONS:
		return {
			"treatment": "french_exempt",
			"rate_factor": 1.0,
			"flat_rate": None,
			"skip_source_tax": True,
		}

	# Non-border canton: standard rules
	return {
		"treatment": "standard",
		"rate_factor": 1.0,
		"flat_rate": None,
		"skip_source_tax": False,
	}


def _classify_italian(employee_doc, canton):
	"""Italian CDI: old frontaliers exempt, new frontaliers at 80%."""
	if canton not in ITALIAN_FRONTALIER_CANTONS:
		# Not in a frontalier canton: standard source tax
		return {
			"treatment": "standard",
			"rate_factor": 1.0,
			"flat_rate": None,
			"skip_source_tax": False,
		}

	# Determine old vs new based on start date
	start_date = employee_doc.get("ch_cross_border_start_date")
	cutoff = getdate(ITALIAN_NEW_FRONTALIER_CUTOFF)

	if start_date and getdate(start_date) >= cutoff:
		# New frontalier: 80% of standard rate
		return {
			"treatment": "italian_new_80pct",
			"rate_factor": ITALIAN_NEW_RATE_FACTOR,
			"flat_rate": None,
			"skip_source_tax": False,
		}

	# Old frontalier: taxed only in Italy, no CH withholding
	return {
		"treatment": "italian_old_exempt",
		"rate_factor": 1.0,
		"flat_rate": None,
		"skip_source_tax": True,
	}


def get_german_flat_tax(gross, config=None):
	"""Calculate German flat 4.5% withholding tax.

	Args:
		gross: Monthly gross salary in CHF.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with tax_amount, tax_rate, model.
	"""
	gross = flt(gross)
	if gross <= 0:
		return {"tax_amount": 0, "tax_rate": 0, "model": "german_flat"}

	rate = flt(config.get("cb_german_flat_rate") if config else 0) / 100 or GERMAN_FLAT_TAX_RATE
	tax = round(gross * rate, 2)

	return {
		"tax_amount": tax,
		"tax_rate": rate,
		"model": "german_flat",
	}


def apply_italian_new_rate_factor(standard_tax_result, config=None):
	"""Apply rate factor (default 80%) to standard source tax for Italian new frontaliers.

	Args:
		standard_tax_result: dict from calculate_source_tax with tax_amount.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		Modified dict with adjusted tax_amount.
	"""
	factor = flt(config.get("cb_italian_new_rate_factor") if config else 0) / 100 or ITALIAN_NEW_RATE_FACTOR
	factor = max(0.0, min(1.0, factor))

	result = dict(standard_tax_result)
	result["tax_amount"] = round(flt(result.get("tax_amount", 0)) * factor, 2)
	result["model"] = result.get("model", "monthly") + "_italian_80pct"
	result["rate_factor"] = factor

	return result


def check_french_telework_threshold(employee, year, config=None):
	"""Check if a French cross-border worker exceeds the telework threshold.

	Queries submitted Cross-Border Telework Log records for the year.

	Args:
		employee: Employee ID.
		year: Calendar year.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with ytd_pct, threshold, exceeds_threshold.
	"""
	import frappe

	from hrms.regional.switzerland.constants import FRENCH_TELEWORK_THRESHOLD

	threshold = flt(config.get("cb_french_telework_threshold") if config else 0) / 100 or FRENCH_TELEWORK_THRESHOLD

	result = frappe.db.get_all(
		"Cross-Border Telework Log",
		filters={
			"employee": employee,
			"year": int(year),
			"docstatus": 1,
		},
		fields=[
			"sum(telework_days) as total_telework",
			"sum(total_work_days) as total_work",
		],
	)

	if result and result[0].get("total_work"):
		ytd_pct = flt(result[0]["total_telework"]) / flt(result[0]["total_work"])
	else:
		ytd_pct = 0

	return {
		"ytd_pct": round(ytd_pct * 100, 2),
		"threshold": round(threshold * 100, 2),
		"exceeds_threshold": ytd_pct > threshold,
	}


def check_german_non_return_days(employee, year):
	"""Check if a German cross-border worker exceeds the non-return day limit.

	Args:
		employee: Employee ID.
		year: Calendar year.

	Returns:
		dict with ytd_days, limit, exceeds_limit.
	"""
	import frappe

	result = frappe.db.get_all(
		"Cross-Border Telework Log",
		filters={
			"employee": employee,
			"year": int(year),
			"docstatus": 1,
		},
		fields=["sum(non_return_days) as total_non_return"],
	)

	ytd_days = int(result[0].get("total_non_return") or 0) if result else 0

	return {
		"ytd_days": ytd_days,
		"limit": GERMAN_NON_RETURN_DAY_LIMIT,
		"exceeds_limit": ytd_days > GERMAN_NON_RETURN_DAY_LIMIT,
	}


def suggest_tariff_letter(employee_doc):
	"""Suggest appropriate QST tariff letter based on cross-border status.

	Args:
		employee_doc: Employee document or dict-like.

	Returns:
		Suggested letter string or None if not determinable.
	"""
	if not employee_doc.get("ch_is_cross_border"):
		return None

	country = (employee_doc.get("ch_residence_country") or "").upper()

	if country == "DE":
		return "G"

	if country == "FR":
		canton = (
			employee_doc.get("ch_qst_taxation_canton")
			or employee_doc.get("ch_fiscal_canton")
			or ""
		).upper()
		if canton == "GE":
			return "G"
		return None  # French exempt cantons: no source tax

	if country == "IT":
		start_date = employee_doc.get("ch_cross_border_start_date")
		cutoff = getdate(ITALIAN_NEW_FRONTALIER_CUTOFF)
		if start_date and getdate(start_date) >= cutoff:
			return "R"  # Default to R (single). HR adjusts to S/T/U/V as needed.
		return None  # Old frontalier: exempt

	return None


def get_cross_border_tax(employee_doc, salary_slip_doc, config, standard_qst_result):
	"""Main entry point: apply cross-border rules to source tax.

	Called from source_tax.calculate_source_tax() after computing the standard result.
	May override, reduce, or zero out the standard tax amount.

	Args:
		employee_doc: Employee document or dict-like.
		salary_slip_doc: Salary Slip document.
		config: Swiss Social Insurance Config dict.
		standard_qst_result: dict from standard source tax calculation.

	Returns:
		Modified tax result dict.
	"""
	classification = classify_cross_border_worker(employee_doc, config)

	if classification["treatment"] == "not_cross_border":
		return standard_qst_result

	if classification["treatment"] == "german_flat":
		gross = sum(flt(row.default_amount) for row in salary_slip_doc.get("earnings"))
		return get_german_flat_tax(gross, config)

	if classification["treatment"] in ("french_exempt", "italian_old_exempt"):
		return {
			"tax_amount": 0,
			"tax_rate": 0,
			"model": classification["treatment"],
			"skip_source_tax": True,
		}

	if classification["treatment"] == "french_ge_source":
		# GE frontaliers use standard ESTV tariff codes G/M/N/Q
		return standard_qst_result

	if classification["treatment"] == "italian_new_80pct":
		return apply_italian_new_rate_factor(standard_qst_result, config)

	# Default: standard rules
	return standard_qst_result
