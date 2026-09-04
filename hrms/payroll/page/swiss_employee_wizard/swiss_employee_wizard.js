//// Neoffice — added file (no upstream equivalent): desk page driving the Swiss employee creation
//// wizard (AVS number, permit, canton, source-tax tariff suggestion).
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.pages["swiss-employee-wizard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Swiss Employee Wizard"),
		single_column: true,
	});
	wrapper.wizard = new SwissEmployeeWizard(page);
};

class SwissEmployeeWizard {
	constructor(page) {
		this.page = page;
		this.data = {};
		this.step = 0;
		this.steps = [
			{ key: "identity", label: __("Identity") },
			{ key: "engagement", label: __("Engagement") },
			{ key: "status", label: __("Permit & residence") },
			{ key: "qst", label: __("Source tax") },
			{ key: "review", label: __("Review & create") },
		];
		this.body = $('<div style="max-width: 760px; padding: 15px 0;"></div>').appendTo(
			this.page.main
		);
		this.render_step();
	}

	// ---------------------------------------------------------------- //

	fields_for(key) {
		if (key === "identity") {
			return [
				{ fieldname: "first_name", label: __("First Name"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "last_name", label: __("Last Name"), fieldtype: "Data", reqd: 1 },
				{ fieldname: "col1", fieldtype: "Column Break" },
				{
					fieldname: "gender",
					label: __("Gender"),
					fieldtype: "Link",
					options: "Gender",
					reqd: 1,
				},
				{
					fieldname: "date_of_birth",
					label: __("Date of Birth"),
					fieldtype: "Date",
					reqd: 1,
				},
				{
					fieldname: "avs_number",
					label: __("AVS Number (756.XXXX.XXXX.XX)"),
					fieldtype: "Data",
					description: __("Checked against the EAN-13 key while you type."),
				},
			];
		}
		if (key === "engagement") {
			return [
				{
					fieldname: "company",
					label: __("Company"),
					fieldtype: "Link",
					options: "Company",
					default: frappe.defaults.get_user_default("Company"),
					reqd: 1,
				},
				{
					fieldname: "date_of_joining",
					label: __("Date of Joining"),
					fieldtype: "Date",
					reqd: 1,
				},
				{
					fieldname: "work_percentage",
					label: __("Activity rate (%)"),
					fieldtype: "Percent",
					default: 100,
				},
				{ fieldname: "col2", fieldtype: "Column Break" },
				{
					fieldname: "holiday_list",
					label: __("Holiday List"),
					fieldtype: "Link",
					options: "Holiday List",
				},
				{
					fieldname: "salary_structure",
					label: __("Salary Structure (optional)"),
					fieldtype: "Link",
					options: "Salary Structure",
				},
				{
					fieldname: "base",
					label: __("Base monthly salary"),
					fieldtype: "Currency",
					depends_on: "salary_structure",
				},
			];
		}
		if (key === "status") {
			return [
				{
					fieldname: "permit_type",
					label: __("Permit type"),
					fieldtype: "Select",
					options: [
						"",
						"Swiss Citizen",
						"Permit C (Settlement)",
						"Permit B (Residence)",
						"Permit G (Cross-border)",
						"Permit L (Short-term)",
					].join("\n"),
					reqd: 1,
				},
				{
					fieldname: "nationality",
					label: __("Nationality"),
					fieldtype: "Link",
					options: "Country",
				},
				{
					fieldname: "canton",
					label: __("Work canton"),
					fieldtype: "Select",
					options: "\nAG\nAI\nAR\nBE\nBL\nBS\nFR\nGE\nGL\nGR\nJU\nLU\nNE\nNW\nOW\nSG\nSH\nSO\nSZ\nTG\nTI\nUR\nVD\nVS\nZG\nZH",
					reqd: 1,
				},
				{ fieldname: "col3", fieldtype: "Column Break" },
				{
					fieldname: "is_cross_border",
					label: __("Cross-border commuter"),
					fieldtype: "Check",
				},
				{
					fieldname: "residence_country",
					label: __("Country of residence"),
					fieldtype: "Select",
					options: "\nDE\nFR\nIT\nAT\nLI",
					depends_on: "is_cross_border",
				},
				{
					fieldname: "de_gre1",
					label: __("Gre-1 attestation (Germany)"),
					fieldtype: "Check",
					depends_on: 'eval:doc.residence_country=="DE"',
				},
				{
					fieldname: "fr_2041as",
					label: __("2041-AS attestation (France)"),
					fieldtype: "Check",
					depends_on: 'eval:doc.residence_country=="FR"',
				},
				{
					fieldname: "it_new_frontalier",
					label: __("New Italian frontalier (from 17.07.2023)"),
					fieldtype: "Check",
					depends_on: 'eval:doc.residence_country=="IT"',
				},
				{
					fieldname: "cross_border_start_date",
					label: __("Cross-border status since"),
					fieldtype: "Date",
					depends_on: "is_cross_border",
				},
			];
		}
		if (key === "qst") {
			return [
				{
					fieldname: "qst_subject",
					label: __("Subject to source tax"),
					fieldtype: "Check",
				},
				{
					fieldname: "tariff_letter",
					label: __("Tariff letter"),
					fieldtype: "Select",
					options: "\nA\nB\nC\nE\nG\nH\nL\nM\nN\nP\nQ\nR\nS\nT\nU",
					depends_on: "qst_subject",
				},
				{ fieldname: "col4", fieldtype: "Column Break" },
				{
					fieldname: "num_children",
					label: __("Children (tax)"),
					fieldtype: "Int",
					depends_on: "qst_subject",
				},
				{
					fieldname: "church_tax",
					label: __("Church tax"),
					fieldtype: "Check",
					depends_on: "qst_subject",
				},
			];
		}
		return [];
	}

	render_step() {
		const step = this.steps[this.step];
		const progress = this.steps
			.map(
				(s, i) => `
				<span class="indicator-pill ${i < this.step ? "green" : i === this.step ? "blue" : "gray"}"
					style="margin-right: 6px;">${i + 1}. ${s.label}</span>`
			)
			.join("");
		this.body.empty();
		this.body.append(`<div style="margin-bottom: 20px;">${progress}</div>`);

		if (step.key === "review") {
			this.render_review();
			return;
		}

		const holder = $('<div></div>').appendTo(this.body);
		this.form = new frappe.ui.FieldGroup({
			fields: this.fields_for(step.key),
			body: holder[0],
		});
		this.form.make();
		this.form.set_values(this.data);

		// Live AVS checksum feedback
		if (step.key === "identity") {
			const avs_field = this.form.get_field("avs_number");
			avs_field.$input.on("change", async () => {
				const value = avs_field.get_value();
				if (!value) return;
				const r = await frappe.call({
					method: "hrms.regional.switzerland.employee_wizard.validate_avs_number",
					args: { avs: value },
				});
				if (r.message.valid) {
					avs_field.set_value(r.message.formatted);
					avs_field.set_description(`<span class="text-success">${__("Valid AVS number")}</span>`);
				} else {
					avs_field.set_description(
						`<span class="text-danger">${__("Invalid AVS number (EAN-13 key mismatch)")}</span>`
					);
				}
			});
		}

		this.render_nav();
	}

	async render_review() {
		// Ask the server for the source-tax reading of the collected data
		const r = await frappe.call({
			method: "hrms.regional.switzerland.employee_wizard.suggest_source_tax",
			args: { data: JSON.stringify(this.data) },
		});
		const suggestion = r.message;

		const line = (label, value) =>
			value
				? `<tr><td class="text-muted" style="width: 40%;">${label}</td><td>${frappe.utils.escape_html(String(value))}</td></tr>`
				: "";
		const notes = (suggestion.notes || [])
			.map((n) => `<div class="indicator-pill blue" style="margin: 2px 6px 2px 0;">${frappe.utils.escape_html(n)}</div>`)
			.join("");

		this.body.append(`
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Summary")}</h5>
				<table class="table table-sm">
					${line(__("Name"), `${this.data.first_name || ""} ${this.data.last_name || ""}`)}
					${line(__("AVS Number"), this.data.avs_number)}
					${line(__("Company"), this.data.company)}
					${line(__("Date of Joining"), this.data.date_of_joining)}
					${line(__("Permit type"), this.data.permit_type)}
					${line(__("Work canton"), this.data.canton)}
					${line(__("Cross-border"), this.data.is_cross_border ? __("Yes") : "")}
					${line(__("Source tax"), this.data.qst_subject ? `${suggestion.tariff_code} (${suggestion.model === "annual" ? __("annual model") : __("monthly model")})` : __("No"))}
					${line(__("Salary Structure (optional)"), this.data.salary_structure)}
					${line(__("Base monthly salary"), this.data.base)}
				</table>
				<div style="display: flex; flex-wrap: wrap;">${notes}</div>
				${
					suggestion.tariff_available === false
						? `<div class="indicator-pill red" style="margin-top: 6px;">${__("QST tariff data missing for this canton/code")}</div>`
						: ""
				}
			</div>`);
		this.render_nav(true);
	}

	render_nav(is_review = false) {
		const nav = $('<div style="margin-top: 20px; display: flex; gap: 10px;"></div>').appendTo(
			this.body
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
					// After the permit step, prefill the source-tax step
					if (this.steps[this.step].key === "status") {
						const r = await frappe.call({
							method: "hrms.regional.switzerland.employee_wizard.suggest_source_tax",
							args: { data: JSON.stringify(this.data) },
						});
						this.data.qst_subject = r.message.qst_subject ? 1 : 0;
						if (!this.data.tariff_letter && r.message.suggested_letter) {
							this.data.tariff_letter = r.message.suggested_letter;
						}
					}
					this.step += 1;
					this.render_step();
				});
		} else {
			$(`<button class="btn btn-primary btn-sm">${__("Create employee")}</button>`)
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

	async create() {
		try {
			const r = await frappe.call({
				method: "hrms.regional.switzerland.employee_wizard.create_employee",
				args: { data: JSON.stringify(this.data) },
				freeze: true,
				freeze_message: __("Creating employee..."),
			});
			const res = r.message;
			frappe.msgprint({
				title: __("Employee created"),
				message:
					`<a href="/app/employee/${encodeURIComponent(res.employee)}">${frappe.utils.escape_html(res.employee_name)}</a>` +
					(res.structure_assignment
						? `<br>${__("Structure assigned")}: ${frappe.utils.escape_html(res.structure_assignment)}`
						: ""),
				indicator: "green",
			});
			this.data = {};
			this.step = 0;
			this.render_step();
		} catch (e) {
			// frappe.call already surfaced the server message
		}
	}
}
