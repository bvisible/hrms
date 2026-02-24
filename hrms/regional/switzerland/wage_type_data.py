# Swiss standard wage type catalog (rubriques de salaire)
# Reference: Daniel Moret Informatique Service, 08.05.2024
# Based on Swissdec standard wage type definitions

# Common flag patterns for social insurance bases
_ALL = {"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 1, "imp": 1}
_NO_LPP = {"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 0, "imp": 1}
_AVS_AC = {"avs": 1, "ac": 1, "laa": 0, "ijm": 0, "lpp": 0, "imp": 1}
_AVS_AC_LAA_IJM = {"avs": 1, "ac": 1, "laa": 1, "ijm": 1, "lpp": 0, "imp": 1}
_AVS_AC_LAA = {"avs": 1, "ac": 1, "laa": 1, "ijm": 0, "lpp": 0, "imp": 1}
_AVS_AC_LAA_LPP = {"avs": 1, "ac": 1, "laa": 1, "ijm": 0, "lpp": 1, "imp": 0}
_IMP_ONLY = {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 1}
_EXEMPT = {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0}
_DEDUCTION = {"avs": 0, "ac": 0, "laa": 0, "ijm": 0, "lpp": 0, "imp": 0}


def _wt(
	code, name, typ, cert, flags, vac=0, stat="", common=0,
	abbr="", desc_fr="", employer=0, linked="", formula="", condition="",
	amount=0, formula_based=0, no_total=0, payment_days=1,
):
	"""Build a wage type dict entry.

	Args:
		code: Numeric wage type code.
		name: Wage type name (French).
		typ: "Earning", "Deduction", or "Informational".
		cert: Lohnausweis certificate position.
		flags: Social insurance base flags dict.
		vac: Included in vacation base.
		stat: Statistical category code.
		common: Commonly used flag.
		abbr: Salary Component abbreviation template.
		desc_fr: French description for the Salary Component.
		employer: Is employer contribution flag.
		linked: Linked wage type code (paired employee/employer).
		formula: Formula expression for automatic calculation.
		condition: Condition expression.
		amount: Default fixed amount.
		formula_based: Amount based on formula flag.
		no_total: Do not include in total (net pay) flag.
		payment_days: Depends on payment days flag.
	"""
	entry = {
		"code": str(code),
		"wage_type_name": name,
		"type": typ,
		"lohnausweis_position": cert,
		"subject_to_avs": flags["avs"],
		"subject_to_ac": flags["ac"],
		"subject_to_laa": flags["laa"],
		"subject_to_ijm": flags["ijm"],
		"subject_to_lpp": flags["lpp"],
		"subject_to_imp": flags["imp"],
		"included_in_vacation_base": vac,
		"statistical_category": stat,
		"is_standard": 1,
		"is_common": common,
	}
	# Template fields (only set if provided)
	if abbr:
		entry["abbreviation"] = abbr
	if desc_fr:
		entry["description_fr"] = desc_fr
	if employer:
		entry["is_employer_contribution"] = 1
		entry["do_not_include_in_total"] = 1
	if linked:
		entry["linked_wage_type_code"] = str(linked)
	if formula:
		entry["formula"] = formula
		entry["amount_based_on_formula"] = 1
	if condition:
		entry["condition"] = condition
	if amount:
		entry["default_amount"] = amount
	if formula_based:
		entry["amount_based_on_formula"] = 1
	if no_total:
		entry["do_not_include_in_total"] = 1
	if not payment_days:
		entry["depends_on_payment_days"] = 0
	else:
		entry["depends_on_payment_days"] = 1
	return entry


def get_swiss_wage_types():
	"""Return all standard Swiss wage type definitions (~170 entries).

	Each entry contains the social insurance base flags, Lohnausweis position,
	and statistical category as defined by the Swissdec standard reference.
	"""
	return [
		# =====================================================================
		# 1000-1056: Base salaries and regular indemnities
		# =====================================================================
		_wt(1000, "Salaire mensuel", "Earning", "1", _ALL, vac=1, stat="BS", common=1),
		_wt(1005, "Salaire horaire", "Earning", "1", _ALL, vac=1, stat="BS", common=1),
		_wt(1006, "Salaire à la leçon", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1007, "Salaire hebdomadaire", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1010, "Honoraires", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1015, "Salaire d'auxiliaire", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1016, "Salaire pour travail à domicile", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1017, "Salaire pour nettoyage", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1018, "Salaire à la tâche", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1020, "Indemnité pour absence", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1021, "Membres autorités et commissions", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1030, "Indemnité pour ancienneté de service", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1031, "Indemnité de fonction", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1032, "Indemnité pour remplacement", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1033, "Indemnité de résidence", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1034, "Allocation de renchérissement", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1040, "Allocations familiale de vie chère", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1050, "Indemnité de logement", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1055, "Indemnité de déplacement", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1056, "Indemnité de mutation", "Earning", "1", _ALL, vac=1, stat="BS"),
		# =====================================================================
		# 1060-1076: Overtime and shift/night work
		# =====================================================================
		_wt(
			1060, "Travail supplémentaire", "Earning", "1", _ALL, vac=1, stat="HS", common=1,
			abbr="OTP", desc_fr="Heures supplémentaires",
		),
		_wt(1061, "Heures supplémentaires à 125%", "Earning", "1", _ALL, vac=1, stat="HS"),
		_wt(1065, "Heures supplémentaires", "Earning", "1", _ALL, vac=1, stat="HS", common=1),
		_wt(1070, "Indemnité travail par équipes", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1071, "Indemnité pour service de piquet", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1072, "Indemnité d'engagement", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1073, "Indemnité pour travail dominical", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1074, "Indemnité pour inconvénients", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1075, "Indemnité pour service de nuit", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1076, "Indemnité pour travail de nuit", "Earning", "1", _ALL, vac=1, stat="IND"),
		# =====================================================================
		# 1100-1112: Construction/mining indemnities and advance primes
		# =====================================================================
		_wt(1100, "Indemnités inconvénients du chantier", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1101, "Indemnité pour travail pénible", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1102, "Indemnité pour travail salissant", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1103, "Indemnité pour poussière", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1104, "Indemnité pour travaux souterrains", "Earning", "1", _ALL, vac=1, stat="IND"),
		_wt(1110, "Avancement", "Earning", "3", _ALL, vac=1, stat="IND"),
		_wt(1111, "Prime pour percement", "Earning", "3", _ALL, vac=1, stat="IND"),
		_wt(1112, "Prime pour ténacité", "Earning", "3", _ALL, vac=1, stat="IND"),
		# =====================================================================
		# 1130-1131: Engagement primes
		# =====================================================================
		_wt(1130, "Prime d'engagement", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1131, "Indemnité de non-engagement", "Earning", "3", _ALL, vac=1, stat="VU"),
		# =====================================================================
		# 1160-1165: Vacation pay
		# =====================================================================
		_wt(
			1160, "Indemnité de vacances", "Earning", "1", _ALL, vac=1, stat="BS", common=1,
			abbr="VACA", desc_fr="Indemnité de vacances",
		),
		_wt(1161, "Indemnité pour jours fériés", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1162, "Vacances payées %", "Earning", "1", _ALL, vac=0, stat="HS"),
		_wt(1163, "Vacances payées", "Earning", "1", _ALL, vac=0, stat="HS"),
		_wt(1164, "Vacances calculées", "Earning", "1", _ALL, vac=0, stat="HS"),
		_wt(1165, "Paiement vacances", "Earning", "1", _EXEMPT, vac=0, stat="HS"),
		# =====================================================================
		# 1180-1182: 13th month salary
		# =====================================================================
		_wt(1180, "13e salaire payé %", "Earning", "1", _ALL, vac=0, stat="SMS", common=1),
		_wt(
			1181, "13e salaire payé", "Earning", "1", _ALL, vac=0, stat="SMS", common=1,
			abbr="13M", desc_fr="Treizième salaire — Calculé automatiquement par le module suisse",
			payment_days=0,
		),
		_wt(1182, "13e salaire calculé", "Earning", "1", _ALL, vac=0, stat="SMS"),
		# =====================================================================
		# 1201-1250: Gratifications, bonuses, primes
		# =====================================================================
		_wt(1201, "Gratification", "Earning", "3", _ALL, vac=1, stat="VU", common=1),
		_wt(1202, "Gratification de Noël", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(
			1210, "Bonus", "Earning", "3", _ALL, vac=1, stat="VU", common=1,
			abbr="BONUS", desc_fr="Bonus / Gratification", payment_days=0,
		),
		_wt(1211, "Participation aux bénéfices", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1212, "Allocation spéciale", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1213, "Prime de succès", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1214, "Prime de rendement", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1215, "Prime de reconnaissance", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1216, "Prime pour propositions d'amélioration", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1217, "Prime sur chiffre d'affaires", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1218, "Commission", "Earning", "1", _ALL, vac=1, stat="BS", common=1),
		_wt(1219, "Prime de présence", "Earning", "1", _ALL, vac=1, stat="BS"),
		_wt(1230, "Cadeau pour ancienneté de service", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1231, "Cadeau de jubilé", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1232, "Prime de fidélité", "Earning", "3", _ALL, vac=1, stat="VU"),
		_wt(1250, "Prime pour prévention de dommages", "Earning", "3", _ALL, vac=1, stat="VU"),
		# =====================================================================
		# 1300-1303: Salary during absence (accident, illness, military, training)
		# =====================================================================
		_wt(1300, "Salaire en cas d'accident", "Earning", "1", _ALL, vac=1, stat="BS", common=1),
		_wt(1301, "Salaire en cas de maladie", "Earning", "1", _ALL, vac=1, stat="BS", common=1),
		_wt(
			1302,
			"Salaire service militaire, protection civile",
			"Earning",
			"1",
			_ALL,
			vac=1,
			stat="BS",
		),
		_wt(
			1303,
			"Salaire formation et perfectionnement",
			"Earning",
			"1",
			_ALL,
			vac=1,
			stat="BS",
		),
		# =====================================================================
		# 1310-1340: Informational (hours tracking, no monetary value)
		# =====================================================================
		_wt(1310, "Nombre d'heures travaillées", "Informational", "", _EXEMPT, stat="HRE"),
		_wt(1315, "Nombre d'heures fériées", "Informational", "", _EXEMPT, stat="HRE"),
		_wt(1316, "Nombre d'heures d'absences payées", "Informational", "", _EXEMPT, stat="HRE"),
		_wt(1320, "Nombre d'heures d'absences non payées", "Informational", "", _EXEMPT, stat="HRE"),
		_wt(1330, "Nombre de leçons", "Informational", "", _EXEMPT, stat="LEC"),
		_wt(1340, "Nombre de leçons annulées payées", "Informational", "", _EXEMPT, stat="LEC"),
		# =====================================================================
		# 1400-1420: Departure indemnities and capital benefits
		# =====================================================================
		_wt(1400, "Indemnité de départ (prévoyance)", "Earning", "4", _IMP_ONLY, stat="CMO"),
		_wt(1401, "Indemnité de départ (soumis AVS)", "Earning", "3", _AVS_AC, stat="CMO"),
		_wt(
			1410,
			"Prestation en capital caract. de prévoyance",
			"Earning",
			"4",
			_IMP_ONLY,
			stat="PS",
		),
		_wt(1411, "Prestation en capital (soumis AVS)", "Earning", "3", _ALL, stat="PS"),
		_wt(1420, "Versement salaire après décès", "Earning", "4", _IMP_ONLY, stat="PS"),
		# =====================================================================
		# 1500-1510: Board of directors compensation
		# =====================================================================
		_wt(1500, "Honoraire CA", "Earning", "6", _ALL, stat=""),
		_wt(1501, "Indemnité CA", "Earning", "6", _ALL, stat=""),
		_wt(1503, "Jetons de présence CS", "Earning", "6", _ALL, stat="VU"),
		_wt(1510, "Tantièmes CA", "Earning", "6", _ALL, stat="VU"),
		# =====================================================================
		# 1900-1962: Benefits in kind and participation rights
		# =====================================================================
		_wt(1900, "Repas gratuits", "Earning", "2.1", _ALL, vac=1, stat="BS"),
		_wt(1901, "Chambre gratuite", "Earning", "2.1", _ALL, vac=1, stat="BS"),
		_wt(1902, "Logement gratuit", "Earning", "2.3", _ALL, vac=1, stat="BS"),
		_wt(1910, "Part privée voiture de service", "Earning", "2.2", _ALL, vac=1, stat="BS"),
		_wt(
			1920,
			"Pourboire soumis aux cotisations AVS",
			"Earning",
			"1",
			_ALL,
			vac=1,
			stat="BS",
		),
		_wt(1950, "Réduction loyer logement locatif", "Earning", "2.3", _ALL, vac=1, stat="BS"),
		_wt(
			1951,
			"Indemnité pour le trajet domicile/lieu de travail",
			"Earning",
			"2.3",
			_ALL,
			stat="",
		),
		_wt(1953, "Prestations en nature expatriés", "Earning", "2.3", _ALL, vac=1, stat="BS"),
		_wt(1955, "Avantage en argent", "Earning", "2.3", _ALL, vac=1, stat="BS"),
		_wt(1960, "Droits de participation imposables", "Earning", "5", _ALL, stat="PS"),
		_wt(1961, "Actions de collaborateurs", "Earning", "5", _ALL, stat="PS"),
		_wt(1962, "Options de collaborateurs", "Earning", "5", _ALL, stat="PS"),
		# =====================================================================
		# 1971-1978: Employer voluntary contributions (shown on cert.sal)
		# =====================================================================
		_wt(1971, "Part facultative employeur IJM", "Earning", "7", _IMP_ONLY, stat="PS"),
		_wt(1972, "Part facultative employeur LPP", "Earning", "7", _ALL, stat="PS"),
		_wt(1973, "Part facultative employeur LPP rachat", "Earning", "7", _ALL, stat="PS"),
		_wt(1974, "Part facultative employeur CM", "Earning", "7", _IMP_ONLY, stat="PS"),
		_wt(
			1975,
			"Part facultative employeur complém. LAA",
			"Earning",
			"7",
			_IMP_ONLY,
			stat="PS",
		),
		_wt(1976, "3ème pilier A payé par l'employeur", "Earning", "7", _ALL, stat="PS"),
		_wt(1977, "3ème pilier B payé par l'employeur", "Earning", "7", _ALL, stat="PS"),
		_wt(
			1978,
			"Impôt à la source payé par employeur",
			"Earning",
			"7",
			_ALL,
			stat="PS",
		),
		# =====================================================================
		# 1980: Training (certificate of salary only)
		# =====================================================================
		_wt(
			1980,
			"Perfectionnement (certificat de salaire)",
			"Earning",
			"13.2.3",
			_EXEMPT,
			stat="",
		),
		# =====================================================================
		# 2000-2075: Third-party benefits (APG, military, insurance, maternity)
		# =====================================================================
		_wt(
			2000, "Indemnité APG", "Earning", "7", _AVS_AC, stat="PRT", common=1,
			abbr="CHAP", desc_fr="Indemnité APG (allocation perte de gain)", payment_days=0,
		),
		_wt(
			2005,
			"Prestation compensation militaire (CCM)",
			"Earning",
			"7",
			_AVS_AC_LAA_IJM,
			stat="PRT",
		),
		_wt(2010, "Caisse militaire subsidiaire", "Earning", "7", _AVS_AC_LAA_IJM, stat="PRT"),
		_wt(2015, "Parifonds", "Earning", "7", _AVS_AC_LAA_IJM, stat="PRT"),
		_wt(2020, "Indemnité assurance militaire", "Earning", "7", _IMP_ONLY, stat="PRT"),
		_wt(2021, "Rente assurance militaire", "Earning", "7", _IMP_ONLY, stat="PRT"),
		_wt(2025, "Indemnité AI", "Earning", "7", _AVS_AC, stat="PRT"),
		_wt(2026, "Rente AI", "Earning", "7", _IMP_ONLY, stat="PRT"),
		_wt(2030, "Indemnité accident", "Earning", "7", _IMP_ONLY, stat="PRT"),
		_wt(2031, "Rente accident", "Earning", "7", _IMP_ONLY, stat="PRT"),
		_wt(
			2035, "Indemnité maladie", "Earning", "7", _IMP_ONLY, stat="PRT", common=1,
			abbr="IIJM", desc_fr="Indemnité journalière maladie IJM", payment_days=0,
		),
		_wt(
			2040, "Indemnité maternité", "Earning", "7", _AVS_AC, stat="PRT", common=1,
			abbr="MATA", desc_fr="Allocation de maternité", payment_days=0,
		),
		_wt(2050, "Correction indemnité de tiers", "Deduction", "", _AVS_AC_LAA, stat=""),
		_wt(2051, "Correction de salaire net", "Deduction", "", _IMP_ONLY, stat=""),
		_wt(2060, "Déduction RHT/ITP (SM)", "Deduction", "", _IMP_ONLY, stat=""),
		_wt(2065, "Perte de gain RHT/ITP (SH)", "Earning", "", _AVS_AC_LAA_LPP, stat=""),
		_wt(2070, "Indemnité de chômage", "Earning", "7", _IMP_ONLY, stat=""),
		_wt(2075, "Délai de carence RHT/ITP", "Earning", "", _IMP_ONLY, stat=""),
		# =====================================================================
		# 3000-3034: Family allowances (not subject to social charges)
		# =====================================================================
		_wt(
			3000, "Allocation pour enfant", "Earning", "7", _IMP_ONLY, stat="CMO", common=1,
			abbr="CHALL", desc_fr="Allocation pour enfant", payment_days=0,
		),
		_wt(
			3010,
			"Allocation de formation professionnelle",
			"Earning",
			"7",
			_IMP_ONLY,
			stat="CMO",
			common=1,
		),
		_wt(3030, "Allocation familiale", "Earning", "7", _IMP_ONLY, stat="CMO"),
		_wt(3031, "Allocation de ménage", "Earning", "7", _IMP_ONLY, stat="CMO"),
		_wt(3032, "Allocation de naissance", "Earning", "3", _IMP_ONLY, stat="CMO", common=1),
		_wt(3033, "Allocation de mariage", "Earning", "3", _IMP_ONLY, stat="CMO"),
		_wt(3034, "Allocation pour charge d'assistance", "Earning", "7", _IMP_ONLY, stat="CMO"),
		# =====================================================================
		# 5010-5027: AVS/AC/Family contributions (social deductions)
		# =====================================================================
		_wt(
			5010, "Cotisation AVS employé", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="AVS_EE", linked="5011",
			desc_fr="AVS/AI/APG — Part employé (5.3%)",
			formula="base * 0.053", formula_based=1,
		),
		_wt(
			5011, "Cotisation AVS employeur", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="AVS_ER", linked="5010", employer=1,
			desc_fr="AVS/AI/APG — Part employeur (5.3%)",
			formula="base * 0.053", formula_based=1,
		),
		_wt(
			5020, "Cotisation AC employé", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="AC_EE", linked="5021",
			desc_fr="Assurance chômage — Part employé (1.1%, plafond CHF 148'200/an géré automatiquement)",
			formula="base * 0.011", formula_based=1,
		),
		_wt(
			5021, "Cotisation AC employeur", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="AC_ER", linked="5020", employer=1,
			desc_fr="Assurance chômage — Part employeur (1.1%, plafond CHF 148'200/an géré automatiquement)",
			formula="base * 0.011", formula_based=1,
		),
		_wt(
			5022, "Cotisation AC solidarité employé", "Deduction", "9", _DEDUCTION,
			stat="CS", abbr="ACSOL_EE", linked="5023",
			desc_fr="AC Solidarité — Part employé (0.5%, uniquement au-dessus du plafond CHF 148'200/an)",
			formula="base * 0.005", formula_based=1, condition="0",
		),
		_wt(
			5023, "Cotisation AC solidarité employeur", "Deduction", "9", _DEDUCTION,
			stat="CS", abbr="ACSOL_ER", linked="5022", employer=1,
			desc_fr="AC Solidarité — Part employeur (0.5%, uniquement au-dessus du plafond CHF 148'200/an)",
			formula="base * 0.005", formula_based=1, condition="0",
		),
		_wt(
			5024, "Cotisation allocations familiales employeur", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="FALLOC_ER", employer=1,
			desc_fr="Allocations familiales — Part employeur (taux cantonal)",
		),
		_wt(5025, "Cotisation PC Famille", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5026, "Cotisation Assurance Maternité", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5027, "Participation cotisation familiale", "Deduction", "9", _DEDUCTION, stat="CS"),
		# =====================================================================
		# 5031-5042: LAA non-professional (AANP) by sector
		# =====================================================================
		_wt(
			5030, "Cotisation AAP employeur", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="LAAP_ER", employer=1,
			desc_fr="LAA Professionnel — Part employeur (taux fixé par l'assureur)",
		),
		_wt(
			5031, "Cotisation AANP employé", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="LAANP_EE",
			desc_fr="LAA Non-professionnel — Part employé (taux fixé par l'assureur)",
		),
		_wt(5032, "Cotisation AANP secteur A1", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5033, "Cotisation AANP secteur A2", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5034, "Cotisation AANP secteur A3", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5035, "Cotisation AANP secteur B0", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5036, "Cotisation AANP secteur B1", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5037, "Cotisation AANP secteur B2", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5038, "Cotisation AANP secteur B3", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5039, "Cotisation AANP secteur Z0", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5040, "Cotisation AANP secteur Z1", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5041, "Cotisation AANP secteur Z2", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5042, "Cotisation AANP secteur Z3", "Deduction", "9", _DEDUCTION, stat="CS"),
		# =====================================================================
		# 5046-5048: Supplementary LAA (LAAC) by category
		# =====================================================================
		_wt(5046, "Cotisation LAAC catégorie 0", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5047, "Cotisation LAAC catégorie 1", "Deduction", "9", _DEDUCTION, stat="CS"),
		_wt(5048, "Cotisation LAAC catégorie 2", "Deduction", "9", _DEDUCTION, stat="CS"),
		# =====================================================================
		# 5050-5052: IJM (daily sickness allowance) by category
		# =====================================================================
		_wt(
			5050, "Cotisation IJM employé", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="IJM_EE", linked="5051",
			desc_fr="IJM/KTG Indemnité journalière maladie — Part employé (taux fixé par l'assureur)",
		),
		_wt(
			5051, "Cotisation IJM employeur", "Deduction", "9", _DEDUCTION,
			stat="CS", common=1, abbr="IJM_ER", linked="5050", employer=1,
			desc_fr="IJM/KTG Indemnité journalière maladie — Part employeur (taux fixé par l'assureur)",
		),
		_wt(5052, "Cotisation IJM catégorie 2", "Deduction", "9", _DEDUCTION, stat="CS"),
		# =====================================================================
		# 5054-5056: LPP (occupational pension)
		# =====================================================================
		_wt(
			5054, "Cotisation LPP employé", "Deduction", "10.1", _DEDUCTION,
			stat="CS", common=1, abbr="LPP_EE", linked="5055",
			desc_fr="LPP/BVG Prévoyance professionnelle — Part employé (taux selon âge)",
		),
		_wt(
			5055, "Cotisation LPP employeur", "Deduction", "10.1", _DEDUCTION,
			stat="CS", common=1, abbr="LPP_ER", linked="5054", employer=1,
			desc_fr="LPP/BVG Prévoyance professionnelle — Part employeur (min. 50%, taux selon âge)",
		),
		_wt(
			5056, "Cotisations rachat LPP", "Deduction", "10.2", _DEDUCTION,
			stat="CS", desc_fr="Rachat LPP (prévoyance professionnelle)",
		),
		# =====================================================================
		# 5060-5062: Source tax (withholding tax)
		# =====================================================================
		_wt(
			5060, "Retenue impôt à la source", "Deduction", "12", _DEDUCTION,
			stat="", common=1, abbr="QST",
			desc_fr="Impôt à la source (Quellensteuer) — Calculé automatiquement depuis les barèmes ESTV",
		),
		_wt(5061, "Correction impôt à la source", "Deduction", "12", _DEDUCTION, stat=""),
		_wt(5062, "Retenue impôt ecclésiastique GE", "Deduction", "12", _DEDUCTION, stat=""),
		# =====================================================================
		# 5080-5112: Corrections and compensations
		# =====================================================================
		_wt(
			5080,
			"Retenue part privée voiture de service",
			"Deduction",
			"",
			_DEDUCTION,
			stat="",
		),
		_wt(5100, "Correction prestations en nature", "Deduction", "", _DEDUCTION, stat=""),
		_wt(5110, "Correction avantage en argent", "Deduction", "", _DEDUCTION, stat=""),
		_wt(5111, "Compensation cotis. LPP employeur", "Deduction", "", _DEDUCTION, stat=""),
		_wt(5112, "Compensation rachat LPP employeur", "Deduction", "", _DEDUCTION, stat=""),
		# =====================================================================
		# 6000-6070: Expense reimbursements (not subject to social charges)
		# =====================================================================
		_wt(
			6000, "Frais de voyage", "Earning", "13.1.1", _EXEMPT, stat="", common=1,
			abbr="TVLE", desc_fr="Remboursement frais de voyage", payment_days=0,
		),
		_wt(
			6001, "Frais de voiture", "Earning", "13.1.1", _EXEMPT, stat="", common=1,
			abbr="CARE", desc_fr="Remboursement frais de voiture", payment_days=0,
		),
		_wt(
			6002, "Frais de repas", "Earning", "13.1.1", _EXEMPT, stat="", common=1,
			abbr="MEAL", desc_fr="Remboursement frais de repas", payment_days=0,
		),
		_wt(6010, "Frais de nuitées", "Earning", "13.1.1", _EXEMPT, stat=""),
		_wt(6020, "Frais effectifs expatriés", "Earning", "13.1.2", _EXEMPT, stat=""),
		_wt(6030, "Autres frais effectifs", "Earning", "13.1.2", _EXEMPT, stat=""),
		_wt(
			6040, "Frais forfaitaires de représentation", "Earning", "13.2.1", _EXEMPT,
			stat="", common=1, abbr="REPR",
			desc_fr="Frais forfaitaires de représentation", payment_days=0,
		),
		_wt(6050, "Frais forfaitaires de voiture", "Earning", "13.2.2", _EXEMPT, stat=""),
		_wt(6060, "Frais forfaitaires pour expatriés", "Earning", "2.3", _ALL, stat=""),
		_wt(6070, "Autres frais forfaitaires", "Earning", "13.2.3", _EXEMPT, stat=""),
		# =====================================================================
		# 6510-6520: Advances (deductions from net pay)
		# =====================================================================
		_wt(6510, "Avance sur salaire", "Deduction", "", _DEDUCTION, stat="", common=1),
		_wt(6520, "Acomptes reçus", "Deduction", "", _DEDUCTION, stat=""),
	]
