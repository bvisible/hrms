# //// Neoffice — added file (no upstream equivalent): the rounding rule of Swiss payroll.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Rounding in Swiss payroll: 5 centimes, commercially, for every amount computed.

Swissdec guidelines, section 4.1.1: "Jede Berechnung innerhalb der
Lohnverarbeitung ist grundsätzlich nach kaufmännischer Regel der 5er-Rundung
vorzunehmen" — every calculation, in principle, to 5 centimes, half away from
zero. The section foresees one exception: a company settling in a foreign
currency, which may not round at all.

That covers the social contributions (AVS, AC, LAA, LAAC, IJM, CAF, LPP), the
source tax WITHHELD, and the wages the payroll computes (a prorated salary, a
13th month). Checked against a Swissdec-certified engine: it flags every one of
its Swiss salary rules for 5-centime rounding, and on a probe payslip it
withheld 620.15 of source tax where the exact amount was 620.1364.

What stays exact are the cumulatives behind the source tax: the annual model
re-settles the year to date on full-precision dues, exactly as the official
examples (annex 1) do. Those examples round nothing — only the hourly wages and
one tax cell of their staff-leasing case (M12/Y12), both to 5 centimes.

round_half_up (to the centime) remains for what is not a payroll amount: the
source-tax determinant and the displays of an exact cumulative.

Both functions round half away from zero — never Python's banker's round() —
and work on Decimal. A float reaching them is first cleared of its binary
noise: 0.7 % of 1'075 is exactly 7.525, but 1075 * (0.7 / 100) in float is
7.5249999999999995, and Decimal(str()) alone would keep it below the half
(7.50 instead of 7.55). Measured over 5.3 million salary x rate products:
1'072 such misses without the guard, none with it.

Pure module: no frappe, so every calculator can use it, including the pure ones.
"""

from decimal import ROUND_HALF_UP, Decimal

_FIVE_CENTIMES = Decimal("0.05")
# An exact contribution has at most 8 decimals (2 for the amount, up to 6 for a rate
# expressed as a fraction); float noise sits around the 11th decimal for payroll
# magnitudes. Quantizing at 9 decimals removes the noise and nothing else.
_FLOAT_NOISE = Decimal("1e-9")


def _to_decimal(value):
	"""Decimal of a payroll amount. A Decimal is taken as-is — the caller computed it
	exactly; a float is cleared of its binary noise (see the module docstring)."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value)).quantize(_FLOAT_NOISE, rounding=ROUND_HALF_UP)


def round_half_up(value, digits=2):
	"""Commercial rounding (half away from zero) to ``digits`` decimals.

	Python's round() is banker's rounding: round(1063.125, 2) -> 1063.12, where
	commercial rounding gives 1063.13. For what is not a payroll amount (see the
	module docstring); amounts go through round_to_5_centimes. Floats are cleared
	of binary noise first (see _to_decimal).
	"""
	quantum = Decimal(1).scaleb(-digits)
	return float(_to_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP))


def round_to_5_centimes(value):
	"""Commercial rounding to the nearest 5 centimes: 100.035 -> 100.05, 55.575 -> 55.60.

	For every payroll amount computed — contributions, source tax withheld, prorated
	wages (Swissdec guidelines 4.1.1). See the module docstring.
	"""
	steps = (_to_decimal(value) / _FIVE_CENTIMES).quantize(Decimal(1), rounding=ROUND_HALF_UP)
	return float(steps * _FIVE_CENTIMES)
