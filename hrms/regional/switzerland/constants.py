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

# Employee permit types
PERMIT_TYPES = [
	"",
	"Swiss Citizen",
	"Permit C (Settlement)",
	"Permit B (Residence)",
	"Permit G (Cross-border)",
	"Permit L (Short-term)",
]
