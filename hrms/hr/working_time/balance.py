# //// Neoffice — added file (no upstream equivalent): the balance of the hours over of an employee, kept the
# //// way their labour agreement says (lot T, neoffice-maintenance#2623).
"""The balance of the hours over, in the agreement's own way.

Three ways of keeping it, a rule of the agreement (`balance_kind`), and a legal counter beside them all:

- **Expiring lots**: each week's hours over are a lot that expires after the agreement's months (the longer
  months when they were extended in writing for the person). Hours short consume the oldest lots first: that is
  how hours are compensated by time off. A lot that reaches its expiry with hours left is to be paid, with the
  agreement's supplement.
- **Sliding balance**: one running balance; at the end of each month, what lies above the agreement's threshold
  is to be paid with the next month's salary and can no longer be compensated.
- **Annual balance**: one running balance between a floor and a ceiling; at the end of each month the hours above
  the ceiling are to be paid (without supplement until the agreement's number of hours paid that year, with it
  after), the hours below the floor lapse; at the closing day the balance left waits for the decisions the
  agreement shares out (half for the employer, half for the employee, say).
- **The legal counter**: the hours above the legal maximum of the week, added up per calendar year, against the
  legal yearly cap. A warning, never a block.

`compute_balance` is pure: the weeks (hours counted over, hours short, legal excess) and the day come in, the
state of the balance comes out; nothing is written. An hour over that waits for the employer's approval is not
in the weeks given to it.
"""

import datetime
from dataclasses import dataclass, field

from dateutil.relativedelta import relativedelta

from frappe.utils import flt, getdate

from hrms.hr.working_time import rules as catalogue

EPSILON = 1e-6


@dataclass
class WeekLine:
	"""What one week brings to the balance."""

	monday: datetime.date
	over: float = 0.0  # hours over that count (approved when the agreement wants an approval)
	short: float = 0.0  # hours short, as a positive number
	legal_excess: float = 0.0


@dataclass
class Balance:
	kind: str
	on_date: datetime.date
	total: float = 0.0
	lots: list = field(default_factory=list)  # expiring lots still open
	payable: list = field(
		default_factory=list
	)  # {"on": date, "hours": h, "supplement_percent": p, "why": key}
	lapsed: list = field(default_factory=list)  # hours short beyond the floor, at the employer's charge
	closings: list = field(default_factory=list)  # {"on": date, "hours": h, "employer_share": .5, ...}
	legal: dict = field(default_factory=dict)  # {year: hours above the legal maximum}
	legal_cap: float | None = None
	warnings: list = field(default_factory=list)


def _sunday(monday):
	return getdate(monday) + datetime.timedelta(days=6)


def _month_ends(start, end):
	"""The last day of each month from `start`'s month to the month before `end`'s, in order."""
	day = getdate(start).replace(day=1)
	end = getdate(end)
	found = []
	while True:
		last = day + relativedelta(months=1) - datetime.timedelta(days=1)
		if last >= end:
			return found
		found.append(last)
		day = day + relativedelta(months=1)


def compute_balance(rules, weeks: list, on_date, extended_in_writing: bool = False) -> Balance | None:
	"""The balance on `on_date` from the weeks up to it, or None when the agreement does not say how it is kept."""
	kind = rules.get("balance_kind")
	if kind not in (catalogue.EXPIRING_LOTS, catalogue.SLIDING_BALANCE, catalogue.ANNUAL_BALANCE):
		return None
	on_date = getdate(on_date)
	weeks = sorted((w for w in weeks if _sunday(w.monday) <= on_date), key=lambda w: getdate(w.monday))
	result = Balance(kind=kind, on_date=on_date)
	if kind == catalogue.EXPIRING_LOTS:
		_lots(rules, weeks, on_date, extended_in_writing, result)
	else:
		_running(rules, weeks, on_date, kind, result)
	_legal(rules, weeks, result)
	result.total = flt(result.total, 4)
	return result


def _supplement(rules):
	return flt(rules.get("overtime_supplement_percent") or 0)


def _lots(rules, weeks, on_date, extended, result):
	months = rules.get("written_extension_months") if extended else None
	months = months or rules.get("compensation_months")
	open_lots, minus = [], 0.0
	for week in weeks:
		earned = _sunday(week.monday)
		expires = earned + relativedelta(months=int(months)) if months else None
		_expire(open_lots, earned, rules, result)
		if week.over > EPSILON:
			open_lots.append(
				{"earned": earned, "hours": flt(week.over), "left": flt(week.over), "expires": expires}
			)
		short = flt(week.short)
		for lot in open_lots:
			if short <= EPSILON:
				break
			used = min(lot["left"], short)
			lot["left"] -= used
			short -= used
		open_lots[:] = [lot for lot in open_lots if lot["left"] > EPSILON]
		minus += short
	_expire(open_lots, on_date, rules, result)
	result.lots = [{**lot, "left": flt(lot["left"], 4), "hours": flt(lot["hours"], 4)} for lot in open_lots]
	result.total = sum(lot["left"] for lot in open_lots) - minus
	if months is None and open_lots:
		result.warnings.append("compensation_months")


def _expire(open_lots, day, rules, result):
	for lot in list(open_lots):
		if lot["expires"] and lot["expires"] <= day:
			result.payable.append(
				{
					"on": lot["expires"],
					"hours": flt(lot["left"], 4),
					"supplement_percent": _supplement(rules),
					"why": "lot_expired",
					"earned": lot["earned"],
				}
			)
			open_lots.remove(lot)


def _running(rules, weeks, on_date, kind, result):
	balance = 0.0
	paid_this_year, year = 0.0, None
	threshold = rules.get("payment_threshold_hours")
	ceiling = rules.get("balance_ceiling_hours")
	floor = rules.get("balance_floor_hours")
	above = rules.get("payment_above_ceiling") or {}
	closing = rules.get("closing_date")
	decision = rules.get("closing_decision") or {}
	start = getdate(weeks[0].monday) if weeks else on_date
	checks = [(day, "month_end") for day in _month_ends(start, on_date)]
	if kind == catalogue.ANNUAL_BALANCE and closing:
		for check_year in range(start.year, on_date.year + 1):
			day = datetime.date(check_year, *map(int, closing.split("-")))
			if start <= day < on_date:
				checks.append((day, "closing"))
	checks.sort(key=lambda item: (item[0], item[1] == "closing"))
	events = sorted(weeks, key=lambda w: getdate(w.monday))
	index = 0
	for day, what in checks:
		while index < len(events) and _sunday(events[index].monday) <= day:
			balance += flt(events[index].over) - flt(events[index].short)
			index += 1
		if year != day.year:
			year, paid_this_year = day.year, 0.0
		if what == "closing":
			if abs(balance) > EPSILON:
				result.closings.append(
					{
						"on": day,
						"hours": flt(balance, 4),
						"employer_share": decision.get("employer_share"),
						"employee_share": decision.get("employee_share"),
						"options": decision.get("options") or [],
					}
				)
			continue
		limit = threshold if kind == catalogue.SLIDING_BALANCE else ceiling
		if limit is not None and balance > flt(limit) + EPSILON:
			excess = balance - flt(limit)
			balance = flt(limit)
			if kind == catalogue.ANNUAL_BALANCE and above.get("paid_hours_before_supplement") is not None:
				free = max(flt(above["paid_hours_before_supplement"]) - paid_this_year, 0.0)
				plain = min(excess, free)
				if plain > EPSILON:
					result.payable.append(
						{"on": day, "hours": flt(plain, 4), "supplement_percent": 0.0, "why": "above_ceiling"}
					)
				if excess - plain > EPSILON:
					result.payable.append(
						{
							"on": day,
							"hours": flt(excess - plain, 4),
							"supplement_percent": flt(above.get("supplement_percent") or 0),
							"why": "above_ceiling",
						}
					)
			else:
				why = "above_threshold" if kind == catalogue.SLIDING_BALANCE else "above_ceiling"
				result.payable.append(
					{"on": day, "hours": flt(excess, 4), "supplement_percent": None, "why": why}
				)
			paid_this_year += excess
		if floor is not None and balance < -flt(floor) - EPSILON:
			result.lapsed.append({"on": day, "hours": flt(-flt(floor) - balance, 4)})
			balance = -flt(floor)
	while index < len(events):
		balance += flt(events[index].over) - flt(events[index].short)
		index += 1
	result.total = balance


def _legal(rules, weeks, result):
	for week in weeks:
		if week.legal_excess > EPSILON:
			year = getdate(week.monday).year
			result.legal[year] = flt(result.legal.get(year, 0.0) + week.legal_excess, 4)
	result.legal_cap = rules.get("legal_yearly_overtime_cap")
	if result.legal_cap is not None and any(hours > flt(result.legal_cap) for hours in result.legal.values()):
		result.warnings.append("legal_yearly_overtime_cap")
