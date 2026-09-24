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
};

frappe.pages["swiss-employee-wizard"].on_page_hide = function (wrapper) {
	wrapper.wizard && wrapper.wizard.stop_badge_watch();
};

const CANTONS = [
	"AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
	"NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH",
]; // prettier-ignore
const WIZARD = "hrms.regional.switzerland.employee_wizard";
const BADGES = "neoffice_theme.badge_assignment";
const esc = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

class SwissEmployeeWizard {
	constructor(page) {
		this.page = page;
		this.step = 0;
		this.body = $('<div style="max-width: 820px; padding: 15px 0;"></div>').appendTo(
			this.page.main,
		);
		// The badge step exists where the terminals do (the Neoffice theme).
		// The badge step needs neoffice_theme and a terminal that is on: its boot flag says both. A theme
		// that does not set the flag yet (it ships separately) keeps the step wherever it is installed.
		this.with_badges =
			frappe.boot.neoffice_bornes === undefined
				? !!(frappe.boot.versions && frappe.boot.versions.neoffice_theme)
				: !!frappe.boot.neoffice_bornes;
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
		this.tax = null;
	}

	async start() {
		const genders = await frappe.db.get_list("Gender", { fields: ["name"], limit: 20 });
		this.genders = genders.map((g) => g.name);
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
			...(this.with_badges ? [{ key: "badge", label: __("Badge") }] : []),
			{ key: "review", label: __("Check and create") },
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
					label: __("Start date"),
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
					fieldtype: "Int",
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
						{ value: "Single", label: __("Single") },
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
		return `<div class="frappe-card" style="padding: 10px 14px;">
			<b>${__("Source tax: tariff {0}", [esc(tax.tariff_code)])}</b>
			${model ? `<span class="text-muted"> · ${esc(model)}</span>` : ""}
			<div class="text-muted small" style="margin-top: 4px;">${(tax.notes || [])
				.map(esc)
				.join("<br>")}</div>${warn}
		</div>`;
	}

	// ---------------------------------------------------------------- badge

	render_badge() {
		const holder = $('<div class="sew-badge"></div>').appendTo(this.body);
		holder.html(`
			<div style="margin-bottom: 12px;">${__(
				"Have {0} present their badge at a terminal: it appears below within a few seconds. Choose it, and their next swipe clocks them in.",
				[`<b>${esc(this.data.first_name || __("the employee"))}</b>`],
			)}</div>
			<div class="sew-terminals text-muted small" style="margin-bottom: 10px;"></div>
			<div class="sew-badges"></div>
			<label style="margin-top: 12px; display: flex; gap: 8px; align-items: center; font-weight: normal;">
				<input type="radio" name="sew-badge" value="" ${this.badge ? "" : "checked"}>
				${__("No badge for now")}
			</label>`);
		holder.on("change", "input[name=sew-badge]", (e) => {
			const value = $(e.currentTarget).val();
			this.badge = value ? (this.badge_rows || []).find((b) => b.name === value) : null;
		});
		this.watch_badges(holder);
		this.render_nav();
	}

	watch_badges(holder) {
		this.stop_badge_watch();
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
						<label class="frappe-card" style="display: flex; gap: 10px; align-items: center; padding: 10px 14px; margin-bottom: 6px; font-weight: normal; ${
							b.recent ? "border-color: var(--primary);" : ""
						}">
							<input type="radio" name="sew-badge" value="${esc(b.name)}" ${chosen === b.name ? "checked" : ""}>
							<span style="flex: 1;"><b>${__("Badge …{0}", [esc(b.uid_tail)])}</b>
								<span class="text-muted small"> · ${
									b.seen_ago == null
										? ""
										: __("presented {0} ago", [this.ago(b.seen_ago)])
								}${b.borne ? " · " + esc(b.borne) : ""}</span></span>
							${b.recent ? `<span class="indicator-pill green">${__("recent")}</span>` : ""}
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

	ago(seconds) {
		if (seconds < 60) return __("{0} s", [seconds]);
		if (seconds < 3600) return __("{0} min", [Math.round(seconds / 60)]);
		if (seconds < 86400) return __("{0} h", [Math.round(seconds / 3600)]);
		return __("{0} d", [Math.round(seconds / 86400)]);
	}

	// ---------------------------------------------------------------- steps

	render_step() {
		this.stop_badge_watch();
		const steps = this.steps();
		const step = steps[this.step];
		const progress = steps
			.map(
				(s, i) => `
				<span class="indicator-pill ${i < this.step ? "green" : i === this.step ? "blue" : "gray"}"
					style="margin-right: 6px;">${i + 1}. ${esc(s.label)}</span>`,
			)
			.join("");
		this.body.empty();
		this.form = null;
		this.body.append(
			`<div class="sew-progress" style="margin-bottom: 20px;">${progress}</div>`,
		);

		if (step.key === "review") return this.render_review();
		if (step.key === "badge") return this.render_badge();

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

	render_review() {
		const d = this.data;
		const line = (label, value) =>
			value
				? `<tr><td class="text-muted" style="width: 40%;">${esc(label)}</td><td>${esc(
						value,
				  )}</td></tr>`
				: "";
		const structure =
			d.salary_structure ||
			((this.defaults.structures || []).length === 1 && this.defaults.structures[0]);
		const missing = [];
		if (!d.base) missing.push(__("no salary: no payslip until one is recorded"));
		if (!d.iban) missing.push(__("no IBAN: the salary cannot be paid by transfer"));
		if (!d.avs_number) missing.push(__("no AVS number: needed for the declarations"));
		if (!d.address_street) missing.push(__("no address: needed for the salary certificate"));
		const tax = this.tax;
		this.body.append(`
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Summary")}</h5>
				<table class="table table-sm">
					${line(__("Name"), `${d.first_name || ""} ${d.last_name || ""}`)}
					${line(__("Date of Birth"), d.date_of_birth && frappe.datetime.str_to_user(d.date_of_birth))}
					${line(__("E-mail"), d.email)}
					${line(__("Company"), d.company)}
					${line(__("Start date"), d.date_of_joining && frappe.datetime.str_to_user(d.date_of_joining))}
					${line(__("Job title"), d.designation)}
					${line(__("Activity rate (%)"), d.work_percentage)}
					${line(__("Gross monthly salary"), d.base && format_currency(d.base, "CHF"))}
					${line(__("Salary structure"), d.base && structure)}
					${line(__("Vacation days a year"), d.vacation_days)}
					${line(__("IBAN of the salary account"), d.iban)}
					${line(__("Source tax"), tax && tax.qst_subject ? __("tariff {0}", [tax.tariff_code]) : __("No"))}
					${line(__("Badge"), this.badge ? __("Badge …{0}", [this.badge.uid_tail]) : "")}
					${line(__("Payslips"), d.email ? __("by e-mail") : __("printed, handed out"))}
				</table>
				${
					missing.length
						? `<div class="text-warning small">${__(
								"Can be completed later",
						  )}: ${missing.map(esc).join(" · ")}</div>`
						: ""
				}
			</div>`);
		this.render_nav(true);
	}

	render_nav(is_review = false) {
		const nav = $('<div style="margin-top: 20px; display: flex; gap: 10px;"></div>').appendTo(
			this.body,
		);
		if (this.step > 0) {
			$(`<button class="btn btn-default btn-sm">${__("Back")}</button>`)
				.appendTo(nav)
				.on("click", () => {
					this.collect();
					this.step -= 1;
					this.render_step();
				});
		}
		if (!is_review) {
			$(`<button class="btn btn-primary btn-sm">${__("Next")}</button>`)
				.appendTo(nav)
				.on("click", async () => {
					if (!this.collect(true)) return;
					if (this.steps()[this.step].key === "tax" && !this.tax)
						await this.refresh_tax();
					this.step += 1;
					this.render_step();
				});
		} else {
			$(`<button class="btn btn-primary btn-sm">${__("Create the employee")}</button>`)
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
		this.render_done(res, badge_note);
	}

	render_done(res, badge_note) {
		const done = [
			__("Employee record created"),
			res.structure_assignment && __("Salary recorded ({0})", [res.structure_assignment]),
			res.leave_allocation && __("Vacation of the year allocated"),
			badge_note,
			this.data.email && __("Payslips by e-mail"),
		].filter(Boolean);
		this.body.empty().append(`
			<div class="frappe-card" style="padding: 20px;">
				<h4 style="margin-top: 0;">${__("{0} is hired", [esc(res.employee_name)])}</h4>
				<ul style="margin-bottom: 16px;">${done.map((d) => `<li>${esc(d)}</li>`).join("")}</ul>
				<div style="display: flex; gap: 10px; flex-wrap: wrap;">
					<a class="btn btn-primary btn-sm" href="/app/employee/${encodeURIComponent(res.employee)}">${__(
						"Open their record",
					)}</a>
					<button class="btn btn-default btn-sm sew-again">${__("Hire someone else")}</button>
					<a class="btn btn-default btn-sm" href="/app/swiss-payroll-cycle">${__("Monthly Payroll")}</a>
				</div>
			</div>`);
		this.body.find(".sew-again").on("click", async () => {
			this.reset();
			await this.load_defaults();
			this.render_step();
		});
	}
}
