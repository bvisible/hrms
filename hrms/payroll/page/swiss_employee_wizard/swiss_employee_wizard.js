//// Neoffice — added file (no upstream equivalent): desk page driving the Swiss employee creation
//// wizard. 2026-09-24: rewritten as THE way to hire (« c'est très compliqué de créer un employé »):
//// the person, the job, the permit and the personal situation in plain words (the source-tax
//// tariff letter follows from them), the badge presented at a terminal, then one click.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.pages["swiss-employee-wizard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("New Employee"),
		single_column: true,
	});
	wrapper.wizard = new SwissEmployeeWizard(page);
	//// Neoffice — Frappe's page view wires on_page_show and never on_page_hide: the desk's container fires a `hide` on
	//// the page's wrapper when it leaves, which nothing listened to, so the badge watch (a read every three seconds)
	//// went on from a page nobody was looking at. Bound here, to the hook below (14.10.2026).
	$(wrapper).on("hide", () => frappe.pages["swiss-employee-wizard"].on_page_hide(wrapper));
};

frappe.pages["swiss-employee-wizard"].on_page_hide = function (wrapper) {
	wrapper.wizard && wrapper.wizard.stop_badge_watch();
};

//// Neoffice — back on the page, the badge watch the leaving stopped starts again, on the badge step only.
frappe.pages["swiss-employee-wizard"].on_page_show = function (wrapper) {
	//// Neoffice — the route can name a record to finish (swiss-employee-wizard/<employee>, or /next): a new route is a new run.
	wrapper.wizard && wrapper.wizard.route_changed();
	wrapper.wizard && wrapper.wizard.resume_badge_watch();
};

const CANTONS = [
	"AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
	"NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH",
]; // prettier-ignore
const WIZARD = "hrms.regional.switzerland.employee_wizard";
const BADGES = "neoffice_theme.badge_assignment";
const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

//// Neoffice — the look of the boards Jérémy validated on 09.11 (« Employé et compte »: WizardAccess, WizardDone; copy in the
//// vault, Roles-Permissions/28-Planches-Employe-Et-Compte): one centred column, the steps numbered at the top as on our other
//// assistants (the design system's stepper: done in green with a check, the current one in a signal ring, the next ones
//// numbered), a Forum title per step, filled fields, Back and Continue apart at the bottom, and a done page in two cards.
//// On the desk's own variables, so the dark theme follows (10.11: « pourquoi tout est collé sur la gauche ? »).
const SEW_CSS_ID = "sew-css";
const SEW_CSS = `
.sew{max-width:900px;margin:0 auto;padding:18px 0 40px;display:flex;flex-direction:column;gap:22px;color:var(--text-color)}
.sew-steps{display:flex;align-items:flex-start;width:100%}
.sew-step{display:flex;flex-direction:column;align-items:center;gap:8px;flex:1;position:relative;min-width:0;background:none;border:0;padding:0;font:inherit;color:inherit}
.sew-step[data-go]{cursor:pointer}
.sew-node{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:15px;position:relative;z-index:1;border:2px solid var(--border-color);background:var(--card-bg);color:var(--text-muted)}
.sew-step.is-done .sew-node{background:#2F6E4E;border-color:#2F6E4E;color:#fff}
.sew-step.is-current .sew-node{border-color:#F55D1A;color:var(--text-color);box-shadow:0 0 0 5px rgba(245,93,26,.16)}
.sew-rule{position:absolute;top:19px;left:calc(-50% + 20px);width:calc(100% - 40px);height:2px;background:var(--border-color)}
.sew-rule.is-done{background:#2F6E4E}
.sew-step-label{font-size:13.5px;font-weight:600;text-align:center;line-height:1.25;padding:0 4px}
.sew-step.is-current .sew-step-label{color:#AA3700;font-weight:700}
[data-theme=dark] .sew-step.is-current .sew-step-label{color:#FFB599}
.sew-step.is-next .sew-step-label{color:var(--text-muted);font-weight:500}
.sew-head{display:flex;flex-direction:column;gap:6px}
.sew-title{margin:0;font-family:Forum,Georgia,serif;font-weight:400;font-size:30px;line-height:1.15}
.sew-lead{font-size:14.5px;color:var(--text-muted)}
.sew-note{font-size:14px;color:var(--text-muted)}
.sew .frappe-control .control-label{font-size:14.5px;color:var(--text-muted);font-weight:400;margin-bottom:7px}
.sew .frappe-control .form-control{background:var(--subtle-fg,var(--control-bg));border:1px solid transparent;border-radius:9px;min-height:44px;font-size:15.5px;box-shadow:none}
.sew .frappe-control .form-control:focus{background:var(--card-bg);border-color:#F55D1A;box-shadow:none}
.sew .frappe-control .help-box,.sew .frappe-control .control-value+.help-box{font-size:13px;color:var(--text-muted)}
.sew .form-section{border:0;padding:0}
.layout-main-section .sew .form-section .section-head:not(.collapsed-section),.sew .form-section .section-head{font-family:Forum,Georgia,serif;font-size:24px !important;font-weight:400 !important;padding:6px 0 10px;margin:0;text-transform:none !important;letter-spacing:normal !important;color:var(--text-color) !important;border-bottom:0;cursor:default}
.sew .form-section .section-body{padding:0}
.sew .form-column{padding:0 10px}
.sew .form-column:first-child{padding-left:0}
.sew .form-column:last-child{padding-right:0}
.sew-card{border:1px solid var(--border-color);border-radius:14px;padding:20px 24px;background:var(--card-bg);display:flex;flex-direction:column;gap:12px}
.sew-card-title{font-family:Forum,Georgia,serif;font-size:24px;line-height:1.2}
.sew-sum{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,3fr);border-top:1px solid var(--border-color)}
.sew-sum>div{padding:10px 4px;border-bottom:1px solid var(--border-color);font-size:15px}
.sew-sum>div:nth-child(odd){color:var(--text-muted)}
.sew-later{display:flex;gap:10px;align-items:flex-start;background:#FDF3DC;color:#5C4A12;border-radius:10px;padding:10px 14px;font-size:14px}
[data-theme=dark] .sew-later{background:rgba(161,98,7,.16);color:var(--text-color)}
.sew-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
.sew-foot-right{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-left:auto}
.sew-btn{border-radius:12px;padding:12px 24px;font-size:15.5px;font-weight:600;min-height:44px;border:1.5px solid var(--text-color);background:var(--card-bg);color:var(--text-color)}
.sew-btn.primary{background:var(--text-color);color:var(--card-bg);padding:13px 28px}
.sew-link{color:#AA3700;font-weight:600;font-size:15px;background:none;border:0;padding:6px 4px}
[data-theme=dark] .sew-link{color:#FFB599}
.sew-pick{display:flex;gap:12px;align-items:center;padding:12px 16px;border-radius:12px;border:1px solid var(--border-color);background:var(--card-bg);margin:0 0 8px;font-weight:400;cursor:pointer}
.sew-pick.is-recent{border-color:#F55D1A}
.sew-pill{display:inline-flex;align-items:center;gap:7px;padding:5px 12px;border-radius:999px;font-size:13.5px;font-weight:500;white-space:nowrap}
.sew-pill::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor}
.sew-pill.success{background:#E6F4EA;color:#15803D}
.sew-pill.warn{background:#FDF3DC;color:#A16207}
.sew-hero{position:relative;border:1px solid #FFD1C1;border-radius:18px;padding:34px 36px 30px;background:linear-gradient(115deg,#FFEFE9,#FBF6EE 60%,#FAF8F4);display:flex;flex-direction:column;gap:6px;margin-top:14px}
[data-theme=dark] .sew-hero{background:linear-gradient(115deg,rgba(245,93,26,.16),var(--card-bg) 60%);border-color:rgba(245,93,26,.4)}
.sew-hero .sew-pill{position:absolute;top:-14px;left:36px}
.sew-hero-title{margin:0;font-family:Forum,Georgia,serif;font-weight:400;font-size:40px;line-height:1.1}
.sew-hero-sub{font-size:15px;color:var(--text-muted)}
.sew-two{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}
.sew-line{display:flex;gap:14px;align-items:flex-start;font-size:15.5px;line-height:1.4}
.sew-ok,.sew-warn-dot{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex:none;margin-top:1px}
.sew-ok{background:#2F6E4E;color:#fff}
.sew-warn-dot{background:#FDF3DC;color:#A16207;font-weight:700;font-size:14px}
.sew-actions{display:flex;gap:12px;flex-wrap:wrap}
@media (max-width:720px){.sew-two,.sew-sum{grid-template-columns:1fr}.sew-step-label{font-size:11.5px}.sew-title{font-size:26px}}
`;
const SEW_CHECK =
	'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';

function sew_ensure_css() {
	if (document.getElementById(SEW_CSS_ID)) return;
	const style = document.createElement("style");
	style.id = SEW_CSS_ID;
	style.textContent = SEW_CSS;
	document.head.appendChild(style);
}

class SwissEmployeeWizard {
	constructor(page) {
		this.page = page;
		this.step = 0;
		sew_ensure_css();
		this.body = $('<div class="sew"></div>').appendTo(this.page.main);
		this.body.on("click", "[data-go]", (e) => {
			//// Neoffice — a done step is a way back: what was typed on this one is kept.
			const target = Number($(e.currentTarget).attr("data-go"));
			if (!(target < this.step)) return;
			this.collect();
			this.step = target;
			this.render_step();
		});
		// The badge step exists where the terminals do (the Neoffice theme).
		// The badge step needs neoffice_theme and a terminal that is on: its boot flag says both. A theme
		// that does not set the flag yet (it ships separately) keeps the step wherever it is installed.
		this.with_badges =
			frappe.boot.neoffice_bornes === undefined
				? !!(frappe.boot.versions && frappe.boot.versions.neoffice_theme)
				: !!frappe.boot.neoffice_bornes;
		//// Neoffice — the access step: where the theme brings the choice of how a person uses Neoffice (an account for the
		//// employee, made with the record). Absent without the theme: the wizard then creates the record alone.
		this.with_access = !!(
			window.neoffice_theme &&
			neoffice_theme.employee_access &&
			neoffice_theme.employee_access.mount
		);
		this.reset();
		this.start();
	}

	reset() {
		this.data = {
			company: frappe.defaults.get_user_default("Company"),
			work_percentage: 100,
			nationality: "Switzerland",
			marital_status: "Single",
		};
		this.step = 0;
		this.badge = null;
		this.access = null;
		this.access_state = null;
		this.tax = null;
		//// Neoffice — back to the hire (the finish mode sets these).
		this.mode = null;
		this.employee = null;
		this.info = null;
		this.page.set_title(__("New Employee"));
	}

	async start() {
		this.current_target = this.route_target();
		const genders = await frappe.db.get_list("Gender", { fields: ["name"], limit: 20 });
		this.genders = genders.map((g) => g.name);
		//// Neoffice — a record to finish is named by the route.
		if (this.current_target) return this.start_finish(this.current_target);
		await this.load_defaults();
		this.render_step();
	}

	async load_defaults() {
		this.defaults = {};
		if (!this.data.company) return;
		try {
			this.defaults = await frappe.xcall(`${WIZARD}.wizard_defaults`, {
				company: this.data.company,
			});
		} catch (e) {
			this.defaults = {};
		}
		this.data.canton = this.defaults.canton || this.data.canton;
		this.data.residence_canton = this.data.residence_canton || this.defaults.canton;
	}

	steps() {
		return [
			{ key: "person", label: __("The person") },
			{ key: "job", label: __("The job") },
			{ key: "tax", label: __("Permit and tax") },
			...(this.with_access && this.mode !== "finish"
				? [{ key: "access", label: __("Access") }]
				: []),
			...(this.with_badges ? [{ key: "badge", label: __("Badge") }] : []),
			{
				key: "review",
				label: this.mode === "finish" ? __("Check and finish") : __("Check and create"),
			},
		];
	}

	// ---------------------------------------------------------------- fields

	fields_for(key) {
		if (key === "person") {
			return [
				{ fieldname: "first_name", label: __("First Name"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "last_name", label: __("Last Name"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "col1", fieldtype: "Column Break" },
				{
					fieldname: "gender",
					label: __("Gender"),
					fieldtype: "Select",
					options: ["", ...this.genders].join("\n"),
					reqd: 1,
				},
				{
					fieldname: "date_of_birth",
					label: __("Date of Birth"),
					fieldtype: "Date",
					reqd: 1,
				},
				{
					fieldname: "sb_contact",
					fieldtype: "Section Break",
					label: __("To reach them"),
				},
				{
					fieldname: "email",
					label: __("E-mail"),
					fieldtype: "Data",
					options: "Email",
					description: __(
						"Their payslips are sent to this address; without one, they are printed.",
					),
				},
				{ fieldname: "col2", fieldtype: "Column Break" },
				{
					fieldname: "mobile",
					label: __("Mobile phone"),
					fieldtype: "Data",
					options: "Phone",
				},
				// The address the salary certificate prints and the salary payment sends: an
				// employee hired without it could not be paid.
				{ fieldname: "sb_address", fieldtype: "Section Break", label: __("Address") },
				{ fieldname: "address_street", label: __("Street and number"), fieldtype: "Data" },
				{ fieldname: "col_address", fieldtype: "Column Break" },
				{
					fieldname: "address_town",
					label: __("Postcode and town"),
					fieldtype: "Data",
					description: __(
						"Printed on the salary certificate and sent with the salary payment.",
					),
				},
				{ fieldname: "sb_avs", fieldtype: "Section Break" },
				{
					fieldname: "avs_number",
					label: __("AVS Number (756.XXXX.XXXX.XX)"),
					fieldtype: "Data",
					description: __(
						"On the AVS or health insurance card. It can wait, but the declarations need it.",
					),
				},
			];
		}
		if (key === "job") {
			const structures = this.defaults.structures || [];
			return [
				{
					fieldname: "company",
					label: __("Company"),
					fieldtype: "Link",
					options: "Company",
					reqd: 1,
					onchange: () => this.company_changed(),
				},
				{
					fieldname: "date_of_joining",
					//// Neoffice — "Start date" is also a subscription or contract start elsewhere and the
					//// last app loaded wins the bare key: the context keeps the hiring-date wording here.
					label: __("Start date", null, "employment start date"),
					fieldtype: "Date",
					reqd: 1,
				},
				{
					fieldname: "designation",
					label: __("Job title"),
					fieldtype: "Data",
					description: __("Created if it does not exist yet."),
				},
				{ fieldname: "col1", fieldtype: "Column Break" },
				{
					fieldname: "work_percentage",
					label: __("Activity rate (%)"),
					fieldtype: "Percent",
					// "100.0", not the system's three decimals ("100.000"); 62.5 still fits.
					precision: 1,
				},
				{
					fieldname: "base",
					label: __("Gross monthly salary"),
					fieldtype: "Currency",
					description: structures.length
						? __("The salary actually paid each month, at this activity rate.")
						: __("No salary structure yet: the salary is recorded once one exists."),
				},
				{
					fieldname: "salary_structure",
					label: __("Salary structure"),
					fieldtype: "Select",
					options: ["", ...structures].join("\n"),
					hidden: structures.length < 2 ? 1 : 0,
				},
				{ fieldname: "sb_pay", fieldtype: "Section Break" },
				{
					fieldname: "iban",
					label: __("IBAN of the salary account"),
					fieldtype: "Data",
					description: __("Needed to pay the salary by bank transfer."),
				},
				{ fieldname: "col2", fieldtype: "Column Break" },
				{
					fieldname: "vacation_days",
					label: __("Vacation days a year"),
					// //// Neoffice — an Int field cut 22.5 to 22 (a half day lost a year); the days are kept to the half day.
					fieldtype: "Float",
					precision: 1,
					description: __("At least 20 by law, 25 until the age of 20."),
				},
			];
		}
		if (key === "tax") {
			const abroad = "eval:doc.permit_type=='Permit G (Cross-border)'";
			return [
				{
					fieldname: "nationality",
					label: __("Nationality"),
					fieldtype: "Link",
					options: "Country",
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "permit_type",
					label: __("Permit"),
					fieldtype: "Select",
					options: [
						"",
						"Permit C (Settlement)",
						"Permit B (Residence)",
						"Permit L (Short-term)",
						"Permit G (Cross-border)",
					].join("\n"),
					depends_on: "eval:doc.nationality && doc.nationality!='Switzerland'",
					onchange: () => this.refresh_tax(),
				},
				{ fieldname: "col1", fieldtype: "Column Break" },
				{
					fieldname: "residence_canton",
					label: __("Canton of residence"),
					fieldtype: "Select",
					options: ["", ...CANTONS].join("\n"),
					depends_on: "eval:doc.permit_type!='Permit G (Cross-border)'",
					description: __("A resident's source tax goes to the canton they live in."),
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "residence_country",
					label: __("Country of residence"),
					fieldtype: "Select",
					// The code is what the employee record keeps; the name is what the user reads
					// (the Select control translates the labels).
					options: [
						{ value: "", label: "" },
						{ value: "DE", label: "Germany" },
						{ value: "FR", label: "France" },
						{ value: "IT", label: "Italy" },
						{ value: "AT", label: "Austria" },
						{ value: "LI", label: "Liechtenstein" },
					],
					depends_on: abroad,
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "de_gre1",
					label: __("Gre-1 certificate of residence handed in"),
					fieldtype: "Check",
					depends_on: "eval:doc.residence_country=='DE'",
					description: __(
						"Without it, the ordinary tariff applies instead of 4.5 % at most.",
					),
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "fr_2041as",
					label: __("2041-AS form handed in"),
					fieldtype: "Check",
					depends_on: "eval:doc.residence_country=='FR'",
					description: __(
						"Taxed in France instead, in the cantons of the 1983 agreement (not in Geneva).",
					),
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "cross_border_start_date",
					label: __("Cross-border commuter since"),
					fieldtype: "Date",
					depends_on: "eval:doc.residence_country=='IT'",
					description: __(
						"From 17 July 2023: the new agreement's tariffs (R, S, T, U).",
					),
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "sb_situation",
					fieldtype: "Section Break",
					label: __("Personal situation"),
				},
				{
					fieldname: "marital_status",
					label: __("Marital status"),
					fieldtype: "Select",
					options: [
						// "Single" alone reads « Simple » in French: Frappe translates it as a Single DocType.
						{ value: "Single", label: __("Single", null, "marital status") },
						{ value: "Married", label: __("Married or registered partnership") },
						{ value: "Divorced", label: __("Divorced or separated") },
						{ value: "Widowed", label: __("Widowed") },
					],
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "spouse_works",
					label: __("The spouse has an income"),
					fieldtype: "Check",
					depends_on: "eval:doc.marital_status=='Married'",
					onchange: () => this.refresh_tax(),
				},
				{ fieldname: "col2", fieldtype: "Column Break" },
				{
					fieldname: "num_children",
					label: __("Dependent children"),
					fieldtype: "Int",
					onchange: () => this.refresh_tax(),
				},
				{
					fieldname: "church_tax",
					label: __("Member of a recognised church (church tax)"),
					fieldtype: "Check",
					onchange: () => this.refresh_tax(),
				},
				// Taxed at source with other employers, the rate is set on the whole activity (ESTV
				// Circular 45, 7.2.1): asked only when the source tax applies (refresh_tax keeps
				// qst_subject in the form for these depends_on).
				{ fieldname: "qst_subject", fieldtype: "Check", hidden: 1 },
				{
					fieldname: "sb_other_employers",
					fieldtype: "Section Break",
					label: __("Other employers"),
					depends_on: "eval:doc.qst_subject",
				},
				{
					fieldname: "other_employment",
					label: __("Also works for other employers"),
					fieldtype: "Check",
					description: __("The source tax rate is then set on the whole activity."),
				},
				{ fieldname: "col3", fieldtype: "Column Break" },
				{
					fieldname: "other_activity_basis",
					label: __("What is known of the other employers"),
					fieldtype: "Select",
					options: [
						{ value: "Unknown", label: __("Nothing: extrapolated to 100 %") },
						{ value: "Work Percentage", label: __("Their activity rate") },
						{ value: "Gross Income", label: __("Their monthly gross") },
					],
					default: "Unknown",
					depends_on: "eval:doc.other_employment",
				},
				{
					fieldname: "other_activity_rate",
					label: __("Activity rate at the other employers (%)"),
					fieldtype: "Percent",
					precision: 1,
					depends_on:
						"eval:doc.other_employment && doc.other_activity_basis=='Work Percentage'",
				},
				{
					fieldname: "other_activity_gross",
					label: __("Monthly gross at the other employers"),
					fieldtype: "Currency",
					depends_on:
						"eval:doc.other_employment && doc.other_activity_basis=='Gross Income'",
				},
				{ fieldname: "sb_summary", fieldtype: "Section Break" },
				{ fieldname: "tax_summary", fieldtype: "HTML" },
			];
		}
		return [];
	}

	async company_changed() {
		const company = this.form.get_value("company");
		if (!company || company === this.data.company) return;
		this.collect();
		this.data.company = company;
		this.data.canton = null;
		await this.load_defaults();
		this.render_step();
	}

	// ---------------------------------------------------------------- source tax

	// Permit B/L/G without the C permit: source tax (art. 83 LIFD). The server says so, and which
	// tariff the situation gives, as the employee would be created.
	async refresh_tax() {
		if (!this.form) return;
		Object.assign(this.data, this.form.get_values(true));
		const data = this.tax_data();
		const tax = await frappe.xcall(`${WIZARD}.suggest_source_tax`, {
			data: JSON.stringify(data),
		});
		this.tax = tax;
		this.data.qst_subject = tax.qst_subject ? 1 : 0;
		this.data.tariff_letter = tax.qst_subject ? tax.tariff_code.slice(0, 1) : null;
		// The questions on other employers show only when the source tax applies.
		if (this.form.get_value("qst_subject") !== this.data.qst_subject) {
			await this.form.set_value("qst_subject", this.data.qst_subject);
		}
		const field = this.form.get_field("tax_summary");
		field && field.$wrapper.html(this.tax_summary_html());
	}

	tax_data() {
		const d = this.data;
		const swiss = !d.nationality || d.nationality === "Switzerland";
		const permit = swiss ? "Swiss Citizen" : d.permit_type || "";
		const cross_border = permit === "Permit G (Cross-border)";
		const it_new =
			d.residence_country === "IT" &&
			d.cross_border_start_date &&
			d.cross_border_start_date >= "2023-07-17";
		return {
			...d,
			permit_type: permit,
			is_cross_border: cross_border ? 1 : 0,
			it_new_frontalier: it_new ? 1 : 0,
			tariff_letter: null,
			reference_date: d.date_of_joining,
		};
	}

	tax_summary_html() {
		const tax = this.tax;
		if (!tax) return "";
		if (!tax.qst_subject) {
			return `<div class="text-muted">${__(
				"Taxed ordinarily: no source tax is withheld from the salary.",
			)}</div>`;
		}
		const model =
			tax.model === "annual" ? __("annual model") : tax.model ? __("monthly model") : "";
		const warn =
			tax.tariff_available === false
				? `<div class="text-warning small" style="margin-top: 4px;">${__(
						"The ESTV tariffs of this canton are not imported yet: import them before the first payroll.",
				  )}</div>`
				: "";
		return `<div class="sew-card" style="gap: 4px;">
			<b>${__("Source tax: tariff {0}", [esc(tax.tariff_code)])}</b>
			${model ? `<span class="text-muted"> · ${esc(model)}</span>` : ""}
			<div class="text-muted small" style="margin-top: 4px;">${(tax.notes || [])
				.map(esc)
				.join("<br>")}</div>${warn}
		</div>`;
	}

	// ---------------------------------------------------------------- access
	//// Neoffice — how the person uses Neoffice: the theme's choice (kind, application, tools, rights), mounted here. The
	//// account is made after the record, by the same server function every door uses (neoffice_theme.employee_account).

	async render_access() {
		const holder = $('<div class="sew-access"></div>').appendTo(this.body);
		const first_name = this.data.first_name || "";
		this.access = await neoffice_theme.employee_access.mount(holder, {
			first_name: first_name,
			get_email: () => this.data.email || "",
			//// Neoffice — the job title of the second step: Nora's suggestion reads it (« Cheffe de chantier » → in the field).
			job: this.data.designation || "",
			initial: this.access_state,
			on_change: (controller) => {
				this.access = controller;
				this.access_state = controller.raw();
			},
		});
		this.render_nav();
	}

	access_kind() {
		return this.access && this.access_state ? this.access_state.kind : "none";
	}

	// ---------------------------------------------------------------- badge

	render_badge() {
		const holder = $('<div class="sew-badge"></div>').appendTo(this.body);
		// Built outside the template: a template literal inside the __() arguments hides the call
		// from the POT extractor, and the next update of the PO files would drop its translation.
		const who = `<b>${esc(this.data.first_name || __("the employee"))}</b>`;
		holder.html(`
			<div class="sew-card">
				<div>${__(
					"Have {0} present their badge at a terminal: it appears below within a few seconds. Choose it, and their next swipe clocks them in.",
					[who],
				)}</div>
				<div class="sew-terminals sew-note"></div>
				<div class="sew-badges"></div>
				<label class="sew-pick">
					<input type="radio" name="sew-badge" value="" ${this.badge ? "" : "checked"}>
					${__("No badge for now")}
				</label>
			</div>`);
		holder.on("change", "input[name=sew-badge]", (e) => {
			const value = $(e.currentTarget).val();
			this.badge = value ? (this.badge_rows || []).find((b) => b.name === value) : null;
		});
		this.watch_badges(holder);
		this.render_nav();
	}

	watch_badges(holder) {
		this.stop_badge_watch();
		this.badge_holder = holder;
		const load = async () => {
			let res;
			try {
				res = await frappe.xcall(`${BADGES}.badges_to_assign`);
			} catch (e) {
				holder
					.find(".sew-badges")
					.html(
						`<div class="text-muted">${__("The badges cannot be read here.")}</div>`,
					);
				this.stop_badge_watch();
				return;
			}
			this.badge_rows = res.badges;
			const online = res.bornes.filter((b) => b.online);
			holder
				.find(".sew-terminals")
				.html(
					res.bornes.length
						? online.length
							? __("Terminal ready: {0}", [
									online.map((b) => esc(b.label)).join(", "),
							  ])
							: __("No terminal seen in the last minutes: {0}", [
									res.bornes.map((b) => esc(b.label)).join(", "),
							  ])
						: __("No terminal on this instance."),
				);
			const chosen = this.badge && this.badge.name;
			holder.find(".sew-badges").html(
				res.badges.length
					? res.badges
							.map(
								(b) => `
						<label class="sew-pick ${b.recent ? "is-recent" : ""}">
							<input type="radio" name="sew-badge" value="${esc(b.name)}" ${chosen === b.name ? "checked" : ""}>
							<span style="flex: 1;"><b>${__("Badge …{0}", [esc(b.uid_tail)])}</b>
								<span class="text-muted small"> · ${
									b.seen_ago == null
										? ""
										: __("presented {0} ago", [this.ago(b.seen_ago)])
								}${b.borne ? " · " + esc(b.borne) : ""}</span></span>
							${b.recent ? `<span class="sew-pill success">${__("recent")}</span>` : ""}
						</label>`,
							)
							.join("")
					: `<div class="text-muted">${__("Waiting for a badge…")}</div>`,
			);
		};
		load();
		this.badge_timer = setInterval(load, 3000);
	}

	stop_badge_watch() {
		if (this.badge_timer) clearInterval(this.badge_timer);
		this.badge_timer = null;
	}

	//// Neoffice — the page was left and shown again: the watch runs again if the badge step is the one on screen
	//// (its holder is still in the page: the steps are not drawn again by the desk coming back).
	resume_badge_watch() {
		const step = this.steps()[this.step];
		if (this.badge_holder && !this.badge_timer && step && step.key === "badge") {
			this.watch_badges(this.badge_holder);
		}
	}

	ago(seconds) {
		if (seconds < 60) return __("{0} s", [seconds]);
		if (seconds < 3600) return __("{0} min", [Math.round(seconds / 60)]);
		if (seconds < 86400) return __("{0} h", [Math.round(seconds / 3600)]);
		return __("{0} d", [Math.round(seconds / 86400)]);
	}

	// ---------------------------------------------------------------- steps

	//// Neoffice — the steps at the top, numbered (the design system's stepper): a done step is a way back.
	stepper_html() {
		const steps = this.steps();
		return `<div class="sew-steps">${steps
			.map((s, i) => {
				const state =
					i < this.step ? "is-done" : i === this.step ? "is-current" : "is-next";
				const rule = i
					? `<div class="sew-rule ${i <= this.step ? "is-done" : ""}"></div>`
					: "";
				const go =
					i < this.step ? ` data-go="${i}" title="${esc(__("Back to this step"))}"` : "";
				return `<button type="button" class="sew-step ${state}"${go}>${rule}<div class="sew-node">${
					i < this.step ? SEW_CHECK : i + 1
				}</div><div class="sew-step-label">${esc(s.label)}</div></button>`;
			})
			.join("")}</div>`;
	}

	//// Neoffice — each step says what it asks, in a Forum title and one line (the access step brings its own).
	step_head(key) {
		const name = this.data.first_name || __("the employee");
		const heads = {
			person: [
				__("Who are you hiring?"),
				__("Their name, how to reach them and their address. The AVS number can wait."),
			],
			job: [
				__("The job of {0}", [name]),
				__("The company, the start date, the activity rate and the salary."),
			],
			tax: [
				__("Permit and tax of {0}", [name]),
				__(
					"The source tax follows from the nationality, the permit and the personal situation.",
				),
			],
			badge: [
				__("The badge of {0}", [name]),
				__("Optional: a badge presented at a terminal clocks them in."),
			],
			review: [
				this.mode === "finish" ? __("Check and finish") : __("Check and create"),
				__("Everything that will be made, in one click."),
			],
		};
		const head = heads[key];
		if (!head) return "";
		return `<div class="sew-head"><h2 class="sew-title">${esc(
			head[0],
		)}</h2><div class="sew-lead">${esc(head[1])}</div></div>`;
	}

	render_step() {
		this.stop_badge_watch();
		const steps = this.steps();
		const step = steps[this.step];
		this.body.empty();
		this.form = null;
		if (this.mode === "finish") {
			//// Neoffice — which record is being finished, and how many wait. Built first (see render_review).
			// A record with a single name has no last name: never print « undefined ».
			const name = [this.data.first_name, this.data.last_name].filter(Boolean).join(" ");
			const who = __("Finishing the record of {0}", [esc(name)]);
			const left = __("{0} records to complete", [this.info.remaining]);
			this.body.append(`<div class="sew-note">${who} · ${left}</div>`);
		}
		this.body.append(this.stepper_html());
		this.body.append(this.step_head(step.key));

		if (step.key === "review") return this.render_review();
		if (step.key === "badge") return this.render_badge();
		if (step.key === "access") return this.render_access();

		const holder = $("<div></div>").appendTo(this.body);
		this.form = new frappe.ui.FieldGroup({
			fields: this.fields_for(step.key),
			body: holder[0],
		});
		this.form.make();
		if (step.key === "job" && !this.data.vacation_days) {
			this.data.vacation_days = this.age_at_year_end() < 20 ? 25 : 20;
		}
		this.form.set_values(this.data);

		if (this.mode === "finish" && step.key === "person") this.render_known(holder);
		if (step.key === "person") this.watch_avs();
		if (step.key === "tax") this.refresh_tax();
		this.render_nav();
	}

	age_at_year_end() {
		if (!this.data.date_of_birth) return 99;
		const year = (this.data.date_of_joining || frappe.datetime.get_today()).slice(0, 4);
		return Number(year) - Number(this.data.date_of_birth.slice(0, 4));
	}

	watch_avs() {
		const avs_field = this.form.get_field("avs_number");
		avs_field.$input.on("change", async () => {
			const value = avs_field.get_value();
			if (!value) return;
			const r = await frappe.xcall(`${WIZARD}.validate_avs_number`, { avs: value });
			if (r.valid) {
				avs_field.set_value(r.formatted);
				avs_field.set_description(
					`<span class="text-success">${__("Valid AVS number")}</span>`,
				);
			} else {
				avs_field.set_description(
					`<span class="text-danger">${__(
						"Invalid AVS number (EAN-13 key mismatch)",
					)}</span>`,
				);
			}
		});
	}

	other_employers_label() {
		const d = this.data;
		if (d.other_activity_basis === "Work Percentage") {
			return __("activity rate {0} %", [d.other_activity_rate || 0]);
		}
		if (d.other_activity_basis === "Gross Income") {
			return __("gross {0} a month", [format_currency(d.other_activity_gross || 0, "CHF")]);
		}
		return __("unknown: extrapolated to 100 %");
	}

	access_summary() {
		const kind = this.access_kind();
		if (kind === "office") return __("An account at the office, with an invitation");
		if (kind === "field") return __("An account in the field, with an invitation");
		return "";
	}

	render_review() {
		const d = this.data;
		const line = (label, value) =>
			value ? `<div>${esc(label)}</div><div>${esc(value)}</div>` : "";
		const structure =
			d.salary_structure ||
			((this.defaults.structures || []).length === 1 && this.defaults.structures[0]);
		const missing = [];
		if (!d.base) missing.push(__("no salary: no payslip until one is recorded"));
		if (!d.iban) missing.push(__("no IBAN: the salary cannot be paid by transfer"));
		if (!d.avs_number) missing.push(__("no AVS number: needed for the declarations"));
		if (!d.address_street) missing.push(__("no address: needed for the salary certificate"));
		const tax = this.tax;
		// Built first: a template literal nested in the summary template hides the __() calls around it
		// from the POT extractor (see render_badge).
		const full_name = `${d.first_name || ""} ${d.last_name || ""}`;
		//// Neoffice — same context as the date_of_joining field above, so the summary and the form agree.
		const start_date_label = __("Start date", null, "employment start date");
		// The colon inside the message: French puts a space before it.
		const later = missing.length
			? `<div class="sew-later">${__("Can be completed later: {0}", [
					missing.map(esc).join(" · "),
			  ])}</div>`
			: "";
		this.body.append(`
			<div class="sew-card">
				<div class="sew-card-title">${__("Summary")}</div>
				<div class="sew-sum">
					${line(__("Name"), full_name)}
					${line(__("Date of Birth"), d.date_of_birth && frappe.datetime.str_to_user(d.date_of_birth))}
					${line(__("E-mail"), d.email)}
					${line(__("Company"), d.company)}
					${line(start_date_label, d.date_of_joining && frappe.datetime.str_to_user(d.date_of_joining))}
					${line(__("Job title"), d.designation)}
					${line(__("Activity rate (%)"), d.work_percentage)}
					${line(__("Gross monthly salary"), d.base && format_currency(d.base, "CHF"))}
					${line(__("Salary structure"), d.base && structure)}
					${line(__("Vacation days a year"), d.vacation_days)}
					${line(__("IBAN of the salary account"), d.iban)}
					${line(__("Source tax"), tax && tax.qst_subject ? __("tariff {0}", [tax.tariff_code]) : __("No"))}
					${line(
						__("Other employers"),
						tax && tax.qst_subject && d.other_employment
							? this.other_employers_label()
							: "",
					)}
					${line(__("Access"), this.access_summary())}
					${line(__("Badge"), this.badge ? __("Badge …{0}", [this.badge.uid_tail]) : "")}
					${line(__("Payslips"), d.email ? __("by e-mail") : __("printed, handed out"))}
				</div>
				${later}
			</div>`);
		this.render_nav(true);
	}

	//// Neoffice — Back on the left, the way forward on the right (the boards): outlined and ink, 44 px high.
	render_nav(is_review = false) {
		const foot = $('<div class="sew-foot"></div>').appendTo(this.body);
		const right = $('<div class="sew-foot-right"></div>');
		if (this.step > 0) {
			$(`<button type="button" class="sew-btn">${__("Back")}</button>`)
				.appendTo(foot)
				.on("click", () => {
					this.collect();
					this.step -= 1;
					this.render_step();
				});
		}
		right.appendTo(foot);
		const nav = right;
		if (this.mode === "finish") {
			$(`<button type="button" class="sew-link">${__("Later")}</button>`)
				.appendTo(nav)
				.on("click", () => this.later());
			$(`<button type="button" class="sew-link">${__("Skip this record")}</button>`)
				.appendTo(nav)
				.on("click", () => this.skip());
		}
		if (!is_review) {
			$(`<button type="button" class="sew-btn primary">${__("Continue")}</button>`)
				.appendTo(nav)
				.on("click", async () => {
					if (!this.collect(true)) return;
					//// Neoffice — the access step stops on what the account would be refused for at the end (10.11: no
					//// e-mail, « an account at the office, with an invitation » in the summary, then the account refused
					//// once the record was made). The theme's chooser says why; « No account » always goes on.
					if (
						this.steps()[this.step].key === "access" &&
						this.access &&
						this.access_kind() !== "none"
					) {
						const problem = this.access.problem();
						if (problem) {
							frappe.msgprint(problem);
							return;
						}
					}
					if (this.steps()[this.step].key === "tax" && !this.tax)
						await this.refresh_tax();
					this.step += 1;
					this.render_step();
				});
		} else if (this.mode === "finish") {
			$(`<button type="button" class="sew-btn primary">${__("Finish the record")}</button>`)
				.appendTo(nav)
				.on("click", () => this.finish());
		} else {
			$(
				`<button type="button" class="sew-btn primary">${__(
					"Create the employee",
				)}</button>`,
			)
				.appendTo(nav)
				.on("click", () => this.create());
		}
	}

	collect(validate = false) {
		if (!this.form) return true;
		if (validate) {
			const missing = this.form.fields
				.filter((f) => f.reqd && !this.form.get_value(f.fieldname))
				.map((f) => f.label);
			if (missing.length) {
				frappe.msgprint(__("Missing required fields: {0}", [missing.join(", ")]));
				return false;
			}
		}
		Object.assign(this.data, this.form.get_values(true));
		return true;
	}

	// ---------------------------------------------------------------- finish
	//// Neoffice — « finish » mode (29.10.2026): the record the theme made for a desk account (a name, a company, a date)
	//// is completed here, with the same steps and the same checks as a hire, instead of being created.
	//// Route: swiss-employee-wizard/<employee>; swiss-employee-wizard/next opens the first record still to complete.

	route_target() {
		const route = frappe.get_route();
		return route[0] === "swiss-employee-wizard" && route[1] ? route[1] : null;
	}

	route_changed() {
		if (this.route_target() === this.current_target) return;
		this.stop_badge_watch();
		this.reset();
		this.start();
	}

	async start_finish(target) {
		if (target === "next") {
			const following = await frappe.xcall(`${WIZARD}.next_employee_to_finish`);
			if (!following) {
				frappe.show_alert({ message: __("No record to finish."), indicator: "green" });
				frappe.set_route("List", "Employee");
				return;
			}
			frappe.set_route("swiss-employee-wizard", following.name);
			return;
		}
		let info;
		try {
			info = await frappe.xcall(`${WIZARD}.employee_to_finish`, { employee: target });
		} catch (e) {
			frappe.set_route("List", "Employee");
			return; // frappe.xcall has shown the server's message
		}
		this.mode = "finish";
		this.employee = target;
		this.info = info;
		this.page.set_title(__("Finish the record"));
		Object.assign(this.data, info.data);
		await this.load_defaults();
		this.step = Math.max(
			0,
			this.steps().findIndex((s) => s.key === info.first_step),
		);
		this.render_step();
	}

	render_known(holder) {
		const known = this.info.known || {};
		const parts = [
			known.account && esc(known.account),
			known.company && esc(known.company),
			known.date_of_joining && esc(frappe.datetime.str_to_user(known.date_of_joining)),
		].filter(Boolean);
		const title = __("Already known from the account");
		holder.prepend(
			`<div class="sew-card" style="margin-bottom: 15px;"><div><b>${title}</b> <span class="text-muted small">· ${parts.join(
				" · ",
			)}</span></div></div>`,
		);
	}

	later() {
		frappe.set_route("List", "Employee");
	}

	async skip() {
		const following = await frappe.xcall(`${WIZARD}.next_employee_to_finish`, {
			after: this.employee,
		});
		if (following) frappe.set_route("swiss-employee-wizard", following.name);
		else this.later();
	}

	async finish() {
		const data = { ...this.tax_data(), qst_subject: this.data.qst_subject };
		if (!data.qst_subject) data.tariff_letter = null;
		else data.tariff_letter = this.data.tariff_letter;
		let res;
		try {
			const r = await frappe.call({
				method: `${WIZARD}.complete_employee`,
				args: { employee: this.employee, data: JSON.stringify(data) },
				freeze: true,
				freeze_message: __("Saving the record…"),
			});
			res = r.message;
		} catch (e) {
			return; // frappe.call has shown the server's message
		}
		if (!res) return;
		let badge_note = "";
		if (this.badge) {
			try {
				await frappe.xcall(`${BADGES}.assign_badge_to_employee`, {
					badge: this.badge.name,
					employee: res.employee,
				});
				badge_note = __("Badge …{0} given: their next swipe clocks them in.", [
					this.badge.uid_tail,
				]);
			} catch (e) {
				badge_note = __("The badge could not be given: give it from their record.");
			}
		}
		this.render_finished(res, badge_note);
	}

	render_finished(res, badge_note) {
		const done = [
			res.structure_assignment && __("Salary recorded ({0})", [res.structure_assignment]),
			res.leave_allocation && __("Vacation of the year allocated"),
			badge_note,
		].filter(Boolean);
		const title = __("{0} is complete", [esc(res.employee_name)]);
		const left = res.remaining
			? __("{0} records to complete", [res.remaining])
			: __("All the records are complete.");
		const list = done
			.map(
				(d) =>
					`<div class="sew-line"><div class="sew-ok">${SEW_CHECK}</div><span>${esc(
						d,
					)}</span></div>`,
			)
			.join("");
		this.body.empty().append(`
			<div class="sew-hero">
				<h2 class="sew-hero-title">${title}</h2>
				<div class="sew-hero-sub">${left}</div>
			</div>
			${list ? `<div class="sew-card">${list}</div>` : ""}
			<div class="sew-actions sew-finished-actions"></div>`);
		const actions = this.body.find(".sew-finished-actions");
		if (res.next) {
			const next_label = __("Next record: {0}", [
				esc(res.next.employee_name || res.next.name),
			]);
			$(`<button type="button" class="sew-btn primary">${next_label}</button>`)
				.appendTo(actions)
				.on("click", () => frappe.set_route("swiss-employee-wizard", res.next.name));
		}
		$(`<button type="button" class="sew-btn">${__("Back to the list")}</button>`)
			.appendTo(actions)
			.on("click", () => this.later());
		$(`<button type="button" class="sew-btn">${__("Open the record")}</button>`)
			.appendTo(actions)
			.on("click", () => frappe.set_route("Form", "Employee", res.employee));
	}

	// ---------------------------------------------------------------- create

	async create() {
		const data = { ...this.tax_data(), qst_subject: this.data.qst_subject };
		if (!data.qst_subject) data.tariff_letter = null;
		else data.tariff_letter = this.data.tariff_letter;
		let res;
		try {
			const r = await frappe.call({
				method: `${WIZARD}.create_employee`,
				args: { data: JSON.stringify(data) },
				freeze: true,
				freeze_message: __("Creating the employee…"),
			});
			res = r.message;
		} catch (e) {
			return; // frappe.call has shown the server's message
		}
		if (!res) return;
		let badge_note = "";
		if (this.badge) {
			try {
				await frappe.xcall(`${BADGES}.assign_badge_to_employee`, {
					badge: this.badge.name,
					employee: res.employee,
				});
				badge_note = __("Badge …{0} given: their next swipe clocks them in.", [
					this.badge.uid_tail,
				]);
			} catch (e) {
				badge_note = __("The badge could not be given: give it from their record.");
			}
		}
		//// Neoffice — the account, once the record exists: the record is never lost to a refusal of the access.
		res.access_lines = [];
		res.access_problem = "";
		if (this.access && this.access_kind() !== "none") {
			try {
				const answer = await neoffice_theme.employee_access.give(
					res.employee,
					this.access,
				);
				if (answer.ok) res.access_lines = neoffice_theme.employee_access.summary(answer);
				else res.access_problem = neoffice_theme.employee_access.refusal(answer);
			} catch (e) {
				res.access_problem = __("The access could not be given.");
			}
		}
		this.render_done(res, badge_note);
	}

	//// Neoffice — the done page of the boards (WizardDone): the person hired in a Forum title on the warm card, then two cards,
	//// the record and their access, each fact with its green check; what went wrong with the access with its amber mark.
	render_done(res, badge_note) {
		const ok = (text) =>
			`<div class="sew-line"><div class="sew-ok">${SEW_CHECK}</div><span>${esc(
				text,
			)}</span></div>`;
		const warn = (text) =>
			`<div class="sew-line"><div class="sew-warn-dot">!</div><span>${esc(
				text,
			)}</span></div>`;
		const record = [
			__("Employee record created"),
			res.structure_assignment && __("Salary recorded ({0})", [res.structure_assignment]),
			res.leave_allocation && __("Vacation of the year allocated"),
			badge_note,
			this.data.email ? __("Payslips by e-mail") : __("Payslips printed, handed out"),
		]
			.filter(Boolean)
			.map(ok)
			.join("");
		let access;
		if (res.access_problem) {
			access =
				warn(res.access_problem) +
				warn(__("The record is created: give the access from their record."));
		} else if ((res.access_lines || []).length) {
			access = res.access_lines.map(ok).join("");
		} else {
			access = warn(__("No account: an access can be given later from their record."));
		}
		const start = this.data.date_of_joining
			? frappe.datetime.str_to_user(this.data.date_of_joining)
			: "";
		const sub = start
			? __("Employee record {0} · starts on {1}", [res.employee, start])
			: __("Employee record {0}", [res.employee]);
		this.body.empty().append(`
			<div class="sew-hero">
				<span class="sew-pill success">${esc(__("Hired"))}</span>
				<h2 class="sew-hero-title">${__("{0} is hired", [esc(res.employee_name)])}</h2>
				<div class="sew-hero-sub">${esc(sub)}</div>
			</div>
			<div class="sew-two">
				<div class="sew-card"><div class="sew-card-title">${esc(__("The record"))}</div>${record}</div>
				<div class="sew-card"><div class="sew-card-title">${esc(__("Their access"))}</div>${access}</div>
			</div>
			<div class="sew-actions">
				<a class="sew-btn primary" href="/app/employee/${encodeURIComponent(res.employee)}">${__(
					"Open their record",
				)}</a>
				<button type="button" class="sew-btn sew-again">${__("Hire someone else")}</button>
				<a class="sew-btn" href="/app/swiss-payroll-cycle">${__("Monthly Payroll")}</a>
			</div>`);
		this.body.find(".sew-again").on("click", async () => {
			this.reset();
			await this.load_defaults();
			this.render_step();
		});
	}
}
