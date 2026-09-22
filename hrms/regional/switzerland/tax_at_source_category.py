# //// Neoffice — added file (no upstream equivalent): resolve the Swissdec TaxAtSourceCategory.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Decide what goes into the ELM ``TaxAtSourceCategory`` element.

The element is a **choice**: exactly one of ``TaxAtSourceCode`` (the usual tariff
code, pattern ``[A-Z][0-9][YN]``), ``CategoryPredefined`` or ``CategoryOpen``
must be present, and the choice is mandatory whenever the person is liable.

Until now we only ever emitted a tariff code, so a case with no tariff code at
all could not be declared. The one that matters here is **SFN**: under the
French special agreement the cantons BL, BS, SO, VD, VS, NE, JU and BE withhold
nothing from a French-resident employee, but **still declare the taxable salary**
to the canton. Two of those cantons — VD and VS — are our first market, so a
frontalier working there was simply not declarable.

Our business logic already classifies these people correctly (cross_border.py
returns ``skip_source_tax`` for them). This module turns that classification into
the element the schema expects.
"""

from hrms.regional.switzerland.constants import (
	BOARD_FEE_WAGE_TYPES,
	FRENCH_EXEMPTED_CANTONS,
	QST_CATEGORY_SFN,
	QST_PREDEFINED_CATEGORIES,
)

BOARD_FEE_CATEGORIES = ("HEN", "HEY")

CATEGORY_TARIFF = "tariff"
CATEGORY_PREDEFINED = "predefined"
CATEGORY_OPEN = "open"


def resolve_tax_at_source_category(employee_doc, canton=None, tariff_code=None):
	"""Which branch of the TaxAtSourceCategory choice applies, and with what value.

	Precedence, highest first:
	  1. an explicitly declared predefined category — it encodes a decision
	     (a board fee, a correction period) that nothing else can express;
	  2. an explicitly declared open category, for a canton-specific arrangement;
	  3. SFN, derived from the French agreement when the employee is a French
	     resident in one of the eight cantons AND holds the 2041-AS attestation
	     (without it the employer must withhold at the ordinary tariff, so the
	     tariff code applies and there is no category);
	  4. the tariff code.

	Returns:
		dict with ``kind`` (one of the CATEGORY_* constants), ``value``, and
		``withhold`` — False when no source tax may be deducted although the
		salary is still declared. ``None`` when the person is not liable at all.
	"""
	employee_doc = employee_doc or {}

	declared = (employee_doc.get("ch_qst_predefined_category") or "").strip().upper()
	if declared:
		if declared not in QST_PREDEFINED_CATEGORIES:
			raise ValueError(
				f"{declared!r} is not a Swissdec predefined source-tax category "
				f"(expected one of {', '.join(QST_PREDEFINED_CATEGORIES)})"
			)
		# SFN and the NON/NOY correction categories withhold nothing.
		withhold = declared not in (QST_CATEGORY_SFN, "NON", "NOY")
		return {"kind": CATEGORY_PREDEFINED, "value": declared, "withhold": withhold}

	open_category = (employee_doc.get("ch_qst_open_category") or "").strip()
	if open_category:
		return {"kind": CATEGORY_OPEN, "value": open_category, "withhold": True}

	if _is_french_agreement_exempt(employee_doc, canton):
		return {"kind": CATEGORY_PREDEFINED, "value": QST_CATEGORY_SFN, "withhold": False}

	code = (tariff_code or employee_doc.get("ch_qst_tariff_code") or "").strip()
	if not code:
		return None
	return {"kind": CATEGORY_TARIFF, "value": code, "withhold": True}


def _is_french_agreement_exempt(employee_doc, canton):
	"""French resident, in one of the eight agreement cantons, with the attestation.

	Geneva is deliberately excluded: it is outside the 1983 agreement and
	withholds at the ordinary tariff, so a Geneva frontalier keeps a tariff code.
	"""
	canton = (canton or employee_doc.get("ch_qst_taxation_canton")
	          or employee_doc.get("ch_fiscal_canton") or "").strip().upper()
	if canton not in FRENCH_EXEMPTED_CANTONS:
		return False
	residence = (employee_doc.get("ch_residence_country") or "").strip().upper()
	if residence not in ("FR", "FRA", "FRANCE"):
		return False
	# Without the 2041-AS attestation the employer MUST withhold at the ordinary
	# tariff — the exemption is conditional, never automatic.
	return bool(employee_doc.get("ch_fr_2041as_attestation"))


def detect_split_required(wage_type_codes, category):
	"""Does this person need to be declared twice?

	A board member domiciled abroad is taxed on his fee at a linear rate under
	HEN/HEY, while the ordinary salary he may also draw keeps its tariff code.
	One ``TaxAtSourceCategory`` cannot carry both — it is a choice — so the ELM
	guidelines resolve it by entering the person **twice**, with two personnel
	numbers and two accounting circles.

	Declaring such a person under a single category is not rejected by the
	recipient; it silently taxes part of the income at the wrong rate. Hence a
	detection rather than a best guess.

	Args:
		wage_type_codes: the wage type codes actually paid in the period.
		category: the resolved category, as returned by
			``resolve_tax_at_source_category`` (may be None).

	Returns:
		dict describing the conflict, or None when there is none.
	"""
	if not category:
		return None
	codes = {str(c).strip() for c in (wage_type_codes or []) if str(c).strip()}
	board_codes = sorted(codes & BOARD_FEE_WAGE_TYPES)
	other_codes = sorted(codes - BOARD_FEE_WAGE_TYPES)
	value = category.get("value")

	if board_codes and category["kind"] == CATEGORY_TARIFF:
		return {
			"reason": "board_fee_under_tariff_code",
			"board_wage_types": board_codes,
			"category": value,
			"message": (
				f"Board fees ({', '.join(board_codes)}) are declared under tariff code "
				f"{value}, but a non-resident board member is taxed on them at a linear "
				"rate under HEN/HEY. Enter the person twice — one personnel number for "
				"the salary, one for the fee — as the ELM guidelines require."
			),
		}

	if other_codes and value in BOARD_FEE_CATEGORIES:
		return {
			"reason": "salary_under_board_fee_category",
			"other_wage_types": other_codes,
			"category": value,
			"message": (
				f"Ordinary salary ({', '.join(other_codes)}) is declared under the board-fee "
				f"category {value}, which taxes it at a linear rate. Enter the person twice — "
				"one personnel number for the salary, one for the fee."
			),
		}

	return None
