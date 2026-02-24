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
env/bin/python -m pytest apps/hrms/hrms/regional/switzerland/test_swissdec.py -v

# Or via bench
bench --site <site_name> run-tests --app hrms --module hrms.regional.switzerland.test_utils
bench --site <site_name> run-tests --app hrms --module hrms.regional.switzerland.test_source_tax
```

~155 unit tests covering:
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
- Cross-border classification (17 tests: DE/FR/IT routing, old/new Italian, GE exception, canton precedence)
- German flat tax (6 tests: basic calc, custom rate, rounding, edge cases)
- Italian rate factor (7 tests: 80% factor, custom factor, clamping, rounding)
- Tariff letter suggestion (7 tests: per-country suggestions, non-cross-border)
- Cross-border integration (7 tests: main entry point, all treatments, all French exempt cantons)
- AVS number validation (10 tests: format, check digit, edge cases)
- UID-BFS validation (6 tests: format variants, edge cases)
- Employee ELM validation (10 tests: required fields, QST, cross-border)
- Salary data validation (6 tests: completeness, consistency)
- Company validation (4 tests: UID-BFS, required fields)
- Validation summary (4 tests: aggregation, text output)
- Full declaration validation (3 tests: multi-employee, mixed errors)
- XML generation (16 tests: namespace, structure, all institution elements, UTF-8)
- Date formatting (2 tests: ISO format, edge cases)
- Month boundaries (5 tests: January, February leap/non-leap, December, April)
- Monthly XML generation (4 tests: period, amounts, institutions, schema version)
- Correction XML generation (2 tests: annual data, annual period)
- Correction validation (2 tests: warning without reference, no warning for Year-End)

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
├── cross_border.py           # Cross-border worker tax engine (DE/FR/IT)
├── test_cross_border.py      # ~44 unit tests (classification + calculations)
├── swissdec_xml.py           # Swissdec ELM 5.0 XML builder engine
├── swissdec_validation.py    # Pre-export validation engine
├── swissdec_data.py          # Salary data aggregation for ELM declarations
├── test_swissdec.py          # ~65 unit tests (XML + validation + data + monthly + correction)
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

hrms/payroll/doctype/cross_border_telework_log/
├── __init__.py
├── cross_border_telework_log.json   # Monthly telework tracking for cross-border workers
└── cross_border_telework_log.py     # YTD calculation + threshold warnings

hrms/payroll/doctype/swissdec_declaration/
├── __init__.py
├── swissdec_declaration.json        # Salary declaration per company/year
└── swissdec_declaration.py          # Business logic (populate, validate, export)

hrms/payroll/doctype/swissdec_declaration_employee/
├── __init__.py
├── swissdec_declaration_employee.json # Child table for declaration employees
└── swissdec_declaration_employee.py

hrms/payroll/print_format/salary_slip_swiss/
├── salary_slip_swiss.json
└── salary_slip_swiss.html           # Monthly pay slip with rates + YTD

hrms/payroll/print_format/salary_certificate_swiss/
├── salary_certificate_swiss.json
└── salary_certificate_swiss.html    # Lohnausweis Form 11 bilingual layout
```

## Cross-Border Workers (Travailleurs frontaliers)

### Overview

Employees residing in Germany, France, or Italy who commute to work in Switzerland are subject to country-specific tax rules governed by bilateral double taxation agreements.

### Three Bilateral Agreements

| Country | Agreement | Tax Treatment |
|---------|-----------|---------------|
| **Germany** | DTA CH-DE | Flat 4.5% withholding tax. Employee must commute daily and not exceed 45 non-return days/year. |
| **France** | CDI CH-FR | Most border cantons (BE, BS, BL, JU, NE, SO, VD, VS): taxed in France, no CH withholding. **Exception**: Geneva (GE) withholds at source using ESTV tariff codes G/M/N/Q. |
| **Italy** | CDI CH-IT | *Old frontaliers* (started before July 17, 2023) in TI/GR/VS: taxed only in Italy, no Swiss withholding. *New frontaliers* (from July 17, 2023): Switzerland withholds 80% of standard source tax using tariff codes R/S/T/U/V. |

### Employee Configuration

On the Employee form, in the "Cross-Border Worker" section:

| Field | Description |
|-------|-------------|
| Cross-Border Worker | Main toggle |
| Country of Residence | DE, FR, IT, AT, LI |
| Cross-Border Start Date | For Italian old/new frontalier determination |
| New Frontalier (post-2023) | Auto-set for Italian workers starting on or after July 17, 2023 |
| German Flat Tax (4.5%) | Auto-set for German workers |
| Permit Expiry Date | Optional tracking for Permit G |

### Config (Swiss Social Insurance Config)

| Field | Description | Default |
|-------|-------------|---------|
| Enable Cross-Border Rules | Master toggle | Disabled |
| German Flat Tax Rate (%) | DTA flat rate | 4.5 |
| Italian New Frontalier Rate Factor (%) | Multiplier for new frontalier rate | 80 |
| French Telework Threshold (%) | Max remote work from France | 40 |

### Cross-Border Telework Log

Monthly tracking DocType for telework days (French 40% threshold) and non-return days (German 45-day limit). One record per employee per month with YTD cumulative calculation and automatic threshold warnings.

### Tax Calculation Flow

1. Standard source tax is calculated via ESTV tariff brackets (Phase 3)
2. If `cb_enabled` and employee is cross-border, the cross-border engine overrides:
   - **German**: replaces with flat 4.5% tax
   - **French exempt** (non-GE border cantons): sets tax to 0
   - **French GE**: keeps standard ESTV result (tariff G/M/N/Q)
   - **Italian old**: sets tax to 0
   - **Italian new**: multiplies standard tax by 80%

## Swissdec ELM 5.0 Export

### Overview

Swiss employers must declare salary data electronically to institutions (AVS, AC, LPP, LAA, IJM, QST, Family Allowances) using the Swissdec ELM (Einheitliches Lohnmeldeverfahren) standard. ELM 5.0 became mandatory January 1, 2026.

This module generates **ELM 5.0-compliant XML** files that can be imported into certified transmitters (SwissDecTX, etc.).

### Swissdec Declaration DocType

One declaration per company per fiscal year (Year-End) or per month (Monthly). Corrections can be created at any time.

**Declaration Types:**

| Type | Naming | Period | Use Case |
|------|--------|--------|----------|
| **Year-End** | `SDD-{abbr}-{year}` | Full fiscal year | Annual salary declaration (once per year) |
| **Monthly** | `SDD-{abbr}-{year}-M{month:02d}` | Single month | Monthly interim declaration |
| **Correction** | `SDD-{abbr}-{year}-C{seq}` | Full fiscal year | Replaces a previously accepted declaration |

**Workflow:**
1. Create a **Swissdec Declaration** record (select company + fiscal year + type)
2. For Monthly: select the declaration month (1-12)
3. For Correction: optionally link the original declaration being corrected
4. Click **Populate Employees** to fetch all employees with submitted salary slips
5. Review the employee list, toggle inclusion per employee
6. Click **Run Validation** to check data completeness
7. Fix any errors flagged in the validation log
8. Click **Export XML** to generate the ELM file
9. Download the attached XML and import into a certified Swissdec transmitter

**Institution toggles:** AVS, AC, LPP, LAA, IJM, QST, Family Allowances (FAK), OFS/BFS statistics. Enable/disable per declaration.

**Monthly Declarations:**
- Data is scoped to the selected month only (salary slips within that month)
- AC ceiling tracking uses year-to-date gross from prior months
- LAA salary cap is prorated to 1/12 of the annual cap
- LPP coordinated salary is the annual coordinated amount divided by 12
- XML `PeriodFrom`/`PeriodTo` reflect the month boundaries

**Corrective Declarations:**
- A correction sends **complete replacement data**, not a delta
- The workflow is: fix salary slips → create Correction declaration → Populate → Validate → Export → Transmit
- The `original_declaration` field links to the Accepted declaration being replaced (optional but recommended)
- Validation warns if no original is referenced, errors if the referenced declaration doesn't exist

### Company Fields for ELM

Configure on the Company form in the "Swissdec / ELM" section:

| Field | Description |
|-------|-------------|
| UID-BFS Number | Company identification (CHE-XXX.XXX.XXX) |
| Swissdec Contact Person | Contact name for declarations |
| Contact Phone | Phone for declarations |
| Contact Email | Email for declarations |

### Employee Fields for ELM

Additional fields on the Employee form:

| Field | Description |
|-------|-------------|
| Nationality | Country link for ELM Person data |
| Work Percentage | Part-time percentage (default 100%) |
| Entry Date (Swiss) | Entry date for ELM declaration |
| Exit Date (Swiss) | Exit date for ELM declaration |

### Config Fields (Swiss Social Insurance Config)

In the "Swissdec / ELM" section:

| Field | Description |
|-------|-------------|
| Enable Swissdec Export | Master toggle |
| ELM Version | "5.0" (default) |
| AVS Branch Number | For multi-branch companies |
| LAA Insurer ID | LAA insurer identification |
| IJM Insurer ID | IJM insurer identification |
| LPP Institution ID | Pension fund identification |
| FAK Canton | Canton for family allowances |

### XML Structure

The generated XML follows the Swissdec SalaryDeclaration schema:

```xml
<SalaryDeclaration xmlns="http://www.swissdec.ch/schema/sd/20050902/SalaryDeclaration" schemaVersion="5.0">
  <Company>
    <UID-BFS>...</UID-BFS>
    <Name>...</Name>
    <Address>...</Address>
    <Staff>
      <Person>
        <Particulars>...</Particulars>     <!-- AVS number, name, DOB, gender -->
        <Activity>...</Activity>           <!-- canton, permit, work%, dates -->
        <AHV-AVS-Salaries>...</AHV-AVS-Salaries>
        <ALV-AC-Salaries>...</ALV-AC-Salaries>
        <BVG-LPP-Salaries>...</BVG-LPP-Salaries>
        <UVG-LAA-Salaries>...</UVG-LAA-Salaries>
        <KTG-IJM-Salaries>...</KTG-IJM-Salaries>
        <QST-Salaries>...</QST-Salaries>
        <FAK-CAF-Salaries>...</FAK-CAF-Salaries>
      </Person>
    </Staff>
  </Company>
</SalaryDeclaration>
```

### Validation

Pre-export validation checks:
- **Company**: UID-BFS presence and format, company name
- **Employee**: AVS number (EAN-13 check digit), date of birth, fiscal canton, nationality, permit type for non-Swiss, QST tariff for source-taxed employees, residence country for cross-border workers
- **Salary data**: salary slips exist for period, gross > 0, AVS contributions present, source tax for QST-subject employees
- **Correction**: original declaration exists and is in Accepted status (warning if missing, error if invalid reference)

### Swissdec Transmission (Phase 5B)

Automated transmission of ELM XML files via SwissDecTX 5.09 through a gateway service.

**Architecture:**
```
HRMS Instance(s) ── HTTP ──> Swissdec Gateway (Synology) ── SSH/SCP ──> SwissDecTX VM (Win11)
```

**Extended Workflow** (steps 7-9 replace manual import):
7. Click **Transmit** to send the XML via the Swissdec Gateway
8. Status updates to "Transmitted" (or directly "Accepted"/"Rejected")
9. For async results, click **Check Status** or wait for the hourly polling job

**Setup:**
1. Deploy the Swissdec Gateway on a host with SSH access to the SwissDecTX VM (see `gateway/README.md`)
2. Configure **Swissdec Transmitter Settings** in HRMS: Gateway URL, API key, Instance ID
3. Click **Test Connection** to verify connectivity

**Multi-Instance Support:** Multiple HRMS instances share a single SwissDecTX installation via the gateway. Each instance has its own API key and instance ID. TX commands are serialized to prevent conflicts.

**DocType: Swissdec Transmitter Settings** — Single-record settings for gateway connection (URL, API key, instance ID).

**Transmission Fields on Swissdec Declaration:**
- Transmission ID, Transmitted On, Declaration ID (from Swissdec)
- Response Status, Response Message
- Result XML, Answer XML (attached files)
- Transmission Log

### Not In Scope (Future Phases)

- PKI encryption (RSA-OAEP + AES-256-CBC)
- Swissdec certification process
- OFS/BFS statistics module
- 2D barcode for salary certificates (PDF417 / eCH-0270)
