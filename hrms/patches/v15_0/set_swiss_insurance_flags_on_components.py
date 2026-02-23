import frappe


def execute():
	"""Set Swiss social insurance base flags on existing Salary Components.

	For existing installations upgrading to the wage type catalog, this patch:
	1. Links existing Swiss salary components to their Swiss Wage Type codes
	2. Sets ch_subject_to_* flags so the per-base payroll hook works correctly
	3. Sets ch_lohnausweis_position for Lohnausweis certificate generation
	"""
	if not frappe.db.has_column("Salary Component", "ch_subject_to_avs"):
		return

	# Map component names to their Swiss wage type code + insurance flags
	# Earnings get their real flags; deductions get all flags = 0
	component_flags = {
		# Earnings — subject to social charges per Swiss law
		"Basic": {
			"wt": "1000",
			"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 1, "imp": 1,
			"cert": "1",
		},
		"13th Month Salary": {
			"wt": "1181",
			"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 1, "imp": 1,
			"cert": "1",
		},
		# Deductions — social charges themselves, not a salary base
		"AVS/AI/APG Employee": {
			"wt": "5010",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"AVS/AI/APG Employer": {
			"wt": "5010",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"AC/ALV Employee": {
			"wt": "5020",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"AC/ALV Employer": {
			"wt": "5020",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"AC Solidarity Employee": {
			"wt": "5022",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"AC Solidarity Employer": {
			"wt": "5022",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"LAA Professional Employer": {
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"LAA Non-Professional Employee": {
			"wt": "5031",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"LPP/BVG Employee": {
			"wt": "5054",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "10.1",
		},
		"LPP/BVG Employer": {
			"wt": "5054",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "10.1",
		},
		"IJM/KTG Employee": {
			"wt": "5050",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"IJM/KTG Employer": {
			"wt": "5050",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "9",
		},
		"Family Allowances Employer": {
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
		},
		"Source Tax Employee": {
			"wt": "5060",
			"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0,
			"cert": "12",
		},
	}

	for comp_name, flags in component_flags.items():
		if not frappe.db.exists("Salary Component", comp_name):
			continue

		updates = {
			"ch_subject_to_avs": flags["avs"],
			"ch_subject_to_ac": flags["ac"],
			"ch_subject_to_laa": flags["laa"],
			"ch_subject_to_ijm": flags["ijm"],
			"ch_subject_to_lpp": flags["lpp"],
			"ch_subject_to_imp": flags["imp"],
		}

		wt_code = flags.get("wt")
		if wt_code:
			wt_name = f"CH-WT-{wt_code}"
			if frappe.db.exists("Swiss Wage Type", wt_name):
				updates["ch_wage_type"] = wt_name
				updates["ch_wage_type_code"] = wt_code

		cert = flags.get("cert")
		if cert:
			updates["ch_lohnausweis_position"] = cert

		frappe.db.set_value("Salary Component", comp_name, updates, update_modified=False)

	frappe.db.commit()
