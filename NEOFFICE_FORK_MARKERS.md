# NEOFFICE_FORK_MARKERS.md

Map of what this repository changes in code it did not write. The rule (`CLAUDE.md`,
"mark every change to code that is not ours") is that every changed hunk carries a
`//// Neoffice` comment saying **why**, so that `grep -rn "////"` gives the whole
divergence at the next upstream merge. This file holds the half of the map that cannot
live in a comment: JSON DocTypes, XSD, `.env` samples, committed build artifacts and
deleted files. `scripts/fork_markers.py check` reads it and accepts a non-commentable
file when its **full path** appears here.

---

## hrms

### Base and attribution (measured 2026-09-04)

| fact | value |
|---|---|
| fork | `bvisible/hrms`, branch `version-15` |
| upstream | `frappe/hrms`, branch `version-15` |
| **BASE** (last upstream commit contained in ours) | `fa4e55c11b` — `chore(release): Bumped to Version 15.63.3`, tag `v15.63.3`, 2026-08-20 |
| our commits since BASE | **168** |
| upstream commits since BASE not in ours | **10** (up to `b2d9a3cc7`, v15.63.4) |
| files we changed since BASE | 353 (317 added, 29 modified, 7 deleted) |

**How BASE was established** — not from the branch name. `upstream/version-15`,
`upstream/develop`, `upstream/version-15-hotfix` and `upstream/version-14` are none of
them an ancestor of `origin/version-15` (`git merge-base --is-ancestor` = NO for all
four), so our branch contains no upstream tip whole. The merge-base with
`upstream/version-15` and with `upstream/version-15-hotfix` is the same commit,
`fa4e55c11b`; the merge-base with `upstream/develop` (`1607f9a6a8`) is an **ancestor**
of it, so `version-15` is genuinely the closest upstream branch and its merge-base is
the base. `git branch -r --contains` confirms the commit lives on `upstream/version-15`
and `upstream/version-15-hotfix`.

**Attribution** — the 168 commits of `origin/version-15 ^BASE ^upstream/version-15` are
ours: 141 by Jérémy Christillin, 19 by bVisible/bvisible, 4 by `neoffice-fork-bot`,
3 by `github-actions[bot]` (the committed SPA build), 1 Neoffice, 1 NeoService; dates
2023-11-01 → 2026-09-04. **Zero `(cherry picked from commit …)` line**: this fork holds
no upstream backport, so no hunk needs the `backport of upstream <sha>` wording.
`git blame` (without `-w`) on the unmarked hunks pointed at those same commits.

### What is our own module

`hrms/regional/switzerland/**` and `hrms/payroll/doctype/swiss_*` +
`hrms/payroll/doctype/swissdec_*` + `cross_border_telework_log` are **additions**: the
Swiss payroll (AVS/AC/LAA/LPP, ESTV source tax, Lohnausweis, Swissdec transmission).
Every added source file carries a `//// Neoffice — added file` header; the JSON that
comes with them is listed below.

### The Swiss fields are Custom Fields, not JSON edits — keep it that way

`hrms/regional/switzerland/setup.py` declares **57 Custom Fields** through
`create_custom_fields`, so nothing Swiss is written into an upstream DocType JSON:

| DocType | Custom Fields |
|---|---|
| Employee | 29 (`ch_permit_type`, `ch_avs_number`, `ch_qst_*`, `ch_is_cross_border`, …) |
| Salary Component | 15 (`ch_wage_type`, `is_employer_contribution`, `ch_subject_to_*`, …) |
| Company | 9 (`ch_default_social_insurance_config`, `ch_uid_bfs`, `ch_contact_*`, …) |
| Salary Slip | 4 (`ch_qst_section`, `ch_qst_tariff_code`, `ch_qst_aperiodic`, `ch_qst_correction_details`) |

Three edits escaped that discipline and **should become Property Setters** at the next
merge (they are field-level edits inside upstream JSON, which is what conflicts):

- `hrms/payroll/doctype/salary_slip/salary_slip.json` — `default_print_format` added
- `hrms/hr/doctype/hr_settings/hr_settings.json` — `hidden` on one field
- `hrms/hr/doctype/expense_claim_type/expense_claim_type.json` — `in_list_view` on two fields

### Modified upstream JSON — field by field

#### `hrms/payroll/doctype/salary_slip/salary_slip.json`
- **added** top-level key `default_print_format: "Salary Slip Swiss"` — a Swiss pay slip must be printed with the Swiss layout out of the box.
- no field added, none removed, none changed.
- **should be a Property Setter** (`Salary Slip` / `default_print_format`) so the DocType JSON stays upstream's.

#### `hrms/hr/doctype/hr_settings/hr_settings.json`
- field `emp_created_by` (Select "Naming Series / Employee Number / Full Name"): **`hidden` 0 → 1**. Employee numbering is imposed by the Neoffice setup, not left to the customer.
- no field added, none removed.
- **should be a Property Setter** (`HR Settings` / `emp_created_by` / `hidden`).

#### `hrms/hr/doctype/expense_claim_type/expense_claim_type.json`
- field `description` (Small Text): `in_list_view` absent → **0**.
- field `deferred_expense_account` (Check): `in_list_view` absent → **0**.
- plus a trailing newline at end of file (upstream ships the file without one).
- both are the null → 0 normalisation a desk save writes back; **should be Property Setters**, or simply dropped at the merge — they change nothing.

#### `hrms/hr/module_onboarding/human_resource/human_resource.json`
- `documentation_url`: `https://docs.erpnext.com/…/human-resources` → `neoffice.io/help` — our customers must not be sent to the ERPNext manual.
- `steps`: removed `Create Employee`; added `Add Your First Swiss Employee` (in its place) and `Set Up Swiss Payroll` (at the end).
- `modified` bumped so the fixture re-imports.

#### `hrms/payroll/module_onboarding/payroll/payroll.json`
- `documentation_url`: `https://frappehr.com/docs/v14/en/payroll-entry` → `neoffice.io/help`. Nothing else.

#### `hrms/hr/onboarding_step/create_holiday_list/create_holiday_list.json`
- `action`: `Show Form Tour` → `Create Entry`. The form tours were never translated into French, so they show an English overlay to a Suisse-romande customer; a plain "create the record" step does not.

#### `hrms/hr/onboarding_step/create_leave_type/create_leave_type.json`
- `action`: `Show Form Tour` → `Create Entry` (same reason as above).

#### `hrms/hr/onboarding_step/create_leave_allocation/create_leave_allocation.json`
- `action`: `Show Form Tour` → `Create Entry`; `show_full_form`: 0 → 1 (the quick-entry dialog does not carry the fields the step is about).

#### `hrms/hr/onboarding_step/create_leave_application/create_leave_application.json`
- `action`: `Show Form Tour` → `Create Entry`; `show_full_form`: 0 → 1 (same reason).

#### `hrms/hr/onboarding_step/hr_settings/hr_settings.json`
- `action`: `Show Form Tour` → `Update Settings` (same reason).

#### `hrms/hr/onboarding_step/data_import/data_import.json`
- `action`: `Watch Video` → `Go to Page`; `video_url` emptied (it pointed at an English YouTube video); **added** `path: /app/data-import`, `callback_title: "Data Import"`, `intro_video_url: ""`.

#### `hrms/hr/workspace/hr/hr.json`
- the workspace was rebuilt: `content` rewritten (chart block dropped, "Your Shortcuts" → "Quick Access", a `Swiss Payroll` shortcut added first), `charts` emptied, `links` regrouped by card, `icon` `hr` → `lucide-briefcase`, `restrict_to_domain` "" → `HR`, `sequence_id` 8 → 30, `idx` 0 → 2.
- **added** keys `custom_blocks`, `number_cards`, `indicator_color`, `is_hidden`; **removed** `parent_page`.
- ⚠️ the `shortcuts` rows carry `parent`/`parentfield`/`parenttype` — child-document metadata a desk export leaked into the fixture. Harmless but not upstream's shape; drop it if the file is rewritten.

#### `hrms/hr/workspace/expense_claims/expense_claims.json`
- `content` rewritten (chart and spacer dropped, "Your Shortcuts" → "Quick Access"), `charts` emptied, `icon` `expenses` → `lucide-receipt`, `sequence_id` 8 → 33, `idx` 0 → 1, `creation` and `modified` bumped.
- **added** keys `indicator_color: green`, `restrict_to_domain: HR`.

#### `hrms/payroll/workspace/payroll/payroll.json`
- `content` rewritten (onboarding and chart blocks dropped, "Quick Access" header, Salary Slip / Payroll Entry shortcuts with a Draft counter), `charts` emptied, `links` regrouped, `icon` `money-coins-1` → `lucide-banknote`, `restrict_to_domain` "" → `HR`, `sequence_id` 15 → 31.
- **`parent_page` "" → `Swiss Payroll`**: upstream's Payroll workspace becomes a child of ours. This is the single line that decides the desk tree — restoring upstream's empty value moves Payroll back to the root.
- **added** keys `custom_blocks`, `number_cards`, `indicator_color: green`, `is_hidden`.

#### `package.json`
- `scripts.build` guarded: it now skips the vite build when `hrms/public/{frontend,roster}/assets` are already there, unless `FORCE_REBUILD` is set; **added** `scripts.build:force` with upstream's unconditional command.
- why: the build outputs are committed on this branch (commit-the-build), and a 4 GB client instance OOMs on vite. CI calls `build:force`.

#### `frontend/package.json`
- `scripts.build`: prefixed with `NODE_OPTIONS=--max-old-space-size=4096`; **added** `scripts.build:force` with the same command, called by `.github/workflows/build-frontend.yml`.
- same reason: the PWA build does not fit in Node's default heap on the CI runner.

### Deleted upstream files

Seven upstream workspaces were removed, their content folded into two of ours. At a
merge, git will offer to bring them back — **do not take them**, or the desk shows both
the old and the new tree:

- `hrms/hr/workspace/leaves/leaves.json` → folded into `Leaves and Attendance`
- `hrms/hr/workspace/shift_&_attendance/shift_&_attendance.json` → folded into `Leaves and Attendance`
- `hrms/hr/workspace/recruitment/recruitment.json` → folded into `Recruitment & Performance`
- `hrms/hr/workspace/performance/performance.json` → folded into `Recruitment & Performance`
- `hrms/hr/workspace/employee_lifecycle/employee_lifecycle.json` → folded into `HR`
- `hrms/payroll/workspace/salary_payout/salary_payout.json` → folded into `Payroll`
- `hrms/payroll/workspace/tax_&_benefits/tax_&_benefits.json` → folded into `Payroll`

### Added files with no comment syntax

Every path below is **added** by this fork; upstream has no equivalent.

- `hrms/hr/onboarding_step/set_up_swiss_payroll/set_up_swiss_payroll.json` — Onboarding Step — last step of the HR module tour, sends to /app/swiss-payroll.
- `hrms/hr/workspace/leaves_and_attendance/leaves_and_attendance.json` — Workspace (child of HR) — merges upstream's `Leaves` and `Shift & Attendance`, both deleted below.
- `hrms/hr/workspace/recruitment_&_performance/recruitment_&_performance.json` — Workspace (child of HR) — merges upstream's `Recruitment` and `Performance`, both deleted below.
- `hrms/payroll/doctype/cross_border_telework_log/cross_border_telework_log.json` — DocType, submittable, 19 fields, links Company/Employee, perms HR Manager + HR User — days teleworked from abroad (FR/DE/IT frontier agreements), which decide where the salary is taxed.
- `hrms/payroll/doctype/swiss_lohnausweis_mapping/swiss_lohnausweis_mapping.json` — Child table, 3 fields, links Salary Component — maps a salary component onto a box of the Lohnausweis (salary certificate, Form 11).
- `hrms/payroll/doctype/swiss_payroll_chat_message/swiss_payroll_chat_message.json` — Child table, 6 fields — one message of the payroll assistant conversation.
- `hrms/payroll/doctype/swiss_payroll_chat_session/swiss_payroll_chat_session.json` — DocType, 13 fields, links Company/User/Swiss Payroll Chat Message — a payroll assistant conversation.
- `hrms/payroll/doctype/swiss_qst_tariff/swiss_qst_tariff.json` — DocType, 17 fields — an ESTV source-tax tariff (canton, letter, year).
- `hrms/payroll/doctype/swiss_qst_tariff_bracket/swiss_qst_tariff_bracket.json` — DocType, 12 fields, links Swiss QST Tariff — one income bracket of a tariff.
- `hrms/payroll/doctype/swiss_salary_certificate/swiss_salary_certificate.json` — DocType, submittable, 53 fields, links Company/Employee/Fiscal Year — the yearly Lohnausweis (Form 11).
- `hrms/payroll/doctype/swiss_social_insurance_config/swiss_social_insurance_config.json` — DocType, 71 fields, links Company/Account/Swiss Lohnausweis Mapping — the AVS/AC/LAA/LPP/IJM rates, ceilings and accounts of one company.
- `hrms/payroll/doctype/swiss_wage_type/swiss_wage_type.json` — DocType, 31 fields — the Swissdec wage-type catalog (code + which insurance bases the component feeds).
- `hrms/payroll/doctype/swissdec_declaration/swissdec_declaration.json` — DocType, 46 fields, links Company/Fiscal Year — a Swissdec transmission to the insurers/tax offices.
- `hrms/payroll/doctype/swissdec_declaration_employee/swissdec_declaration_employee.json` — Child table, 15 fields, links Employee — one employee line of a declaration.
- `hrms/payroll/doctype/swissdec_ema_notification/swissdec_ema_notification.json` — DocType, 34 fields, links Company/Employee — an arrival / change / departure notification (EMA) to the insurers.
- `hrms/payroll/doctype/swissdec_transmitter_settings/swissdec_transmitter_settings.json` — Single, 10 fields, perms HR Manager — the SwissDecTX gateway coordinates.
- `hrms/payroll/module_onboarding/swiss_payroll/swiss_payroll.json` — Module Onboarding — the 7-step Swiss payroll tour.
- `hrms/payroll/onboarding_step/add_your_first_swiss_employee/add_your_first_swiss_employee.json` — Onboarding Step of the Swiss payroll tour.
- `hrms/payroll/onboarding_step/assign_a_swiss_salary_structure/assign_a_swiss_salary_structure.json` — Onboarding Step of the Swiss payroll tour.
- `hrms/payroll/onboarding_step/configure_swiss_social_insurances/configure_swiss_social_insurances.json` — Onboarding Step of the Swiss payroll tour.
- `hrms/payroll/onboarding_step/create_a_swiss_salary_structure/create_a_swiss_salary_structure.json` — Onboarding Step of the Swiss payroll tour.
- `hrms/payroll/onboarding_step/import_swiss_source_tax_tariffs/import_swiss_source_tax_tariffs.json` — Onboarding Step of the Swiss payroll tour.
- `hrms/payroll/onboarding_step/review_swiss_wage_types/review_swiss_wage_types.json` — Onboarding Step of the Swiss payroll tour.
- `hrms/payroll/onboarding_step/run_your_first_swiss_payroll_cycle/run_your_first_swiss_payroll_cycle.json` — Onboarding Step of the Swiss payroll tour.
- `hrms/payroll/page/swiss_employee_wizard/swiss_employee_wizard.json` — Page (Payroll, HR Manager + HR User) — hire an employee with AVS number, permit and source tax.
- `hrms/payroll/page/swiss_payroll_cycle/swiss_payroll_cycle.json` — Page (Payroll, HR Manager + HR User) — the monthly payroll cycle.
- `hrms/payroll/page/swiss_payroll_setup/swiss_payroll_setup.json` — Page (Payroll, System Manager + HR Manager + HR User) — insurance setup and ESTV tariff import.
- `hrms/payroll/page/swiss_year_end/swiss_year_end.json` — Page (Payroll, HR Manager + HR User) — year-end closing (certificates, yearly declaration).
- `hrms/payroll/print_format/salary_certificate_swiss/salary_certificate_swiss.json` — Print Format (Jinja, standard) on Swiss Salary Certificate — the official Form 11 layout.
- `hrms/payroll/print_format/salary_slip_swiss/salary_slip_swiss.json` — Print Format (Jinja, standard) on Salary Slip — the Swiss pay slip; set as `default_print_format` on Salary Slip (see below).
- `hrms/payroll/workspace/swiss_payroll/swiss_payroll.json` — Workspace (child of HR) — the entry point of the Swiss payroll; upstream's `Payroll` workspace becomes its child (see below).
- `hrms/regional/switzerland/gateway/.env.example` — Sample environment of the SwissDecTX gateway (paths, API keys, timeout). Placeholders only, no secret.
- `hrms/regional/switzerland/test_data/annexe1_oracle.json` — Swissdec certification fixture: the expected values of annex 1, used as the oracle of the Swiss payroll tests.
- `hrms/regional/switzerland/xsd/pain.001.001.09.ch.03.xsd` — ISO 20022 pain.001 Swiss Implementation Guidelines schema — validates the salary payment file before it is sent to the bank.

### Committed build artifacts — mark the source, never the artifact

Upstream gitignores both SPA builds and lets every bench rebuild them. We un-ignore them
(see the `//// Neoffice` marker in `.gitignore`) and commit the output, because a 4 GB
client instance OOMs on vite; `.github/workflows/build-frontend.yml` builds in CI and
commits. **Never hand-edit a file below** — mark `frontend/index.html` or
`roster/index.html` instead, vite copies their comments verbatim into the output.

| artifact | files in the diff | built from |
|---|---|---|
| `hrms/public/frontend/assets/*` | 124 | `frontend/` (vite, `outDir: ../hrms/public/frontend`) |
| `hrms/public/frontend/index.html`, `sw.js`, `manifest.webmanifest`, `frappe-push-notification.js`, `favicon.png` | 5 | idem |
| `hrms/www/hrms.html` | 1 | `cp hrms/public/frontend/index.html` (`frontend/package.json`, `copy-html-entry`) |
| `hrms/public/roster/assets/*` | 41 | `roster/` (vite, `outDir: ../hrms/public/roster`) |
| `hrms/public/roster/index.html`, `favicon.png` | 2 | idem |
| `hrms/www/roster.html` | 1 | `cp hrms/public/roster/index.html` (`roster/package.json`, `copy-html-entry`) |

`hrms/public/frontend/index.html` is the one artifact left **unmarked**: it sits under
`/public/frontend/`, which `fork_markers.py` skips, and `verify` refuses any added line
in a skipped file. The build bot writes the marker into it at the next `yarn build`.

### Decisions worth recording

- **Empty `__init__.py` left unmarked** — 18 of them under `hrms/payroll/doctype/swiss_*/`,
  `hrms/payroll/page/*/` and `hrms/regional/switzerland/`. A marker in a zero-byte file
  says nothing a merge could use, and their parent folder already carries one. Four more
  (`swiss_wage_type`, `swiss_salary_certificate`, `swiss_lohnausweis_mapping`,
  `swissdec_transmitter_settings`) hold only the upstream copyright header and are
  likewise left alone.
- **No unreachable hunk.** Every changed hunk in a commentable file could take a marker
  on its own line or within the three lines above it. Two are worth knowing about:
  `frontend/src/App.vue` carries its marker as `////import …`, a bare JS line comment
  (the four slashes ARE the comment), and
  `hrms/hr/report/employee_hours_utilization_based_on_timesheet/…py` disables whole
  blocks inside `'''` strings, so the marker sits on the quote line.
- **Files identical to upstream except for whitespace or a final newline** —
  `frontend/src/views/Login.vue` lost its trailing newline in `9c61c153e`; the hunk git
  reports at the end of that file is that missing `\n`, not code. Take upstream's ending
  at the merge.
- **`hrms/translations/fr.csv` and `hrms/locale/*.po`** are skipped by the checker
  (translations follow the `/translate` pipeline, PO only) and are not part of this map.

### Cross-app couplings to check at a merge

- `frappe.neolog(...)` — used in
  `hrms/hr/report/employee_hours_utilization_based_on_timesheet/…py`. It exists **only**
  in our `frappe` fork (`frappe/__init__.py`, itself marked `#//// added function`).
  Against upstream frappe this file raises `AttributeError`.
- `Employee.employment_degrees` — a child table `hrms` does not ship; it comes from
  another Neoffice app. Same file, same block.

