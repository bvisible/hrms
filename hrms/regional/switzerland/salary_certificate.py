# //// Neoffice — added file (no upstream equivalent): the positions and the remarks of the Swiss
# //// salary certificate (Form 11), computed from a year of salary slips.
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# License: GNU General Public License v3. See license.txt
"""Salary certificate (Form 11): positions and remarks from the salary slips of a year.

Where a slip row goes, in this order:

1. the certificate mapping of the social insurance configuration, when it names the component
   — an explicit choice; a row there marked "not in the certificate" leaves the component out;
2. else the salary certificate position of the component, or of its wage type in the catalogue;
3. else, for an amount paid, box 1: income left off the certificate is worse than income
   misfiled in it.

Until 2026-09-23 only the configuration's mapping counted, and its default rows covered seven
components: a bonus (box 3), an APG or maternity allowance (box 7), family allowances,
overtime and every expense reimbursement were on no certificate at all.

What never goes on it: the employer's contributions, which are not the employee's; a row that
only raises the insurance bases without being paid, unless its wage type is income of the
employee (tips, 1920). Box 9 takes AVS/AI/APG, AC and AANP only (FAQ 2026 on the salary
certificate, 9.1 and 9.2): the IJM and LAAC premiums and the cantonal contributions withheld
are stated in box 15 instead. Box 14 is text only: the benefits the employer cannot value
(Wegleitung Rz 62).

Amounts are whole francs, rounded half up: the form says "only whole franc amounts" and the
Swissdec guidelines (6.0, 9.1.2) require whole numbers for the barcode and the transmission.
Box 8 and box 11 are computed from the rounded boxes, so that the printed form adds up.

The texts of box 15 are data, not interface strings: the certificate speaks its own language
(fr, de, it or en), not the language of whoever prints it. The Swissdec standard remarks keep
the wording of the Swissdec guidelines 6.0 (annex 5, StandardRemarks.xml) — the wording the
certified payroll software print. Same reasoning as the barcode labels (issue #239).

Pure module: rows in, positions and remarks out. The document fetches the rows.
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

INCOME_POSITIONS = ("1", "2.1", "2.2", "2.3", "3", "4", "5", "6", "7")
DEDUCTION_POSITIONS = ("9", "10.1", "10.2", "12")
EXPENSE_POSITIONS = ("13.1.1", "13.1.2", "13.2.1", "13.2.2", "13.2.3", "13.3")
# Positions whose kind of benefit must be named next to the amount (Wegleitung Rz 26, 31, 54,
# 58, 62). Box 14 is only that: a text without an amount.
DESCRIBED_POSITIONS = ("2.3", "3", "4", "7", "13.1.2", "13.2.3", "14")
TEXT_ONLY_POSITIONS = ("14",)

LANGUAGES = ("fr", "de", "it", "en")
# Swissdec guidelines 6.0, 9.1.5: a certificate that is not final carries this DocID.
DRAFT_DOC_ID = "Ébauche – Brouillon – Bozza"

# Box 9: AVS/AI/APG and AC (5010-5023), LAA occupational and non-occupational (5030-5042).
_BOX_9_CODES = ((5010, 5023), (5030, 5042))
# Withheld from the employee but not deductible in box 9: IJM (5050-5053) and LAAC (5046-5048).
_IJM_CODES = (5050, 5053)
_LAAC_CODES = (5046, 5048)
# Income replacement benefits the employer pays out for an insurer (FAQ 2026, 1.6): APG, military
# insurance, AI, accident, sickness and maternity daily allowances. Not the pensions (2021, 2026,
# 2031) nor the correction of a daily allowance (2050), which belongs with the salary.
_REPLACEMENT_INCOME_CODES = frozenset({2000, 2005, 2010, 2015, 2020, 2025, 2030, 2035, 2040})
# Compensation of the unemployment insurance for short-time work and bad weather.
_SHORT_TIME_WORK_CODES = frozenset({2070})
_FAMILY_ALLOWANCE_CODES = (3000, 3099)

# The language a canton's tax administration reads: the majority one for FR, VS, BE and GR.
_CANTON_LANGUAGES = {"GE": "fr", "VD": "fr", "NE": "fr", "JU": "fr", "FR": "fr", "VS": "fr", "TI": "it"}

# Swissdec guidelines 6.0, annex 5, StandardRemarks.xml — texts joined around their variable.
_STANDARD_REMARKS = {
	"rectificate": {
		"fr": "Rectification d'un certificat de salaire incorrect: Date: {date} DocID: {doc_id}",
		"de": "Rektifikat eines fehlerhaften Lohnausweises: Datum: {date} DocID: {doc_id}",
		"it": "Rettificazione di un certificato di salario errato: Data: {date} DocID: {doc_id}",
		"en": "Rectificate of an incorrect salary declaration: Date: {date} DocID: {doc_id}",
	},
	"number_of_certificates": {
		"fr": "Un de {count} certificats de salaire.",
		"de": "Einer von {count} Lohnausweisen.",
		"it": "Uno di {count} certificati di salario.",
		"en": "One of {count} salary certificates.",
	},
	"part_time": {
		"fr": "Poste à {rate}%.",
		"de": "{rate}%-Stelle.",
		"it": "Posto al {rate}%.",
		"en": "{rate}% figure.",
	},
	"expense_regulation": {
		"fr": "Règlement des frais agréé par le canton {canton} le {date}.",
		"de": "Spesenreglement durch Kanton {canton} am {date} genehmigt.",
		"it": "Regolamento delle spese approvato dal cantone {canton} il {date}.",
		"en": "Expenses regulations approved by the canton {canton} on {date}.",
	},
	# ELM 6.0 schema, StandardRemark/ShortTimeWorkCompensation (no English text there).
	"short_time_work_in_box_1": {
		"fr": "Indemnité en cas de réduction de l'horaire de travail incluse dans le chiffre 1.",
		"de": "Kurzarbeitsentschädigung in Ziffer 1 enthalten.",
		"it": "Compensazione per la riduzione dell'orario di lavoro inclusa nella figura 1.",
		"en": "Short-time work compensation included in box 1.",
	},
	"tax_at_source": {
		"fr": (
			"Les personnes imposées à la source peuvent exiger par demande écrite et motivée "
			"jusqu'au 31 mars {year} auprès de l'administration cantonale des impôts compétente une "
			"décision sur l'existence et l'étendue de l'assujettissement à l'impôt à la source ou une "
			"taxation ordinaire ultérieure, respectivement un nouveau calcul de l'impôt à la source. "
			"Sans demande respectant la forme et le délai, le prélèvement de l'impôt à la source est "
			"définitif."
		),
		"de": (
			"Quellensteuerpflichtige Personen können schriftlich und begründet bis 31. März {year} "
			"bei der zuständigen kantonalen Steuerbehörde eine Verfügung über Bestand und Umfang der "
			"Quellensteuerpflicht oder eine nachträgliche ordentliche Veranlagung bzw. eine "
			"Neuberechnung der Quellensteuer verlangen. Ohne form- und fristgerechten Antrag wird der "
			"Quellensteuerabzug definitiv."
		),
		"it": (
			"Le persone tassate alla fonte possono pretendere per iscritto e in modo motivato entro "
			"il 31 marzo {year} presso l'autorità fiscale cantonale competente una decisione circa la "
			"sussistenza e l'entità dell'imposta alla fonte oppure una tassazione supplementare "
			"ordinaria ovvero un nuovo calcolo dell'imposta alla fonte. Senza una domanda, presentata "
			"correttamente e nei termini, la deduzione dell'imposta alla fonte diviene definitiva."
		),
		"en": (
			"Persons liable to withholding tax may request, in writing and with the pertinent "
			"justification included, a ruling on the existence and extent of the withholding tax "
			"liability or a retrospective statutory assessment (recalculation of the withholding tax) "
			"by 31 March {year} from the responsible cantonal tax authority. Without such a request in "
			"due form and time, the withholding tax becomes definitive."
		),
	},
}

# Remarks the Wegleitung asks for without a standard wording (Rz 42, 63, 64; FAQ 2026 1.6, 9.2).
_REMARKS = {
	"replacement_in_box_1": {
		"fr": "Allocation pour perte de gain comprise dans le chiffre 1 : {label}, CHF {amount} ({months}).",
		"de": "In Ziffer 1 enthaltene Erwerbsersatzleistung: {label}, CHF {amount} ({months}).",
		"it": "Indennità per perdita di guadagno compresa nella cifra 1: {label}, CHF {amount} ({months}).",
		"en": "Income replacement benefit included in box 1: {label}, CHF {amount} ({months}).",
	},
	"benefit_days_by_insurer": {
		"fr": "Jours avec indemnités pour perte de gain non versées par l'employeur : {days}.",
		"de": "Tage mit nicht durch den Arbeitgeber ausbezahlten Erwerbsausfallentschädigungen: {days}.",
		"it": "Giorni con indennità per perdita di guadagno non versate dal datore di lavoro: {days}.",
		"en": "Days with income replacement benefits not paid by the employer: {days}.",
	},
	"withheld_ijm": {
		"fr": "Cotisations à l'assurance indemnités journalières maladie retenues : CHF {amount}.",
		"de": "Abgezogene Beiträge an die Krankentaggeldversicherung: CHF {amount}.",
		"it": "Contributi all'assicurazione d'indennità giornaliera in caso di malattia trattenuti: CHF {amount}.",
		"en": "Daily sickness allowance insurance contributions withheld: CHF {amount}.",
	},
	"withheld_laac": {
		"fr": "Primes d'assurance-accidents complémentaire retenues : CHF {amount}.",
		"de": "Abgezogene Prämien der UVG-Zusatzversicherung: CHF {amount}.",
		"it": "Premi dell'assicurazione complementare contro gli infortuni trattenuti: CHF {amount}.",
		"en": "Supplementary accident insurance premiums withheld: CHF {amount}.",
	},
	"withheld_other": {
		"fr": "Autres cotisations retenues ({label}) : CHF {amount}.",
		"de": "Weitere abgezogene Beiträge ({label}): CHF {amount}.",
		"it": "Altri contributi trattenuti ({label}): CHF {amount}.",
		"en": "Other contributions withheld ({label}): CHF {amount}.",
	},
	"family_allowances": {
		"fr": "Allocations familiales comprises dans le chiffre 1 : CHF {amount}.",
		"de": "In Ziffer 1 enthaltene Familienzulagen: CHF {amount}.",
		"it": "Assegni familiari compresi nella cifra 1: CHF {amount}.",
		"en": "Family allowances included in box 1: CHF {amount}.",
	},
}


def _code(row):
	code = str(row.get("ch_wage_type_code") or "").strip()
	return int(code) if code.isdigit() else None


def _in(code, bounds):
	return code is not None and bounds[0] <= code <= bounds[1]


def _premium_kind(row):
	"""'ijm' or 'laac' for a premium withheld that box 9 does not take, else None."""
	code = _code(row)
	name = (row.get("salary_component") or "").lower()
	if _in(code, _IJM_CODES) or "ijm" in name or "ktg" in name:
		return "ijm"
	if _in(code, _LAAC_CODES) or "laac" in name or "uvgz" in name:
		return "laac"
	return None


def _own_position(row):
	"""The component's position, else its wage type's in the catalogue; None when neither has one."""
	return (
		(row.get("ch_lohnausweis_position") or "").strip()
		or (row.get("wage_type_position") or "").strip()
		or None
	)


def to_francs(amount):
	"""Whole francs, rounded half away from zero (commercial rounding, never banker's)."""
	return float(Decimal(str(amount or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def certificate_positions(rows, overrides=None):
	"""Aggregate slip rows into certificate positions.

	Args:
		rows: dicts with salary_component, parentfield ("earnings"/"deductions"), amount,
			do_not_include_in_total, is_employer_contribution, ch_bases_only,
			ch_lohnausweis_position, wage_type_position, ch_wage_type_code, label (the name to
			print) and months (the "YYYY-MM" the row was paid in, comma separated).
		overrides: {component: position} from the configuration's mapping; a position of
			None leaves the component out.

	Returns:
		dict: totals {position: whole francs}, descriptions {position: [labels]}, withheld
		[{kind, label, amount}], family_allowances, replacement_in_box_1 [{label, amount,
		months}] and short_time_work_in_box_1.
	"""
	overrides = overrides or {}
	totals = defaultdict(float)
	descriptions = defaultdict(list)
	withheld = {}
	family_allowances = 0.0
	replacement = {}
	short_time_work_in_box_1 = False

	for row in rows:
		amount = float(row.get("amount") or 0)
		if not amount:
			continue
		component = row.get("salary_component")
		earning = row.get("parentfield") == "earnings"
		if component in overrides:
			position = overrides[component]
		else:
			position = _own_position(row)
		if position is None and component not in overrides and earning:
			position = "1"
		code = _code(row)

		if earning:
			if row.get("do_not_include_in_total") and not row.get("ch_bases_only"):
				continue  # a statistical row, not income
			if row.get("ch_bases_only") and not _own_position(row):
				continue  # raises the bases, is nobody's income (short-time work loss, 2065)
			if not position:
				continue
			if position not in TEXT_ONLY_POSITIONS:
				totals[position] += amount
			if position == "1" and _in(code, _FAMILY_ALLOWANCE_CODES):
				family_allowances += amount
			if position == "1" and code in _SHORT_TIME_WORK_CODES:
				short_time_work_in_box_1 = True
			if position == "1" and code in _REPLACEMENT_INCOME_CODES:
				label = row.get("label") or component
				entry = replacement.setdefault(label, {"label": label, "amount": 0.0, "months": set()})
				entry["amount"] += amount
				entry["months"].update(m for m in (row.get("months") or "").split(",") if m)
		else:
			if row.get("is_employer_contribution"):
				continue
			kind = _premium_kind(row)
			if kind and position in (None, "9"):
				_add_withheld(withheld, kind, row.get("label") or component, amount)
				continue
			if not position:
				continue
			if position == "9" and code is not None:
				if not any(_in(code, bounds) for bounds in _BOX_9_CODES):
					# A cantonal contribution (PC Famille, maternity insurance): FAQ 9.2, box 15.
					_add_withheld(withheld, "other", row.get("label") or component, amount)
					continue
			if position in TEXT_ONLY_POSITIONS:
				pass
			else:
				# A deduction booked to an income box takes back from it.
				totals[position] += -amount if position in INCOME_POSITIONS else amount

		if position in DESCRIBED_POSITIONS:
			label = row.get("label") or component
			if label and label not in descriptions[position]:
				descriptions[position].append(label)

	rounded = {position: to_francs(value) for position, value in totals.items()}
	return {
		"totals": {position: value for position, value in rounded.items() if value},
		"descriptions": dict(descriptions),
		"withheld": [
			{**entry, "amount": to_francs(entry["amount"])}
			for entry in withheld.values()
			if to_francs(entry["amount"])
		],
		"family_allowances": to_francs(family_allowances),
		"replacement_in_box_1": [
			{"label": e["label"], "amount": to_francs(e["amount"]), "months": sorted(e["months"])}
			for e in replacement.values()
			if to_francs(e["amount"])
		],
		"short_time_work_in_box_1": short_time_work_in_box_1,
	}


def _add_withheld(withheld, kind, label, amount):
	key = kind if kind in ("ijm", "laac") else f"other:{label}"
	entry = withheld.setdefault(key, {"kind": kind, "label": label, "amount": 0.0})
	entry["amount"] += amount


def certificate_totals(positions):
	"""Box 8 (gross) and box 11 (net) from whole-franc boxes: the printed form adds up."""
	gross = sum(to_francs(positions.get(p)) for p in INCOME_POSITIONS)
	net = gross - sum(to_francs(positions.get(p)) for p in ("9", "10.1", "10.2"))
	return gross, net


def employment_period(year_start, year_end, date_of_joining=None, relieving_date=None):
	"""Box E: the exact entry and exit dates within the year (Wegleitung Rz 8)."""
	start = max(date_of_joining, year_start) if date_of_joining else year_start
	end = min(relieving_date, year_end) if relieving_date else year_end
	return start, max(start, end)


def certificate_language(canton=None, fallback=None):
	"""The language of the tax administration of the employee's canton, else ``fallback``, else fr."""
	if canton:
		return _CANTON_LANGUAGES.get(str(canton).strip().upper(), "de")
	fallback = (fallback or "")[:2].lower()
	return fallback if fallback in LANGUAGES else "fr"


def format_chf(amount):
	"""1234.0 -> "1'234": whole francs with the Swiss thousands separator."""
	value = int(to_francs(amount))
	sign = "-" if value < 0 else ""
	return sign + f"{abs(value):,}".replace(",", "'")


def format_date(value):
	"""A date as the certificate prints it: 10.01.2027."""
	if isinstance(value, str):
		value = date.fromisoformat(value[:10])
	return value.strftime("%d.%m.%Y") if value else ""


def _format_rate(rate):
	rate = round(float(rate), 2)
	return str(int(rate)) if rate == int(rate) else str(rate).rstrip("0").rstrip(".")


def _month_ranges(months):
	"""["2027-05", "2027-06", "2027-08"] -> "05.2027-06.2027, 08.2027"."""
	indexes = sorted({int(m[:4]) * 12 + int(m[5:7]) - 1 for m in months if len(m) >= 7})
	runs = []
	for index in indexes:
		if runs and index == runs[-1][1] + 1:
			runs[-1][1] = index
		else:
			runs.append([index, index])

	def label(index):
		return f"{index % 12 + 1:02d}.{index // 12}"

	return ", ".join(label(a) if a == b else f"{label(a)}-{label(b)}" for a, b in runs)


def _text(table, key, language, **values):
	texts = table[key]
	return texts.get(language, texts["fr"]).format(**values)


def build_remarks(facts, language="fr"):
	"""Box 15, one remark per line, in the certificate's language.

	Args:
		facts: what the remarks are made of — rectificate {date, doc_id}, number_of_certificates,
			part_time_rate, expense_regulation {canton, date}, short_time_work_in_box_1,
			replacement_in_box_1, benefit_days_by_insurer, withheld, family_allowances,
			tax_at_source_year and additional_remarks (free text, kept as typed).
		language: fr, de, it or en.
	"""
	language = language if language in LANGUAGES else "fr"
	lines = []

	rectificate = facts.get("rectificate")
	if rectificate and rectificate.get("doc_id"):
		lines.append(
			_text(
				_STANDARD_REMARKS,
				"rectificate",
				language,
				date=format_date(rectificate.get("date")),
				doc_id=rectificate["doc_id"],
			)
		)
	count = int(facts.get("number_of_certificates") or 0)
	if count > 1:
		lines.append(_text(_STANDARD_REMARKS, "number_of_certificates", language, count=count))
	rate = facts.get("part_time_rate")
	if rate and 0 < float(rate) < 100:
		lines.append(_text(_STANDARD_REMARKS, "part_time", language, rate=_format_rate(rate)))
	regulation = facts.get("expense_regulation")
	if regulation and regulation.get("canton") and regulation.get("date"):
		lines.append(
			_text(
				_STANDARD_REMARKS,
				"expense_regulation",
				language,
				canton=regulation["canton"],
				date=format_date(regulation["date"]),
			)
		)
	if facts.get("short_time_work_in_box_1"):
		lines.append(_text(_STANDARD_REMARKS, "short_time_work_in_box_1", language))
	for entry in facts.get("replacement_in_box_1") or []:
		lines.append(
			_text(
				_REMARKS,
				"replacement_in_box_1",
				language,
				label=entry["label"],
				amount=format_chf(entry["amount"]),
				months=_month_ranges(entry.get("months") or []),
			)
		)
	days = int(facts.get("benefit_days_by_insurer") or 0)
	if days > 0:
		lines.append(_text(_REMARKS, "benefit_days_by_insurer", language, days=days))
	for entry in facts.get("withheld") or []:
		key = {"ijm": "withheld_ijm", "laac": "withheld_laac"}.get(entry["kind"], "withheld_other")
		lines.append(
			_text(_REMARKS, key, language, label=entry.get("label") or "", amount=format_chf(entry["amount"]))
		)
	if facts.get("family_allowances"):
		lines.append(
			_text(_REMARKS, "family_allowances", language, amount=format_chf(facts["family_allowances"]))
		)
	additional = (facts.get("additional_remarks") or "").strip()
	if additional:
		lines.append(additional)
	if facts.get("tax_at_source_year"):
		lines.append(_text(_STANDARD_REMARKS, "tax_at_source", language, year=facts["tax_at_source_year"]))
	return lines
