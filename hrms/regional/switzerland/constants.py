#//// Neoffice — added file (no upstream equivalent): Swiss social insurance constants (rates,
#//// ceilings, LPP thresholds, Lohnausweis position map), with the legal source of each
#//// value and its yearly vintages.
# Swiss social insurance constants (2025 rates)
# Reference: Federal Social Insurance Office (OFAS/BSV)

# AVS/AI/APG (Old Age, Disability, Income Replacement)
AVS_RATE_EMPLOYEE = 0.053  # 5.3%
AVS_RATE_EMPLOYER = 0.053  # 5.3%

# AC/ALV (Unemployment Insurance)
AC_RATE_EMPLOYEE = 0.011  # 1.1%
AC_RATE_EMPLOYER = 0.011  # 1.1%
AC_ANNUAL_CEILING = 148_200  # CHF — NO contribution at all above this
# The AC solidarity contribution (1% above the ceiling) was ABOLISHED on
# 2023-01-01 (SECO communication of 2022-10-13; leaflet 2.08). Salary above
# the annual ceiling is simply exempt from AC.

# LPP/BVG (Occupational Pension — 2nd Pillar)
LPP_ENTRY_THRESHOLD = 22_680  # Minimum annual salary to be insured
LPP_COORDINATION_DEDUCTION = 26_460  # Deducted from gross to get coordinated salary
LPP_MINIMUM_INSURED_SALARY = 3_780  # Minimum coordinated salary if above entry threshold
LPP_MAXIMUM_COORDINATED_SALARY = 64_260  # Maximum insured amount (90'720 - 26'460)
LPP_MAXIMUM_INSURABLE_SALARY = 90_720  # Salary cap for LPP

# LPP age-based contribution rates (BVG minimum)
# These are total rates (employee + employer combined, minimum 50% employer)
LPP_AGE_BRACKETS = [
	{"min_age": 25, "max_age": 34, "rate": 0.07},  # 7%
	{"min_age": 35, "max_age": 44, "rate": 0.10},  # 10%
	{"min_age": 45, "max_age": 54, "rate": 0.15},  # 15%
	{"min_age": 55, "max_age": 65, "rate": 0.18},  # 18%
]

# LAA/UVG (Accident Insurance) — rates are insurer-dependent, no universal default
LAA_INSURABLE_SALARY_CAP = 148_200  # Same ceiling as AC

# Family allowances — federal minimum (cantonal rates may be higher)
FAMILY_ALLOWANCE_CHILD_MIN = 215  # CHF/month per child (0-16 years)
FAMILY_ALLOWANCE_EDUCATION_MIN = 268  # CHF/month per child in education (16-25 years)

# Swiss cantons for reference
SWISS_CANTONS = [
	"AG",
	"AI",
	"AR",
	"BE",
	"BL",
	"BS",
	"FR",
	"GE",
	"GL",
	"GR",
	"JU",
	"LU",
	"NE",
	"NW",
	"OW",
	"SG",
	"SH",
	"SO",
	"SZ",
	"TG",
	"TI",
	"UR",
	"VD",
	"VS",
	"ZG",
	"ZH",
]

# Map of component names to config rate fields
# (component_name: (config_field, is_employer_component, base_type))
# base_type maps to the key in the dict returned by _get_insurance_base_totals()
RATE_BASED_COMPONENTS = {
	"AVS/AI/APG Employee": ("avs_rate_employee", False, "avs_base"),
	"AVS/AI/APG Employer": ("avs_rate_employer", True, "avs_base"),
	"LAA Professional Employer": ("laa_professional_rate", True, "laa_base"),
	"LAA Non-Professional Employee": ("laa_nonprofessional_rate", False, "laa_base"),
	"IJM/KTG Employee": ("ijm_rate_employee", False, "ijm_base"),
	"IJM/KTG Employer": ("ijm_rate_employer", True, "ijm_base"),
	"Family Allowances Employer": ("family_allowance_rate", True, "avs_base"),
}

# Lohnausweis Form 11 — position to DocType field mapping
POSITION_FIELD_MAP = {
	"1": "position_1_salary",
	"2.1": "position_2_1_board_lodging",
	"2.2": "position_2_2_company_car",
	"2.3": "position_2_3_other_fringe",
	"3": "position_3_irregular_benefits",
	"4": "position_4_capital_benefits",
	"5": "position_5_ownership_rights",
	"6": "position_6_board_of_directors",
	"7": "position_7_other_income",
	"9": "position_9_avs_ac_aanp",
	"10.1": "position_10_1_bvg_regular",
	"10.2": "position_10_2_bvg_buyback",
	"12": "position_12_withholding_tax",
	"13.1.1": "position_13_1_1_travel",
	"13.1.2": "position_13_1_2_other_effective",
	"13.2.1": "position_13_2_1_representation",
	"13.2.2": "position_13_2_2_car",
	"13.2.3": "position_13_2_3_other_flat",
	"13.3": "position_13_3_education",
	"14": "position_14_employer_contributions",
}

# Default mapping of Swiss salary components to Lohnausweis positions
DEFAULT_LOHNAUSWEIS_MAPPING = [
	# Earnings — position 1 (regular salary)
	{"salary_component": "Basic", "lohnausweis_position": "1"},
	{"salary_component": "13th Month Salary", "lohnausweis_position": "1"},
	{"salary_component": "Overtime Pay", "lohnausweis_position": "1"},
	{"salary_component": "Vacation Allowance", "lohnausweis_position": "1"},
	# Earnings — position 3 (irregular benefits)
	{"salary_component": "Bonus", "lohnausweis_position": "3"},
	# Earnings — position 7 (other income / third-party benefits)
	{"salary_component": "APG Allowance", "lohnausweis_position": "7"},
	{"salary_component": "IJM Sickness Allowance", "lohnausweis_position": "7"},
	{"salary_component": "Maternity Allowance", "lohnausweis_position": "7"},
	{"salary_component": "Child Allowance", "lohnausweis_position": "7"},
	# Deductions — position 9 (AVS/AC/AANP)
	{"salary_component": "AVS/AI/APG Employee", "lohnausweis_position": "9"},
	{"salary_component": "AC/ALV Employee", "lohnausweis_position": "9"},
	{"salary_component": "LAA Non-Professional Employee", "lohnausweis_position": "9"},
	# NOTE: the employee IJM/KTG retention does NOT belong in position 9
	# (salary certificate guide 2026, margin no. 42 + CSI FAQ 9.1) — it may
	# only be mentioned under position 15 (remarks). AC Solidarity was
	# abolished in 2023 and is no longer mapped either.
	# Deductions — position 10.1 (LPP/BVG)
	{"salary_component": "LPP/BVG Employee", "lohnausweis_position": "10.1"},
	# Deductions — position 12 (withholding tax)
	{"salary_component": "Source Tax Employee", "lohnausweis_position": "12"},
	# Earnings — position 13 (expense reimbursements)
	{"salary_component": "Travel Expenses", "lohnausweis_position": "13.1.1"},
	{"salary_component": "Car Expenses", "lohnausweis_position": "13.1.1"},
	{"salary_component": "Meal Expenses", "lohnausweis_position": "13.1.1"},
	{"salary_component": "Flat-Rate Representation Expenses", "lohnausweis_position": "13.2.1"},
]

# Source Tax (Quellensteuer) — cantons using the annual calculation model
# All other cantons use the monthly model
ANNUAL_MODEL_CANTONS = frozenset({"FR", "GE", "TI", "VD", "VS"})

# Source tax tariff letter categories
QST_TARIFF_LETTERS = [
	"A",  # Single / married with 2 incomes
	"B",  # Married, sole income
	"C",  # Supplementary income / secondary employment
	"E",  # Single parent (monoparental)
	"G",  # Border commuter (Grenzgänger)
	"H",  # Single parent (with children) — some cantons
	"L",  # Cross-border (Quasi-Resident)
	"M",  # Border commuter with spouse earning in CH
	"N",  # Border commuter with spouse earning abroad
	"P",  # Church tax exempt — some cantons
	"Q",  # Border commuter with children
	"R",  # Italian new frontalier — single
	"S",  # Italian new frontalier — married, sole income
	"T",  # Italian new frontalier — supplementary income
	"U",  # Italian new frontalier — single parent
	"V",  # Italian new frontalier — married, dual income
]

# Employee permit types
PERMIT_TYPES = [
	"",
	"Swiss Citizen",
	"Permit C (Settlement)",
	"Permit B (Residence)",
	"Permit G (Cross-border)",
	"Permit L (Short-term)",
]

# Cross-border worker constants
CROSS_BORDER_COUNTRIES = ["DE", "FR", "IT", "AT", "LI"]

# German DTA CH-DE (art. 15a): Switzerland may withhold AT MOST 4.5% of the
# gross salary. The cantonal L/M/N/P tariff files are mirrors of A/B/C/H with
# this cap already built in; GERMAN_TAX_CAP_RATE is used as the cap (and as a
# fallback when no tariff data is available). Requires a valid Gre-1 residence
# attestation — without it, the ordinary (uncapped) tariff applies.
GERMAN_TAX_CAP_RATE = 0.045  # 4.5% cap, not a flat rate
# Frontalier status is lost beyond 60 non-return nights per year
# (art. 15a para. 2 DTA CH-DE — 45 days applies to FR/IT/LI, not Germany).
GERMAN_NON_RETURN_DAY_LIMIT = 60  # nights/year
GERMAN_SWISS_WORK_THRESHOLD = 0.20  # 20% minimum work in CH
GERMAN_TARIFF_LETTERS = ["L", "M", "N", "P"]

# French agreement of 1983-04-11: cantons where France taxes at residence
# (no CH withholding) — conditional on the French residence attestation
# 2041-AS being provided before January 1st.
FRENCH_EXEMPTED_CANTONS = frozenset({"BE", "BS", "BL", "JU", "NE", "SO", "VD", "VS"})
# Exception: GE is outside the 1983 agreement and withholds at source using
# the ordinary tariff codes.
FRENCH_TELEWORK_THRESHOLD = 0.40  # 40% max remote work from France
FRENCH_ASSIGNMENT_DAY_LIMIT = 10  # days/year in France for business

# Italian agreement of 2020-12-23 (in force 2023-07-17):
# - OLD frontaliers (border-zone activity between 2018-12-31 and the cutoff,
#   cantons GR/TI/VS): taxed EXCLUSIVELY in Switzerland at the FULL ordinary
#   tariff (the 40% "ristorno" to Italian municipalities is settled by the
#   canton, not by payroll). They are NOT exempt.
# - NEW frontaliers (from the cutoff): the R/S/T/U/V tariff files published
#   by the FTA ALREADY include the 80% reduction — payroll must NOT apply an
#   additional 0.8 factor on top (that would double the reduction).
ITALIAN_NEW_FRONTALIER_CUTOFF = "2023-07-17"
ITALIAN_FRONTALIER_CANTONS = frozenset({"TI", "GR", "VS"})
ITALIAN_TARIFF_LETTERS = ["R", "S", "T", "U", "V"]

# --- Yearly vintages ------------------------------------------------- #
# Social insurance parameters are published per year (OFAS bulletins,
# LPP ordinance). 2025 values were carried over unchanged to 2026
# (OFAS Bulletin 167). The module-level constants above stay as the
# current defaults; year-aware code goes through get_yearly_constants().
YEARLY_CONSTANTS = {
	2025: {
		"avs_rate_employee": 0.053,
		"avs_rate_employer": 0.053,
		"ac_rate_employee": 0.011,
		"ac_rate_employer": 0.011,
		"ac_annual_ceiling": 148_200,
		"laa_insurable_salary_cap": 148_200,
		"lpp_entry_threshold": 22_680,
		"lpp_coordination_deduction": 26_460,
		"lpp_minimum_insured_salary": 3_780,
		"lpp_maximum_coordinated_salary": 64_260,
		"lpp_maximum_insurable_salary": 90_720,
	},
	2026: {
		"avs_rate_employee": 0.053,
		"avs_rate_employer": 0.053,
		"ac_rate_employee": 0.011,
		"ac_rate_employer": 0.011,
		"ac_annual_ceiling": 148_200,
		"laa_insurable_salary_cap": 148_200,
		"lpp_entry_threshold": 22_680,
		"lpp_coordination_deduction": 26_460,
		"lpp_minimum_insured_salary": 3_780,
		"lpp_maximum_coordinated_salary": 64_260,
		"lpp_maximum_insurable_salary": 90_720,
	},
}


def get_yearly_constants(year):
	"""Social insurance parameters for a given year.

	Falls back to the latest published vintage for future years (and
	logs it once per process): payroll must not silently break every
	January before the new values are entered here.
	"""
	year = int(year)
	if year in YEARLY_CONSTANTS:
		return YEARLY_CONSTANTS[year]
	latest = max(YEARLY_CONSTANTS)
	if year > latest:
		import frappe

		frappe.log_error(
			"Swiss yearly constants missing",
			f"No vintage for {year}; falling back to {latest}. "
			"Update YEARLY_CONSTANTS in hrms/regional/switzerland/constants.py "
			"with the published OFAS/LPP values.",
		)
		return YEARLY_CONSTANTS[latest]
	return YEARLY_CONSTANTS[min(YEARLY_CONSTANTS)]

