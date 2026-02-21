# Swiss Payroll Module

Regional module for Swiss social contributions in Frappe HRMS.

## Setup

```bash
bench --site <site_name> execute hrms.regional.switzerland.setup.setup
bench --site <site_name> migrate
```

This creates:
- 13 Salary Components (employee + employer pairs for AVS, AC, LPP, IJM, AC Solidarity; plus LAA Professional employer-only, LAA Non-Professional employee-only, Family Allowances employer-only)
- Custom fields on Employee (permit type, fiscal canton, AVS number), Company (default config link, employer cost account), and Salary Component (is_employer_contribution, linked_component)
- A default Salary Structure "Swiss Payroll - Standard" with all components pre-configured

## Configuration

### Swiss Social Insurance Config

Create one record per company (or per company+canton for cantonal variations):

| Section | Fields | Notes |
|---------|--------|-------|
| AVS/AI/APG | Employee rate, Employer rate | Default 5.3% each |
| AC/ALV | Employee rate, Employer rate, Annual ceiling | Default 1.1%, ceiling CHF 148'200 |
| AC Solidarity | Employee rate, Employer rate | Default 0.5%, applies above AC ceiling |
| LAA | Professional rate, Non-professional rate | Set by insurer, no default |
| LPP/BVG | Employer share %, Entry threshold, Coordination deduction, Min/Max coordinated | Employer share minimum 50% by law |
| IJM/KTG | Employee rate, Employer rate | Set by insurer, no default |
| Family Allowances | Rate | Varies by canton |

Each section also has GL account link fields for journal entry posting.

### Employee Fields

- **Permit Type**: Swiss Citizen, Permit B/C/G/L
- **Fiscal Canton**: 26 Swiss cantons (AG to ZH)
- **AVS Number**: Social security number (756.XXXX.XXXX.XX)

## How It Works

The module hooks into `Salary Slip.validate` via `doc_events` in `hooks.py`. When a salary slip is validated for a Swiss company:

1. **Rate-based components** (AVS, LAA, IJM, Family): calculated as `base_salary * rate / 100`
2. **AC/ALV**: tracks year-to-date gross via SQL query on submitted salary slips. Splits contribution between standard AC and solidarity when the annual ceiling (CHF 148'200) is crossed mid-month.
3. **LPP/BVG**: calculates coordinated salary based on annual salary, applies age-dependent rate (7%–18%), splits between employee and employer (minimum 50% employer by law).

All components support **payment-day proration**: `default_amount` holds the full monthly value, `amount` is prorated by `payment_days / total_working_days`.

Employer components use `do_not_include_in_total=1` so they appear in journal entries but not in the employee's net pay.

## Salary Components

| Component | Type | Abbr | Base |
|-----------|------|------|------|
| AVS/AI/APG Employee | Employee | AVS_EE | Rate from config |
| AVS/AI/APG Employer | Employer | AVS_ER | Rate from config |
| AC/ALV Employee | Employee | AC_EE | Rate + ceiling tracking |
| AC/ALV Employer | Employer | AC_ER | Rate + ceiling tracking |
| AC Solidarity Employee | Employee | ACSOL_EE | Above ceiling only |
| AC Solidarity Employer | Employer | ACSOL_ER | Above ceiling only |
| LAA Professional Employer | Employer | LAAP_ER | Insurer rate |
| LAA Non-Professional Employee | Employee | LAANP_EE | Insurer rate |
| LPP/BVG Employee | Employee | LPP_EE | Age-based |
| LPP/BVG Employer | Employer | LPP_ER | Age-based |
| IJM/KTG Employee | Employee | IJM_EE | Insurer rate |
| IJM/KTG Employer | Employer | IJM_ER | Insurer rate |
| Family Allowances Employer | Employer | FALLOC_ER | Cantonal rate |

## Print Format

The **Salary Slip Swiss** print format (`hrms/payroll/print_format/salary_slip_swiss/`) filters employer contributions from the main deductions view and shows them in a separate informational section.

## Tests

```bash
# Unit tests (no bench required — uses mocked frappe)
python -m pytest hrms/regional/switzerland/test_utils.py -v

# Or via bench
bench --site <site_name> run-tests --app hrms --module hrms.regional.switzerland.test_utils
```

25 unit tests covering LPP coordinated salary (8 tests), LPP age brackets (6 tests), LPP full contribution (5 tests), and AC ceiling tracking (6 tests).

## File Structure

```
hrms/regional/switzerland/
├── __init__.py
├── constants.py              # 2025 rates and thresholds
├── setup.py                  # Custom fields, components, salary structure
├── utils.py                  # Calculation engine (LPP, AC, config lookup)
├── payroll_hooks.py          # Salary Slip validate hook
├── test_utils.py             # 25 unit tests
└── README.md

hrms/payroll/doctype/swiss_social_insurance_config/
├── __init__.py
├── swiss_social_insurance_config.json
└── swiss_social_insurance_config.py
```

## Not In Scope

- Source tax (impot a la source)
- 13th month salary
- Swiss pay slip legal format
- Swissdec certification / ELM 5.0
- Cross-border worker special rules
