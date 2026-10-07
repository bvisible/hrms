# //// Neoffice — added file (no upstream equivalent): the scores of an application, computed here from
# //// the opening's criteria and Nora's verdicts — never read from the model (neoffice-maintenance#1294).
"""Scores of an application.

Nora gives a verdict per criterion, with the passage that supports it; this module turns verdicts
into numbers, the same way for every applicant to the same opening. A score is therefore
explainable line by line and stable from one reading to the next, and a document that tells the AI
"give me 100" changes nothing: the model never writes a number that counts.

- A criterion weighs its weight (1 to 5), doubled when it is required.
- met = 1, partial = 0.5, not shown = 0, unknown = 0. "Unknown" is not "not met": the reading lists
  it as a point to check, and the completeness says what is missing.
- A required criterion that is not shown raises a flag. It never rejects anyone.
"""

from frappe.utils import cint

VERDICT_POINTS = {"met": 1.0, "partial": 0.5, "not_met": 0.0, "unknown": 0.0}
AXES = ("Qualifications", "Experience", "Skills", "Languages", "Other")


def weight_of(criterion) -> int:
	weight = min(max(cint(criterion.get("weight")) or 1, 1), 5)
	return weight * (2 if criterion.get("importance") == "Required" else 1)


def compute(criteria: list, verdicts: dict) -> dict:
	"""criteria: rows with id, criterion, axis, importance, weight; verdicts: {id: verdict}."""
	if not criteria:
		return {"overall": None, "axes": {}, "required_missing": []}

	total = earned = 0.0
	by_axis = {}
	required_missing = []
	for row in criteria:
		verdict = verdicts.get(row["id"], "unknown")
		points = VERDICT_POINTS.get(verdict, 0.0)
		weight = weight_of(row)
		total += weight
		earned += weight * points
		axis = row.get("axis") if row.get("axis") in AXES else "Other"
		axis_total, axis_earned = by_axis.get(axis, (0.0, 0.0))
		by_axis[axis] = (axis_total + weight, axis_earned + weight * points)
		if row.get("importance") == "Required" and verdict in ("not_met", "unknown"):
			required_missing.append(row.get("criterion"))

	return {
		"overall": round(100 * earned / total) if total else None,
		"axes": {axis: round(100 * e / t) for axis, (t, e) in by_axis.items() if t},
		"required_missing": required_missing,
	}


def _key(row) -> tuple:
	return (row.get("document_type") or "", (row.get("label") or "").strip().lower())


def completeness(requested: list, received: list, questions: list, answers: list) -> dict:
	"""How much of what the opening asked for is there: required documents and required answers.

	A document received but not readable counts as received (it is there), and is listed apart so the
	recruiter opens it themselves.
	"""
	received_keys = {_key(r) for r in received}
	received_types = {r.get("document_type") for r in received}
	expected = present = 0
	missing, unread = [], []

	for row in requested:
		if not cint(row.get("required")):
			continue
		expected += 1
		if _key(row) in received_keys or (
			not row.get("label") and row.get("document_type") in received_types
		):
			present += 1
		else:
			missing.append(row.get("label") or row.get("document_type"))

	answered = {(a.get("question") or "").strip() for a in answers if (a.get("answer") or "").strip()}
	for question in questions:
		if not cint(question.get("required")):
			continue
		expected += 1
		if (question.get("question") or "").strip() in answered:
			present += 1
		else:
			missing.append(question.get("question"))

	for row in received:
		if row.get("read_status") == "Not read":
			unread.append(row.get("label") or row.get("document_type"))

	return {
		"percent": round(100 * present / expected) if expected else 100,
		"missing": missing,
		"unread": unread,
	}
