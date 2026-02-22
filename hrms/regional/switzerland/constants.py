# Swiss social insurance constants (2025 rates)
# Reference: Federal Social Insurance Office (OFAS/BSV)

# AVS/AI/APG (Old Age, Disability, Income Replacement)
AVS_RATE_EMPLOYEE = 0.053  # 5.3%
AVS_RATE_EMPLOYER = 0.053  # 5.3%

# AC/ALV (Unemployment Insurance)
AC_RATE_EMPLOYEE = 0.011  # 1.1%
AC_RATE_EMPLOYER = 0.011  # 1.1%
AC_ANNUAL_CEILING = 148_200  # CHF — no standard AC above this
AC_SOLIDARITY_RATE_EMPLOYEE = 0.005  # 0.5% on salary above ceiling
AC_SOLIDARITY_RATE_EMPLOYER = 0.005  # 0.5%

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
# (component_name: (config_field, is_employer_component))
RATE_BASED_COMPONENTS = {
	"AVS/AI/APG Employee": ("avs_rate_employee", False),
	"AVS/AI/APG Employer": ("avs_rate_employer", True),
	"LAA Professional Employer": ("laa_professional_rate", True),
	"LAA Non-Professional Employee": ("laa_nonprofessional_rate", False),
	"IJM/KTG Employee": ("ijm_rate_employee", False),
	"IJM/KTG Employer": ("ijm_rate_employer", True),
	"Family Allowances Employer": ("family_allowance_rate", True),
}

# Lohnausweis Form 11 — position to DocType field mapping
POSITION_FIELD_MAP = {
	"1": "position_1_salary",
	"2.1": "position_2_1_other_benefits",
	"2.2": "position_2_2_board_lodging",
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
	"13.1": "position_13_1_actual_expenses",
	"13.2": "position_13_2_flat_rate_car",
	"13.3": "position_13_3_other_flat_expenses",
	"14": "position_14_employer_contributions",
}

# Default mapping of Swiss salary components to Lohnausweis positions
DEFAULT_LOHNAUSWEIS_MAPPING = [
	{"salary_component": "Basic", "lohnausweis_position": "1"},
	{"salary_component": "13th Month Salary", "lohnausweis_position": "1"},
	{"salary_component": "AVS/AI/APG Employee", "lohnausweis_position": "9"},
	{"salary_component": "AC/ALV Employee", "lohnausweis_position": "9"},
	{"salary_component": "AC Solidarity Employee", "lohnausweis_position": "9"},
	{"salary_component": "LAA Non-Professional Employee", "lohnausweis_position": "9"},
	{"salary_component": "IJM/KTG Employee", "lohnausweis_position": "9"},
	{"salary_component": "LPP/BVG Employee", "lohnausweis_position": "10.1"},
	{"salary_component": "Source Tax Employee", "lohnausweis_position": "12"},
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
