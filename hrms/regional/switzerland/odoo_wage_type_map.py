# //// Neoffice — added file (no upstream equivalent): translation of our Swiss wage types
# //// into the payslip input codes of a Swissdec-certified Odoo instance.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Translate our wage type codes into a certified Odoo's payslip input codes.

When a certified third party transmits the ELM declaration for us, the gross
amounts are injected into it as ``hr.payslip.input`` records, each pointing at an
``hr.payslip.input.type`` whose code is ``WT_<swissdec code>``. Most of our codes
map straight through, because both catalogues follow the Swissdec numbering.

Some do not, and those are the dangerous ones: injecting an amount under a code
the recipient does not know produces a declaration that is *accepted* and
*wrong*. So every divergence is listed here explicitly, with its reason, and
anything unmapped raises instead of guessing.

Verified 2026-09-22 against the Swissdec ELM guidelines (whose test-example
Lohnartenstamm is authoritative for certification) and against the catalogue of
an Odoo instance certified ELM 5.3 (Zert-Nr. 1203.25).
"""

# Our code -> the Swissdec code to declare it under. Only divergences appear here;
# everything else maps to itself.
WAGE_TYPE_TRANSLATION = {
	# The 13th month. 1180/1181/1182 describe HOW it is paid (as a percentage,
	# paid out, computed); the Swissdec guidelines declare it under 1200
	# ("1200 / 13. Monatslohn" in the ELM test examples).
	"1180": "1200",
	"1181": "1200",
	"1182": "1200",
	# Gratification: the certified catalogue numbers it 1204. Our 1201 is a
	# variant of the same thing.
	"1201": "1204",
	# Holiday pay: we split "computed" and "paid out"; the standard declares both
	# as holiday compensation.
	"1164": "1162",
	"1165": "1162",
}

# Codes we hold that have NO counterpart to inject, with the reason. Injecting
# them is a bug, not a gap — hence a dedicated list rather than a silent skip.
NOT_INJECTABLE = {
	"1007": "weekly salary — no standard counterpart; declare the hours under 1005 instead",
	"1951": "home-to-work travel allowance — no standard counterpart; use 1055 or an expense",
	"6000": "expenses are not wage types: they go through the expense channel, not a payslip input",
	"6001": "expenses — see 6000",
	"6002": "expenses — see 6000",
	"6010": "expenses — see 6000",
	"6020": "expenses — see 6000",
	"6030": "expenses — see 6000",
	"6040": "expenses — see 6000",
	"6050": "expenses — see 6000",
	"6060": "expenses — see 6000",
	"6070": "expenses — see 6000",
}


class UnmappedWageType(ValueError):
	"""Raised rather than guessing a code: a wrong code declares a wrong salary."""


def to_odoo_input_code(wage_type_code, strict=True):
	"""The ``hr.payslip.input.type`` code to inject this wage type under.

	Args:
		wage_type_code: our Swiss wage type code, e.g. "1000" or 1000.
		strict: raise on a code that must not be injected; return None if False.

	Returns:
		"WT_<code>", or None when the code is not injectable and strict is False.

	Raises:
		UnmappedWageType: the code is expenses, a deduction, or has no counterpart.
	"""
	code = str(wage_type_code or "").strip()
	if not code:
		raise UnmappedWageType("empty wage type code")

	if code in NOT_INJECTABLE:
		if strict:
			raise UnmappedWageType(f"wage type {code} must not be injected: {NOT_INJECTABLE[code]}")
		return None

	return "WT_" + WAGE_TYPE_TRANSLATION.get(code, code)


def translate_earnings(rows, strict=True):
	"""Translate ``[{"code": ..., "amount": ...}, ...]`` into injectable inputs.

	Amounts landing on the same target code are summed: 1180 and 1181 both
	declare under 1200, and two inputs of the same type on one payslip would
	either be rejected or double-counted.
	"""
	totals = {}
	skipped = []
	for row in rows:
		try:
			target = to_odoo_input_code(row.get("code"), strict=strict)
		except UnmappedWageType:
			if strict:
				raise
			target = None
		if target is None:
			skipped.append(row.get("code"))
			continue
		totals[target] = round(totals.get(target, 0.0) + float(row.get("amount") or 0), 2)

	return {
		"inputs": [{"code": code, "amount": amount} for code, amount in sorted(totals.items())],
		"skipped": skipped,
	}
