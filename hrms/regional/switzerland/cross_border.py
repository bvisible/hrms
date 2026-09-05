# //// Neoffice — added file (no upstream equivalent): cross-border worker (frontalier) tax engine
# //// for the DE/FR/IT bilateral agreements.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt

"""Cross-border worker (Grenzgänger/frontalier) tax calculation engine.

Handles country-specific tax rules for employees residing in Germany, France,
or Italy who commute to work in Switzerland. Three bilateral agreements
(legal review 2026-08-20, FTA circular no. 45 + treaty texts):

- Germany (DTA CH-DE art. 15a): Switzerland withholds AT MOST 4.5% of the
  gross salary — the cantonal L/M/N/P tariffs are capped mirrors of A/B/C/H,
  so the ordinary result is CAPPED, not replaced by a flat rate. The regime
  requires a valid Gre-1 residence attestation; without it the ordinary
  (uncapped) tariff applies. Status is lost beyond 60 non-return nights/year.
- France (agreement of 1983, cantons BE/SO/BS/BL/VD/VS/NE/JU): taxed in
  France, no CH withholding — conditional on the 2041-AS residence
  attestation. GE is outside the agreement: ordinary source tax.
- Italy (agreement of 2020, in force 2023-07-17): OLD frontaliers are taxed
  exclusively in Switzerland at the FULL ordinary tariff (they are NOT
  exempt; the ristorno is settled by the canton). NEW frontaliers use the
  R/S/T/U/V tariffs, which ALREADY include the 80% reduction — no extra
  factor may be applied.
"""

from frappe.utils import flt, getdate

from hrms.regional.switzerland.constants import (
	FRENCH_EXEMPTED_CANTONS,
	GERMAN_NON_RETURN_DAY_LIMIT,
	GERMAN_TAX_CAP_RATE,
	ITALIAN_FRONTALIER_CANTONS,
	ITALIAN_NEW_FRONTALIER_CUTOFF,
	ITALIAN_TARIFF_LETTERS,
)

_STANDARD = {
	"treatment": "standard",
	"rate_factor": 1.0,
	"cap_rate": None,
	"skip_source_tax": False,
}


def classify_cross_border_worker(employee_doc, config=None):
	"""Determine cross-border tax treatment for an employee.

	Args:
		employee_doc: Employee document or dict-like with cross-border fields.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with keys:
		- treatment: classification string
		- rate_factor: multiplier for standard rate (always 1.0 — kept for
		  backward compatibility of the result shape)
		- cap_rate: decimal cap on gross (e.g. 0.045) or None
		- skip_source_tax: True if employee is exempt from CH withholding
	"""
	if not employee_doc.get("ch_is_cross_border"):
		return dict(_STANDARD, treatment="not_cross_border")

	country = (employee_doc.get("ch_residence_country") or "").upper()
	canton = (
		employee_doc.get("ch_qst_taxation_canton")
		or employee_doc.get("ch_fiscal_canton")
		or ""
	).upper()

	if not country:
		return dict(_STANDARD)

	if country == "DE":
		return _classify_german(employee_doc, config)

	if country == "FR":
		return _classify_french(employee_doc, canton)

	if country == "IT":
		return _classify_italian(employee_doc, canton)

	# AT, LI or other: standard source tax rules apply
	return dict(_STANDARD)


def _classify_german(employee_doc, config=None):
	"""German DTA art. 15a: ordinary tariff CAPPED at 4.5% of gross.

	The capped regime only applies with a valid Gre-1 residence attestation;
	without it the ordinary tariff applies uncapped (circular 45).
	"""
	if not employee_doc.get("ch_de_gre1_attestation"):
		return dict(_STANDARD, treatment="german_no_attestation")

	cap_rate = flt(config.get("cb_german_flat_rate") if config else 0) / 100 or GERMAN_TAX_CAP_RATE
	return {
		"treatment": "german_capped",
		"rate_factor": 1.0,
		"cap_rate": cap_rate,
		"skip_source_tax": False,
	}


def _classify_french(employee_doc, canton):
	"""French agreement of 1983: 8 cantons exempt (with attestation), GE ordinary.

	The exemption is conditional on the French residence attestation 2041-AS.
	Without it, the employer MUST withhold at the ordinary tariff.
	"""
	if canton == "GE":
		return dict(_STANDARD, treatment="french_ge_source")

	if canton in FRENCH_EXEMPTED_CANTONS:
		if not employee_doc.get("ch_fr_2041as_attestation"):
			return dict(_STANDARD, treatment="french_no_attestation")
		return {
			"treatment": "french_exempt",
			"rate_factor": 1.0,
			"cap_rate": None,
			"skip_source_tax": True,
		}

	# Non-border canton: standard rules
	return dict(_STANDARD)


def _classify_italian(employee_doc, canton):
	"""Italian agreement: old = full ordinary tariff, new = R-V tariffs as-is."""
	if canton not in ITALIAN_FRONTALIER_CANTONS:
		# Not in a frontalier canton: standard source tax
		return dict(_STANDARD)

	# Determine old vs new based on start date
	start_date = employee_doc.get("ch_cross_border_start_date")
	cutoff = getdate(ITALIAN_NEW_FRONTALIER_CUTOFF)

	if start_date and getdate(start_date) >= cutoff:
		# New frontalier: the R/S/T/U/V tariff files already include the 80%
		# reduction — use the standard lookup result unchanged.
		return dict(_STANDARD, treatment="italian_new_rv")

	# Old frontalier: taxed exclusively in Switzerland at the FULL ordinary
	# tariff. NOT exempt (the 40% ristorno to Italian municipalities is
	# settled by the canton, outside payroll).
	return dict(_STANDARD, treatment="italian_old_full")


def get_german_capped_tax(gross, standard_qst_result=None, config=None):
	"""Cap the ordinary source tax at 4.5% of gross (DTA CH-DE art. 15a).

	The cantonal L/M/N/P tariffs are mirrors of A/B/C/H with the cap built
	in. When the standard lookup produced a positive amount, the result is
	min(standard, cap). When no tariff data is available (standard = 0), the
	cap itself is withheld as a conservative fallback — this preserves the
	historical behaviour of this module and never exceeds the treaty maximum.

	Args:
		gross: Monthly gross salary in CHF.
		standard_qst_result: dict from the standard source tax calculation.
		config: Optional Swiss Social Insurance Config dict.

	Returns:
		dict with tax_amount, tax_rate, cap_rate, model.
	"""
	gross = flt(gross)
	if gross <= 0:
		return {"tax_amount": 0, "tax_rate": 0, "cap_rate": 0, "model": "german_capped"}

	cap_rate = flt(config.get("cb_german_flat_rate") if config else 0) / 100 or GERMAN_TAX_CAP_RATE
	cap_amount = round(gross * cap_rate, 2)

	standard_amount = flt((standard_qst_result or {}).get("tax_amount"))
	if standard_amount > 0:
		tax = min(standard_amount, cap_amount)
		capped = tax == cap_amount and standard_amount > cap_amount
	else:
		# No tariff data available: withhold the treaty maximum.
		tax = cap_amount
		capped = True

	return {
		"tax_amount": tax,
		"tax_rate": round(tax / gross, 6) if gross else 0,
		"cap_rate": cap_rate,
		"cap_applied": capped,
		"model": "german_capped",
	}


def validate_italian_tariff_letter(employee_doc):
	"""Return a warning string if a new Italian frontalier lacks an R-V tariff.

	The 80% reduction for new frontaliers lives in the R/S/T/U/V tariff
	files themselves. An ordinary letter (A/B/C/H) would tax them at 100%.

	Returns None when everything is consistent.
	"""
	letter = (employee_doc.get("ch_qst_tariff_category") or "").upper()
	if letter and letter not in ITALIAN_TARIFF_LETTERS:
		return (
			"New Italian frontalier should use one of the tariff letters "
			f"{', '.join(ITALIAN_TARIFF_LETTERS)} (80% reduction built into the "
			f"tariff files); found '{letter}'."
		)
	return None


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
	"""Check if a German cross-border worker exceeds the non-return limit.

	Art. 15a para. 2 DTA CH-DE: frontalier status is lost beyond 60
	non-return nights per year (pro-rated for partial years — not handled
	here; the caller sees the raw YTD count).

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
		Suggested letter string or None if not determinable (HR picks the
		ordinary letter A/B/C/H according to the personal situation).
	"""
	if not employee_doc.get("ch_is_cross_border"):
		return None

	country = (employee_doc.get("ch_residence_country") or "").upper()

	if country == "DE":
		# L/M/N/P mirror A/B/C/H; default to L (single). HR adjusts.
		return "L" if employee_doc.get("ch_de_gre1_attestation") else None

	if country == "FR":
		# GE and non-attested workers use the ordinary letters; exempt
		# cantons have no withholding at all.
		return None

	if country == "IT":
		start_date = employee_doc.get("ch_cross_border_start_date")
		cutoff = getdate(ITALIAN_NEW_FRONTALIER_CUTOFF)
		if start_date and getdate(start_date) >= cutoff:
			return "R"  # Default to R (single). HR adjusts to S/T/U/V as needed.
		return None  # Old frontalier: ordinary letter, full tariff

	return None


def get_cross_border_tax(employee_doc, salary_slip_doc, config, standard_qst_result):
	"""Main entry point: apply cross-border rules to source tax.

	Called from source_tax.calculate_source_tax() after computing the standard
	result. May cap or zero out the standard tax amount.

	Args:
		employee_doc: Employee document or dict-like.
		salary_slip_doc: Salary Slip document.
		config: Swiss Social Insurance Config dict.
		standard_qst_result: dict from standard source tax calculation.

	Returns:
		Modified tax result dict.
	"""
	classification = classify_cross_border_worker(employee_doc, config)
	treatment = classification["treatment"]

	if treatment == "not_cross_border":
		return standard_qst_result

	if treatment == "german_capped":
		gross = sum(flt(row.default_amount) for row in salary_slip_doc.get("earnings"))
		return get_german_capped_tax(gross, standard_qst_result, config)

	if treatment == "french_exempt":
		return {
			"tax_amount": 0,
			"tax_rate": 0,
			"model": treatment,
			"skip_source_tax": True,
		}

	if treatment in ("french_ge_source", "french_no_attestation", "german_no_attestation"):
		# Ordinary tariff, uncapped (missing attestation or GE regime).
		result = dict(standard_qst_result)
		result["model"] = f"{result.get('model', 'monthly')}_{treatment}"
		return result

	if treatment == "italian_new_rv":
		# The R-V tariffs already include the 80% reduction: use as-is.
		result = dict(standard_qst_result)
		result["model"] = f"{result.get('model', 'monthly')}_italian_new_rv"
		return result

	if treatment == "italian_old_full":
		# Full ordinary tariff — exclusively taxed in Switzerland.
		result = dict(standard_qst_result)
		result["model"] = f"{result.get('model', 'monthly')}_italian_old_full"
		return result

	# Default: standard rules
	return standard_qst_result
