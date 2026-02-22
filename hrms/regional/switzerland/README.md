# Swiss Payroll Module

Regional module for Swiss social contributions in Frappe HRMS.

## Setup

```bash
bench --site <site_name> execute hrms.regional.switzerland.setup.setup
bench --site <site_name> migrate
```

This creates:
- 14 Salary Components (employee + employer pairs for AVS, AC, LPP, IJM, AC Solidarity; plus LAA Professional employer-only, LAA Non-Professional employee-only, Family Allowances employer-only, and 13th Month Salary earning)
- Custom fields on Employee (permit type, fiscal canton, AVS number), Company (default config link, employer cost account), and Salary Component (is_employer_contribution, linked_component)
- A default Salary Structure "Swiss Payroll - Standard" with all deduction components pre-configured

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
| 13th Month Salary | Mode (Disabled / Annual / Monthly) | Default: Disabled. See below. |

Each section also has GL account link fields for journal entry posting.

### 13th Month Salary (Treizieme salaire)

Configure via the **13th Month Salary** section on Swiss Social Insurance Config:

| Mode | Behavior |
|------|----------|
| **Disabled** | No 13th month. Social charges still calculated on full gross pay. |
| **Annual** | Full 13th month paid in December (or on the employee's final slip if they leave mid-year). Pro-rated for partial-year employees based on days worked. |
| **Monthly** | 1/12 of base salary added as an earning on every salary slip. |

**Pro-rata rules:**
- Employees joining mid-year receive a pro-rated amount (days worked / 365).
- Employees leaving mid-year receive their pro-rated 13th month on the final salary slip.
- Example: hired April 1 → December 13th month = base * 275/365.

**HR override:** If a manual Additional Salary for "13th Month Salary" already exists on the slip, the hook skips auto-calculation. This allows HR to override the amount for special contractual terms.

### Employee Fields

- **Permit Type**: Swiss Citizen, Permit B/C/G/L
- **Fiscal Canton**: 26 Swiss cantons (AG to ZH)
- **AVS Number**: Social security number (756.XXXX.XXXX.XX)

## How It Works

The module hooks into `Salary Slip.validate` via `doc_events` in `hooks.py`. When a salary slip is validated for a Swiss company:

1. **13th month earning** (if enabled): the hook adds a "13th Month Salary" earning row before computing gross pay. In Monthly mode, this is `base / 12` every month. In Annual mode, it's the full (pro-rated) base in December or on the relieving month.
2. **Gross pay calculation**: `gross_pay = sum(default_amount for all earnings)`. This unprorated total is used as the base for social charges. Swiss law requires ALL salary earnings to be subject to social charges.
3. **Rate-based components** (AVS, LAA, IJM, Family): calculated as `gross_pay * rate / 100`.
4. **AC/ALV**: tracks year-to-date gross via SQL query on submitted salary slips. Splits contribution between standard AC and solidarity when the annual ceiling (CHF 148'200) is crossed mid-month.
5. **LPP/BVG**: uses `base_monthly * multiplier` (13 if 13th month enabled, 12 otherwise) for the annual salary. Calculates coordinated salary, applies age-dependent rate (7%-18%), splits between employee and employer (minimum 50% employer by law).

All components support **payment-day proration**: `default_amount` holds the full monthly value, `amount` is prorated by `payment_days / total_working_days`.

Employer components use `do_not_include_in_total=1` so they appear in journal entries but not in the employee's net pay.

> **Important:** Expense reimbursements (Spesen) are not subject to social charges if covered by an approved expense regulation (Spesenreglement). They must be processed via the **Expense Claim** module, not as salary earning components. Any earning component on the salary slip will be included in the gross pay base for social charges.

## Salary Components

| Component | Type | Abbr | Base |
|-----------|------|------|------|
| AVS/AI/APG Employee | Deduction | AVS_EE | Rate from config |
| AVS/AI/APG Employer | Deduction | AVS_ER | Rate from config |
| AC/ALV Employee | Deduction | AC_EE | Rate + ceiling tracking |
| AC/ALV Employer | Deduction | AC_ER | Rate + ceiling tracking |
| AC Solidarity Employee | Deduction | ACSOL_EE | Above ceiling only |
| AC Solidarity Employer | Deduction | ACSOL_ER | Above ceiling only |
| LAA Professional Employer | Deduction | LAAP_ER | Insurer rate |
| LAA Non-Professional Employee | Deduction | LAANP_EE | Insurer rate |
| LPP/BVG Employee | Deduction | LPP_EE | Age-based |
| LPP/BVG Employer | Deduction | LPP_ER | Age-based |
| IJM/KTG Employee | Deduction | IJM_EE | Insurer rate |
| IJM/KTG Employer | Deduction | IJM_ER | Insurer rate |
| Family Allowances Employer | Deduction | FALLOC_ER | Cantonal rate |
| Source Tax Employee | Deduction | QST | ESTV tariff brackets |
| 13th Month Salary | Earning | 13M | Auto-calculated by hook |

## Source Tax (Quellensteuer / Impôt à la source)

### Overview

Employees subject to source taxation (primarily Permit B/G/L holders) have income tax withheld directly from their salary. Tax rates are published annually by the ESTV (Federal Tax Administration) as fixed-width tariff files, one per canton.

### Two Calculation Models

| Model | Cantons | Logic |
|-------|---------|-------|
| **Monthly** | AG, AI, AR, BE, BL, BS, GL, GR, JU, LU, NE, NW, OW, SG, SH, SO, SZ, TG, UR, ZG, ZH | rate = lookup(monthly_gross) → tax = gross × rate |
| **Annual** | FR, GE, TI, VD, VS | Projects annual income, looks up rate, calculates cumulative due minus YTD. December auto-corrects. |

### Setup

1. Run `setup()` to create the "Source Tax Employee" salary component
2. Import ESTV tariffs: open **Swiss QST Tariff** list view → click **Fetch All Cantons**
3. Select year and tariff type (Salaires / Autres revenus), confirm
4. Wait for background job to complete (~800k brackets across 26 cantons)
5. Tariffs are auto-activated after import

### Employee Configuration

On the Employee form, in the "Source Tax" section:

| Field | Description |
|-------|-------------|
| Subject to Source Tax | Main toggle — check for Permit B/G/L holders |
| Tariff Category | Letter code: A (single), B (married sole income), C (supplementary), etc. |
| Children (Tax) | Number of children for tax purposes (0-9) |
| Church Tax Member | Y/N — affects tariff bracket |
| Tariff Code | Auto-composed from above fields (e.g., B2Y) |
| Canton of Taxation | Canton for tax lookup (overrides fiscal canton) |
| Exceeds CHF 120k | Auto-set flag when projected annual > threshold |

### Config (Swiss Social Insurance Config)

| Field | Description | Default |
|-------|-------------|---------|
| Enable Source Tax | Master toggle for source tax calculation | Disabled |
| Default Taxation Canton | Fallback if employee has no canton set | — |
| Ordinary Taxation Threshold | CHF threshold for 120k flag | 120,000 |
| Source Tax GL Account | GL account for journal entries | — |

### Auto-Update

ESTV publishes next year's tariffs in early December. A daily scheduled task checks for missing tariffs (Dec 1 – Jan 15) and auto-imports them via background job.

### Key Rules

- Source tax is **NOT prorated** by payment days — the tariff bracket already accounts for actual income
- 13th month salary naturally increases gross → moves to higher bracket
- Annual model: December auto-corrects cumulative over/under deduction
- CHF 120k flag is informational only — employer continues withholding
- The "Source Tax Employee" component maps to Lohnausweis position 12

## Pay Slip (Art. 323b CO)

The **Salary Slip Swiss** print format (`hrms/payroll/print_format/salary_slip_swiss/`) provides a professional monthly pay slip with:

- **Employee info**: name, AVS number, permit type, fiscal canton, department, designation
- **Bank details**: bank name and account number
- **Earnings table**: component name, amount, year-to-date (YTD)
- **Employee deductions**: component name, rate (%), amount, YTD — employer components are filtered out
- **Net pay**: net amount, rounded total, amount in words, YTD
- **Employer contributions** (informational, greyed out): component name, rate (%), amount, YTD + total employer cost

Rates are fetched dynamically from the Swiss Social Insurance Config via `get_component_rates_for_salary_slip()`.

## Annual Salary Certificate (Lohnausweis Form 11)

The **Swiss Salary Certificate** DocType (`hrms/payroll/doctype/swiss_salary_certificate/`) generates the annual Lohnausweis required by Swiss tax law, covering all 15 positions of Form 11:

| Position | Description | Source |
|----------|-------------|--------|
| 1 | Salary, wages | Basic + 13th Month |
| 2.1-2.3 | Other benefits, board/lodging, fringe benefits | Manual |
| 3-7 | Irregular benefits, capital, ownership, directors fees, other | Manual |
| 8 | **Gross income** (calculated: sum 1-7) | Auto |
| 9 | AVS/AC/AANP contributions | Mapped from salary slips |
| 10.1 | BVG/LPP regular contributions | Mapped from salary slips |
| 10.2 | BVG buy-back | Manual |
| 11 | **Net salary** (calculated: 8 - 9 - 10.1 - 10.2) | Auto |
| 12 | Withholding tax | Manual |
| 13.1-13.3 | Expense allowances | Manual |
| 14 | Employer contributions | Manual |
| 15 | Remarks | Auto + manual |

### Workflow

1. Create a **Swiss Salary Certificate** record (employee + fiscal year)
2. Click **Populate from Salary Slips** to auto-fill positions from submitted slips
3. Review and adjust manual positions (2.1-2.3, 3-7, 10.2, 12-14)
4. Submit the certificate
5. Print using the **Salary Certificate Swiss** print format (bilingual FR/DE layout)

### Configuration: Lohnausweis Mapping

The mapping between salary components and Form 11 positions is configured on the **Swiss Social Insurance Config** DocType (Lohnausweis section). Run `setup()` to populate defaults:

| Component | Position |
|-----------|----------|
| Basic | 1 |
| 13th Month Salary | 1 |
| AVS/AI/APG Employee | 9 |
| AC/ALV Employee | 9 |
| AC Solidarity Employee | 9 |
| LAA Non-Professional Employee | 9 |
| IJM/KTG Employee | 9 |
| LPP/BVG Employee | 10.1 |

## Tests

```bash
# Unit tests via bench Python (frappe must be importable)
cd /path/to/frappe-bench
env/bin/python -m pytest apps/hrms/hrms/regional/switzerland/test_utils.py -v
env/bin/python -m pytest apps/hrms/hrms/regional/switzerland/test_lohnausweis.py -v
env/bin/python -m pytest apps/hrms/hrms/regional/switzerland/test_estv_parser.py -v
env/bin/python -m pytest apps/hrms/hrms/regional/switzerland/test_source_tax.py -v

# Or via bench
bench --site <site_name> run-tests --app hrms --module hrms.regional.switzerland.test_utils
bench --site <site_name> run-tests --app hrms --module hrms.regional.switzerland.test_source_tax
```

~90 unit tests covering:
- LPP coordinated salary (8 tests)
- LPP age brackets (6 tests)
- LPP full contribution (5 tests)
- AC ceiling tracking (6 tests)
- 13th month calculation (10 tests: both modes, pro-rata hire/departure, edge cases)
- 13th month integration (2 tests: LPP threshold crossing with x13, AC ceiling + December 13th)
- Component rate display (8 tests: all rate types, LPP age-based, custom employer share, edge cases)
- Lohnausweis mapping (4 tests: default mapping, position map completeness, uniqueness)
- Lohnausweis computation (8 tests: aggregation, full year, partial year, unmapped exclusion)
- Certificate calculated fields (2 tests: position 8 gross, position 11 net)
- ESTV parser (13 tests: line parsing, Rappen conversion, rate conversion, file parsing, canton filter)
- Source tax calculation model (4 tests: monthly/annual canton mapping, edge cases)
- Tariff code builder (6 tests: composition, capping, defaults)
- Monthly source tax (6 tests: basic calc, zero/negative gross, rounding, no rate)
- Annual source tax (6 tests: first month, mid-year, December correction, salary increase)
- Edge cases (2 tests: very low income, fractional amounts)

## File Structure

```
hrms/regional/switzerland/
├── __init__.py
├── constants.py              # 2025 rates, thresholds, component maps, Lohnausweis positions
├── setup.py                  # Custom fields, components, salary structure, Lohnausweis defaults
├── utils.py                  # Calculation engine (LPP, AC, 13th month, rates, config lookup)
├── source_tax.py             # Source tax engine (monthly + annual models, ESTV lookup)
├── estv_parser.py            # ESTV tariff file parser + downloader
├── payroll_hooks.py          # Salary Slip validate hook
├── test_utils.py             # 45 unit tests (calculations + rate display)
├── test_lohnausweis.py       # 14 unit tests (mapping + aggregation + computed fields)
├── test_estv_parser.py       # 13 unit tests (parser + format conversion)
├── test_source_tax.py        # 18 unit tests (models + calculations)
└── README.md

hrms/payroll/doctype/swiss_social_insurance_config/
├── __init__.py
├── swiss_social_insurance_config.json
└── swiss_social_insurance_config.py

hrms/payroll/doctype/swiss_qst_tariff/
├── __init__.py
├── swiss_qst_tariff.json           # One record per canton+year+type
├── swiss_qst_tariff.py             # Import, fetch, activate logic
└── swiss_qst_tariff.js             # Buttons + list view actions

hrms/payroll/doctype/swiss_qst_tariff_bracket/
├── __init__.py
├── swiss_qst_tariff_bracket.json   # ~800k rows (lookup table, autoincrement)
└── swiss_qst_tariff_bracket.py

hrms/payroll/doctype/swiss_lohnausweis_mapping/
├── __init__.py
├── swiss_lohnausweis_mapping.json   # Child table for component-to-position mapping
└── swiss_lohnausweis_mapping.py

hrms/payroll/doctype/swiss_salary_certificate/
├── __init__.py
├── swiss_salary_certificate.json    # Submittable DocType (Form 11 positions)
├── swiss_salary_certificate.py      # Business logic + populate from slips
└── swiss_salary_certificate.js      # Client-side button

hrms/payroll/print_format/salary_slip_swiss/
├── salary_slip_swiss.json
└── salary_slip_swiss.html           # Monthly pay slip with rates + YTD

hrms/payroll/print_format/salary_certificate_swiss/
├── salary_certificate_swiss.json
└── salary_certificate_swiss.html    # Lohnausweis Form 11 bilingual layout
```

## Not In Scope

- Swissdec certification / ELM 5.0
- Cross-border worker special rules (beyond standard QST tariffs)
