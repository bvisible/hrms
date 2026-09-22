<!-- //// Neoffice — added file (no upstream equivalent): repo guide for Claude Code on THIS fork. -->
<!-- //// Upstream ships no CLAUDE.md; ours documents the commit-the-build pipeline (the -->
<!-- //// frontend/roster SPA builds are committed here, see .gitignore) and the Swiss -->
<!-- //// payroll module. Drop it only if the fork itself goes away. -->
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Frappe HR (HRMS) — open-source HR & Payroll application built on top of Frappe Framework and ERPNext.
- **Version**: 15.x (branch `version-15`)
- **Dependencies**: Frappe >= 15.0.0, ERPNext >= 15.0.0, Python >= 3.10

## Common Commands

### Running Tests
```bash
# Full parallel test suite (from bench directory)
bench --site <site_name> run-parallel-tests --app hrms --total-builds 2 --build-number 1

# Single test file
bench --site <site_name> run-tests --app hrms --module hrms.hr.doctype.<doctype_name>.test_<doctype_name>

# Single test case
bench --site <site_name> run-tests --app hrms --module hrms.hr.doctype.<doctype_name>.test_<doctype_name> --test <TestClassName>
```

### Frontend Development
```bash
# Install all frontend dependencies
yarn

# PWA (employee mobile app) - Vue 3 + Ionic
cd frontend && yarn dev

# Roster (shift management app) - Vue 3 + TypeScript
cd roster && yarn dev

# Build both frontends
yarn build
```

### Linting
```bash
# Python linting and formatting (Ruff)
ruff check hrms/
ruff format hrms/

# JS/Vue formatting (Prettier, via pre-commit)
npx prettier --write "hrms/**/*.{js,vue,css,scss}"
```

### Bench Operations
```bash
bench --site <site_name> migrate        # Run pending patches and schema changes
bench --site <site_name> clear-cache    # Clear server-side cache
bench build --app hrms                  # Build JS/CSS bundles
```

## Code Style

### Python
- **Formatter**: Ruff with **tab indentation**, double quotes, 110 char line length
- **Import order**: stdlib → third-party → frappe → erpnext → hrms → first-party → local
- All code comments in **English**
- All user-facing strings wrapped with `_("...")` for translation

### JavaScript
- Prettier for formatting
- User-facing strings wrapped with `__("...")` for translation

### Commits
- Conventional commits enforced: `feat`, `fix`, `refactor`, `chore`, `test`, `docs`, `perf`, `ci`, `build`, `style`, `revert`, `patch`
- Example: `fix(payroll): correct tax calculation for marginal relief`

### Error Logging
```python
# CORRECT — first arg is title (max 140 chars), second is message
frappe.log_error("Failed to process payroll", str(e))

# WRONG — will truncate
frappe.log_error(f"Failed to process payroll for {employee}: {str(e)}")
```

## Architecture

### App Structure
```
hrms/
├── hr/                    # HR module — ~114 doctypes
│   ├── doctype/           # Leave, Attendance, Recruitment, Appraisals, Shifts, etc.
│   └── report/            # HR reports
├── payroll/               # Payroll module — ~30 doctypes
│   ├── doctype/           # Salary Structures, Slips, Tax, Gratuity, etc.
│   └── report/            # Payroll reports
├── overrides/             # ERPNext doctype overrides (Employee, Timesheet, Payment Entry, Project)
├── api/                   # Whitelisted API endpoints for PWA/frontend
├── controllers/           # Shared business logic controllers
├── mixins/                # Mixin classes for doctypes
├── regional/              # Regional features (India tax/HRA, UAE)
├── patches/               # Migration patches (pre_model_sync / post_model_sync in patches.txt)
├── public/                # Static assets, JS bundles, doctype JS overrides
├── templates/             # Jinja email templates, web generators
├── translations/          # 70+ locale PO files
└── tests/                 # Test utilities (test_utils.py)
```

### Frontend Apps
- **`/frontend`** — Employee self-service PWA (Vue 3, Ionic 7, Frappe-UI, TailwindCSS, Firebase push)
- **`/roster`** — Shift roster management (Vue 3, TypeScript, Frappe-UI, TailwindCSS)

Both build into `hrms/public/frontend/` and `hrms/public/roster/` respectively.

### Key Patterns

**DocType overrides** — HRMS extends ERPNext doctypes via `override_doctype_class` in hooks.py:
- `Employee` → `hrms.overrides.employee_master.EmployeeMaster`
- `Timesheet` → `hrms.overrides.employee_timesheet.EmployeeTimesheet`
- `Payment Entry` → `hrms.overrides.employee_payment_entry.EmployeePaymentEntry`

**DocType JS extensions** — HRMS injects JS into ERPNext forms via `doctype_js` in hooks.py (Employee, Company, Department, Timesheet, Payment Entry, Journal Entry, etc.)

**Custom fields** — hooks.py contains extensive custom field definitions added to ERPNext doctypes (Company, Employee, Department, Designation, Project, etc.)

**Doc events** — hooks.py registers event handlers on ERPNext doctypes (User validate, Company validate, Employee updates, Payment/Journal Entry events)

**Scheduled tasks** — hourly (work summary, shift auto-attendance), daily (birthday/anniversary reminders, leave expiry), frequent (interview reminders)

**Website generators** — Job Opening pages auto-generated as website routes

### API Layer
`hrms/api/__init__.py` contains all whitelisted endpoints for the mobile PWA — employee info, attendance, leave, shifts, expenses, salary slips, notifications.

### Patches
Listed in `hrms/patches.txt` with `[pre_model_sync]` and `[post_model_sync]` sections. New patches go in `hrms/patches/v15_0/`.

### Regional
- **India**: HRA calculations, tax with marginal relief, gratuity rules in `hrms/regional/india/`.
- **Switzerland**: Social contributions (AVS, AC, LPP, LAA, IJM, Family Allowances), employer/employee component pairs, Swiss print format, and config DocType in `hrms/regional/switzerland/`. See `hrms/regional/switzerland/README.md` for details.

## Build pipeline (commit-the-build)

⚠️ **Ne jamais lancer `yarn build` ou `bench build --app hrms` localement sur un serveur Neoffice** (4 GB RAM → OOM-kill garanti). Le build se fait UNIQUEMENT sur GitHub Actions (ubuntu-latest, 16 GB RAM).

### Comment ça marche

1. Modif d'un fichier source (`frontend + roster/...`) en local → `git commit` → `git push origin version-15`. **Ne pas builder localement.**
2. Le workflow `.github/workflows/build-frontend.yml` détecte le push, lance `yarn build` sur ubuntu-latest (~1-2 min) et commit les artefacts back avec un commit `[skip-build] frontend artifacts for <SHA>` (par `github-actions[bot]`).
3. Sur les instances clients, le pipeline d'update fait `git pull` (ramène ton commit + le commit du bot). Quand `bench build --app hrms` tourne, il appelle `yarn build` à la racine — **le `package.json` voit les artefacts déjà présents et skip vite** (gate). Plus d'OOM-kill.

### Paths spécifiques

- **Source frontend** : `frontend + roster/`
- **Artefacts vite (commités)** : `hrms/public/frontend + hrms/public/roster/`
- **SPA HTML(s) (commités)** : `hrms/www/hrms.html` + `hrms/www/roster.html`
- **Build script root** : `yarn workspace (`yarn build-pwa && yarn build-roster`)`

### Forcer un rebuild local (si vraiment nécessaire)

```bash
FORCE_REBUILD=1 yarn build
```

### Documentation complète

- Doc canonique : `bvisible/neoffice-devops:main` → `docs/COMMIT-BUILD-PATTERN.md`
- Doc batch migration (12 apps) : même fichier, sections "Apps that have adopted the pattern" + "Edge cases discovered"
- Vault Obsidian : `[[NORA/04-savoir-faire/drive-frontend-build-pattern]]`

### Edge cases spécifiques à hrms

- 2 SPAs : `hrms` (employee self-service, dans `frontend/`) + `roster` (shift planner, dans `roster/`).
- 2 builds vite séparés. Le gate du package.json check les 2 paths d'artefacts.
- **socket.js**: pattern drive (async + DEV-only import dynamique, commit `3a8bd5c90`).

## Downstream consumer: the Neoffice mobile app (read before touching `hrms/api`)

**`hrms/api/__init__.py` is a public contract, not internal code.** The Neoffice
mobile app (private repo `neoffice-mobile`, React Native / Expo monorepo) ships a
full HR module built on it — leaves, attendance (check-in, attendance & shift
requests), expense claims, employee advances and salary slips, under
`apps/mobile/app/[site_id]/hrms/`. Breaking an endpoint there ships a broken app
to phones, and a phone app is not fixed by a `bench migrate`.

Audited 2026-09-22 against v15.64.1: the app calls **21** of the ~36 whitelisted
`hrms.api.*` functions. Before changing any of them — and after every upstream
merge — re-run the cross-check:

```bash
# endpoints the app calls
grep -rhoE "hrms\.api\.[a-zA-Z0-9_]+" ~/GitHub/neoffice-mobile/apps ~/GitHub/neoffice-mobile/packages \
  --include="*.ts" --include="*.tsx" | sort -u
```

and confirm each one still exists **with a compatible signature and HTTP method**.

**The trap is the HTTP method, not the name.** Upstream hardens endpoints in
place: v15.64.1 turned `mark_all_notifications_as_read`, `upload_base64_file` and
`delete_attachment` into `@frappe.whitelist(methods=["POST"])`. None of the three
was called by the app, so nothing broke — but the same edit on a GET the app uses
would have been a silent production break, invisible to every test in this repo.
A renamed or removed endpoint is loud; a method-restricted one is not.

Two more couplings worth knowing:
- The app downloads payslip PDFs through `frappe.utils.print_format.download_pdf`,
  so the **Swiss print format and its default-format setting are part of the
  mobile experience**, not just the desk.
- Swiss payroll fields (source tax, AVS/LPP lines) are not modelled in the app
  yet: it renders the generic earnings/deductions tables of the slip.
