import re

from frappe import _

from hrms.regional.switzerland.constants import SWISS_CANTONS


def validate_avs_number(number):
	"""Validate Swiss AVS/AHV number (format: 756.XXXX.XXXX.XX with EAN-13 check digit)."""
	if not number:
		return False, _("AVS number is required")

	# Remove dots and spaces
	clean = re.sub(r"[.\s]", "", str(number))

	if len(clean) != 13:
		return False, _("AVS number must be 13 digits (756.XXXX.XXXX.XX)")

	if not clean.startswith("756"):
		return False, _("AVS number must start with 756")

	if not clean.isdigit():
		return False, _("AVS number must contain only digits")

	# EAN-13 check digit validation
	total = 0
	for i, digit in enumerate(clean[:12]):
		weight = 1 if i % 2 == 0 else 3
		total += int(digit) * weight
	expected_check = (10 - (total % 10)) % 10

	if int(clean[12]) != expected_check:
		return False, _("Invalid AVS check digit")

	return True, None


def format_avs_number(number):
	"""Format AVS number to standard format: 756.XXXX.XXXX.XX."""
	clean = re.sub(r"[.\s]", "", str(number))
	if len(clean) == 13:
		return f"{clean[:3]}.{clean[3:7]}.{clean[7:11]}.{clean[11:13]}"
	return number


def validate_uid_bfs(uid):
	"""Validate Swiss UID-BFS (format: CHE-XXX.XXX.XXX)."""
	if not uid:
		return False, _("UID-BFS is required")

	# Accept with or without dots/dashes
	clean = re.sub(r"[-.\s]", "", str(uid).upper())

	if not clean.startswith("CHE"):
		return False, _("UID-BFS must start with CHE")

	digits = clean[3:]
	if len(digits) != 9 or not digits.isdigit():
		return False, _("UID-BFS must have 9 digits after CHE")

	return True, None


def format_uid_bfs(uid):
	"""Format UID-BFS to standard format: CHE-XXX.XXX.XXX."""
	clean = re.sub(r"[-.\s]", "", str(uid).upper())
	if len(clean) == 12 and clean.startswith("CHE"):
		digits = clean[3:]
		return f"CHE-{digits[:3]}.{digits[3:6]}.{digits[6:9]}"
	return uid


def validate_canton(canton):
	"""Validate Swiss canton code."""
	if not canton:
		return False, _("Canton is required")
	canton = str(canton).upper().strip()
	if canton not in SWISS_CANTONS:
		return False, _("Invalid canton code: {0}").format(canton)
	return True, None


def validate_rate(value, field_label, min_val=0, max_val=100):
	"""Validate a percentage rate."""
	try:
		rate = float(value)
	except (ValueError, TypeError):
		return False, _("{0} must be a number").format(field_label)

	if rate < min_val or rate > max_val:
		return False, _("{0} must be between {1} and {2}").format(field_label, min_val, max_val)

	return True, None


def validate_employee_coherence(data):
	"""Validate employee data coherence (permit, QST, cross-border rules)."""
	errors = []
	permit = data.get("ch_permit_type", "")

	# Cross-border workers (permit G) must have QST
	if permit == "G":
		if not data.get("ch_qst_subject"):
			errors.append(_("Cross-border workers (permit G) are always subject to source tax (QST)"))
		if not data.get("ch_is_cross_border"):
			errors.append(_("Cross-border workers (permit G) must be flagged as cross-border"))
		if not data.get("ch_residence_country"):
			errors.append(_("Residence country is required for cross-border workers"))

	# Foreign workers with permits B, L, F are typically subject to QST
	if permit in ("B", "L", "F") and not data.get("ch_qst_subject"):
		errors.append(
			_("Foreign workers with permit {0} are typically subject to source tax (QST)").format(permit)
		)

	# QST-specific validations
	if data.get("ch_qst_subject"):
		if not data.get("ch_qst_tariff_letter"):
			errors.append(_("QST tariff letter is required for source-taxed employees"))
		if not data.get("ch_qst_taxation_canton"):
			errors.append(_("QST taxation canton is required"))

	return errors


def get_lpp_rate_for_age(age):
	"""Get the LPP minimum contribution rate for a given age."""
	from hrms.regional.switzerland.constants import LPP_AGE_BRACKETS

	for bracket in LPP_AGE_BRACKETS:
		if bracket["min_age"] <= age <= bracket["max_age"]:
			return bracket["rate"]
	return 0
