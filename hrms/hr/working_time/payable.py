# //// Neoffice — added file (no upstream equivalent): the lines the payroll pays from the working time, one entry
# //// point for the bridge to the payroll (lot T, neoffice-maintenance#2623).
"""What the working time gives the payroll to pay, for the days from `first` to `last`.

- `overtime`: the hours over that fell due for payment in the period (a lot that expired, the part of a balance
  above its threshold or its ceiling), each paid as the hour itself and its supplement in per cent (0 % is the
  hour alone; None is a supplement the agreement does not settle);
- `time_range`: the hours worked in a time range of the agreement (night, Sunday, public holiday…), paid as their
  supplement only, since the hour itself is in the salary, or as an amount per hour;
- at the end of the contract (the person's relieving date in the period): `balance_at_exit`, the hours over left,
  paid with the supplement; `short_at_exit`, the hours short left, never withheld here (the HR decides, and some
  agreements allow it only for the employee's fault); `rest_days_at_exit`, the rest days still owed, each paid
  as the monthly salary divided by the agreement's daily divisor.

Turning a line into money is the payroll's: the agreement's hourly and daily divisors come beside the lines.
`collect` is pure; `payable_lines` reads the balance, the supplements and the rest of an employee.
"""

from frappe.utils import flt, getdate

EPSILON = 1e-6


def collect(rules, first, last, balance=None, supplements=(), rest=None, relieving_date=None) -> dict:
	"""The lines to pay from the figures of the engine, for the days from `first` to `last`."""
	first, last = getdate(first), getdate(last)
	lines = []
	for item in balance.payable if balance else []:
		if first <= getdate(item["on"]) <= last:
			lines.append(
				{
					"date": getdate(item["on"]),
					"kind": "overtime",
					"hours": flt(item["hours"], 4),
					"supplement_percent": item.get("supplement_percent"),
					"why": item.get("why"),
				}
			)
	for item in supplements or ():
		if first <= getdate(item["date"]) <= last:
			lines.append(
				{
					"date": getdate(item["date"]),
					"kind": "time_range",
					"hours": flt(item["hours"], 4),
					"supplement_percent": item.get("percent"),
					"amount_per_hour": item.get("amount_per_hour"),
					"label": item.get("label"),
					"article": item.get("article"),
				}
			)
	exit_day = getdate(relieving_date) if relieving_date else None
	if exit_day and first <= exit_day <= last:
		left = flt(balance.total, 4) if balance else 0.0
		if left > EPSILON:
			lines.append(
				{
					"date": exit_day,
					"kind": "balance_at_exit",
					"hours": left,
					"supplement_percent": balance.supplement.get("percent"),
				}
			)
		elif left < -EPSILON:
			lines.append({"date": exit_day, "kind": "short_at_exit", "hours": -left, "to_decide": True})
		owed = flt(sum(lot["days"] for lot in rest.rest_owed), 4) if rest else 0.0
		if owed > EPSILON:
			lines.append({"date": exit_day, "kind": "rest_days_at_exit", "days": owed})
	lines.sort(key=lambda line: (line["date"], line["kind"]))
	return {
		"from": first,
		"to": last,
		"hourly_divisor": rules.get("hourly_divisor"),
		"daily_divisor": rules.get("daily_divisor"),
		"lines": lines,
	}


def payable_lines(employee: str, first, last) -> dict | None:
	"""The lines to pay of an employee for the days from `first` to `last`; None without an agreement."""
	import frappe

	from hrms.hr.working_time.agreement import rules_for
	from hrms.hr.working_time.store import balance_of, rest_of
	from hrms.hr.working_time.supplements import supplements_of

	rules = rules_for(employee)
	if rules is None:
		return None
	relieving_date = frappe.db.get_value("Employee", employee, "relieving_date")
	last = getdate(last)
	# after the person left there is nothing more to count: the figures are those of their last day
	on = min(last, getdate(relieving_date)) if relieving_date else last
	return {
		"employee": employee,
		**collect(
			rules,
			first,
			last,
			balance=balance_of(employee, on),
			supplements=supplements_of(employee, first, last) or [],
			rest=rest_of(employee, on),
			relieving_date=relieving_date,
		),
	}
