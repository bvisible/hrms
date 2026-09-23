//// Neoffice — added file (no upstream equivalent): the company payroll setup wizard, first step
//// of the Swiss payroll onboarding. It asks the choices the payroll otherwise takes silently
//// (booking method, third-party allowances, accounts, insurance rates, certificate header) and
//// writes them to the Company and its default social insurance configuration.
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.pages["swiss-company-payroll-setup"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Company Payroll Setup"),
		single_column: true,
	});
	wrapper.setup_wizard = new SwissCompanyPayrollSetup(page);
};

const SWISS_CANTONS = [
	"AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE",
	"NW", "OW", "SG", "SH", "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH",
]; // prettier-ignore

class SwissCompanyPayrollSetup {
	constructor(page) {
		this.page = page;
		this.data = {};
		this.step = 0;
		this.steps = [
			{ key: "company", label: __("Company") },
			{ key: "insurances", label: __("Social insurances") },
			{ key: "accounting", label: __("Accounting") },
			{ key: "certificate", label: __("Salary certificate") },
			{ key: "review", label: __("Review & apply") },
		];
		this.body = $('<div style="max-width: 820px; padding: 15px 0;"></div>').appendTo(
			this.page.main
		);
		this.load(frappe.defaults.get_user_default("Company"));
	}

	async load(company) {
		if (!company) {
			this.render_step();
			return;
		}
		const r = await frappe.call({
			method: "hrms.regional.switzerland.company_setup.get_company_setup",
			args: { company },
		});
		this.data = r.message || { company };
		this.data.has_expense_regulation = this.data.lohnausweis_expense_regulation_canton ? 1 : 0;
		this.render_step();
	}

	account_query(extra = {}) {
		return () => ({ filters: { company: this.data.company, is_group: 0, ...extra } });
	}

	fields_for(key) {
		if (key === "company") {
			return [
				{
					fieldname: "company",
					label: __("Company"),
					fieldtype: "Link",
					options: "Company",
					reqd: 1,
					change: () => {
						const company = this.form.get_value("company");
						if (company && company !== this.data.company) this.load(company);
					},
				},
				{
					fieldname: "canton",
					label: __("Canton of the company's seat"),
					fieldtype: "Select",
					options: ["", ...SWISS_CANTONS],
					reqd: 1,
					description: __(
						"The social insurance configuration is kept per canton; this one becomes the company's default."
					),
				},
				{
					fieldname: "ch_uid_bfs",
					label: __("UID number"),
					fieldtype: "Data",
					description: __("CHE-123.456.789, on the salary certificate barcode and the declarations."),
				},
				{ fieldname: "col1", fieldtype: "Column Break" },
				{
					fieldname: "lohnausweis_employer_name",
					label: __("Employer name on the salary certificate"),
					fieldtype: "Data",
				},
				{
					fieldname: "lohnausweis_employer_address",
					label: __("Employer address on the salary certificate"),
					fieldtype: "Small Text",
					description: __("Street, then ZIP and city. Printed in box I."),
				},
				{
					fieldname: "sec_contact",
					fieldtype: "Section Break",
					label: __("Person in charge of the payroll"),
					description: __(
						"Printed in box I of the salary certificate with the phone number, and given in the Swissdec declarations."
					),
				},
				{ fieldname: "ch_contact_person", label: __("Name"), fieldtype: "Data" },
				{ fieldname: "col2", fieldtype: "Column Break" },
				{ fieldname: "ch_contact_phone", label: __("Phone"), fieldtype: "Data" },
				{ fieldname: "ch_contact_email", label: __("Email"), fieldtype: "Data", options: "Email" },
			];
		}
		if (key === "insurances") {
			const rate = (fieldname, label, description) => ({
				fieldname,
				label,
				fieldtype: "Percent",
				description,
			});
			return [
				{ fieldname: "sec_avs", fieldtype: "Section Break", label: __("AVS compensation fund") },
				rate(
					"avs_admin_fee_rate",
					__("Administration fees (%)"),
					__(
						"Charged by your compensation fund on the AVS/AI/APG contributions (see its invoice). 0 if it charges none."
					)
				),
				{ fieldname: "col_avs", fieldtype: "Column Break" },
				rate(
					"family_allowance_rate",
					__("Family allowances contribution (%)"),
					__("Employer contribution to the family allowance fund (CAF), on the AVS salary.")
				),
				{
					fieldname: "sec_laa",
					fieldtype: "Section Break",
					label: __("Accident insurance (LAA) and supplementary (LAAC)"),
					description: __("Rates of your policies. The insured salary cap is applied for you."),
				},
				rate("laa_professional_rate", __("Occupational accidents, employer (%)")),
				rate("laa_nonprofessional_rate", __("Non-occupational accidents, employee (%)")),
				{ fieldname: "col_laa", fieldtype: "Column Break" },
				rate("laac_rate_employee", __("LAAC, employee (%)")),
				rate("laac_rate_employer", __("LAAC, employer (%)")),
				{
					fieldname: "sec_ijm",
					fieldtype: "Section Break",
					label: __("Daily sickness allowance (IJM) and pension fund (LPP)"),
				},
				rate("ijm_rate_employee", __("IJM, employee (%)")),
				rate("ijm_rate_employer", __("IJM, employer (%)")),
				{ fieldname: "col_ijm", fieldtype: "Column Break" },
				rate(
					"lpp_employer_share_pct",
					__("Employer share of the LPP contributions (%)"),
					__("At least 50 % by law; more if your pension fund's regulations say so.")
				),
				{ fieldname: "sec_payroll", fieldtype: "Section Break", label: __("Payroll") },
				{
					fieldname: "thirteenth_month_mode",
					label: __("13th month salary"),
					fieldtype: "Select",
					options: [
						{ value: "Disabled", label: __("None") },
						{ value: "Annual", label: __("Paid once a year") },
						{ value: "Monthly", label: __("Paid monthly (1/12 each month)") },
					],
				},
				{ fieldname: "col_payroll", fieldtype: "Column Break" },
				{
					fieldname: "qst_enabled",
					label: __("Some employees are taxed at source"),
					fieldtype: "Check",
				},
				{
					fieldname: "qst_default_canton",
					label: __("Default canton of taxation"),
					fieldtype: "Select",
					options: ["", ...SWISS_CANTONS],
					depends_on: "eval:doc.qst_enabled",
				},
			];
		}
		if (key === "accounting") {
			return [
				{
					fieldname: "ch_payroll_booking_method",
					label: __("How are the social charges booked?"),
					fieldtype: "Select",
					reqd: 1,
					options: [
						{ value: "Social Insurance Liability", label: __("Social Insurance Liability") },
						{ value: "Social Charges", label: __("Social Charges") },
					],
				},
				{
					fieldname: "booking_help",
					fieldtype: "HTML",
					options: `<div class="text-muted small" style="margin: -6px 0 14px;">
						<p><b>${__("Social Insurance Liability")}</b> — ${__(
							"every month the employee deductions and the employer contributions are credited to the insurers' accounts (2270-2274) and the employer contributions charged (5700-5799); the insurers' invoices then settle those accounts. The charges are right every month. Recommended with a payroll software."
						)}</p>
						<p><b>${__("Social Charges")}</b> — ${__(
							"the employee deductions are credited to the charge accounts (5700-5799) and the employer contributions are not booked monthly: the insurers' invoices are charged in full when paid. Simpler for a small company, the charges are right once the invoices are booked."
						)}</p></div>`,
				},
				{
					fieldname: "ch_third_party_allowance_booking",
					label: __("Allowances the employer pays out for an insurer"),
					fieldtype: "Select",
					reqd: 1,
					options: [
						{ value: "Salaries", label: __("With the salaries (5000)") },
						{ value: "Insurer Receivable", label: __("As a receivable from the insurer (1180)") },
					],
					description: __(
						"APG, maternity, accident, sickness, short-time work: with the salaries, the insurer's reimbursement is credited back there; as a receivable, the balance sheet shows what each insurer still owes."
					),
				},
				{
					fieldname: "ch_third_party_allowance_account",
					label: __("Receivable account"),
					fieldtype: "Link",
					options: "Account",
					depends_on: "eval:doc.ch_third_party_allowance_booking == 'Insurer Receivable'",
					get_query: this.account_query({ root_type: "Asset" }),
				},
				{ fieldname: "col_acc", fieldtype: "Column Break" },
				{
					fieldname: "default_payroll_payable_account",
					label: __("Salary transit account (net pay)"),
					fieldtype: "Link",
					options: "Account",
					get_query: this.account_query(),
					description: __("Usually 1091: credited with the net salaries, cleared by the payment."),
				},
				{
					fieldname: "payment_account",
					label: __("Bank account paying the salaries"),
					fieldtype: "Link",
					options: "Account",
					get_query: this.account_query({ account_type: "Bank" }),
				},
				{ fieldname: "payment_iban", label: __("IBAN of that account"), fieldtype: "Data" },
				{ fieldname: "payment_bic", label: __("BIC"), fieldtype: "Data" },
				{ fieldname: "sec_accounts", fieldtype: "Section Break" },
				{
					fieldname: "configure_accounts",
					label: __("Assign the other payroll accounts from the chart of accounts"),
					fieldtype: "Check",
					description: __(
						"Salaries, social charges and insurers' accounts of each salary component, picked by number and name. An account already chosen is never replaced."
					),
				},
			];
		}
		if (key === "certificate") {
			return [
				{
					fieldname: "has_expense_regulation",
					label: __("The canton approved our expense regulation"),
					fieldtype: "Check",
					description: __(
						"Then only the lump-sum expenses are declared on the salary certificates, box 15 says so, and 13.1.1 gets no cross."
					),
				},
				{
					fieldname: "lohnausweis_expense_regulation_canton",
					label: __("Approved by the canton"),
					fieldtype: "Select",
					options: ["", ...SWISS_CANTONS],
					depends_on: "eval:doc.has_expense_regulation",
				},
				{
					fieldname: "lohnausweis_expense_regulation_date",
					label: __("Approved on"),
					fieldtype: "Date",
					depends_on: "eval:doc.has_expense_regulation",
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
		if (this.step === 0) {
			this.body.append(
				`<p class="text-muted" style="margin-bottom: 16px;">${__(
					"The choices the payroll needs before its first run. Everything can be changed later by running this setup again."
				)}</p>`
			);
		}

		if (step.key === "review") {
			this.render_review();
			return;
		}

		const holder = $("<div></div>").appendTo(this.body);
		this.form = new frappe.ui.FieldGroup({
			fields: this.fields_for(step.key),
			body: holder[0],
		});
		this.form.make();
		this.form.set_values(this.data);
		this.render_nav();
	}

	render_review() {
		const d = this.data;
		const text = (value) => (value ? frappe.utils.escape_html(String(value)) : "—");
		const pct = (value) => (value ? `${flt(value)} %` : "—");
		const line = (label, value) =>
			`<tr><td class="text-muted" style="width: 45%;">${label}</td><td>${value}</td></tr>`;
		const option = (field, value) => {
			const df = (this.all_fields || []).find((f) => f.fieldname === field);
			const match = df && (df.options || []).find((o) => o.value === value);
			return text(match ? match.label : value);
		};
		this.all_fields = [
			...this.fields_for("insurances"),
			...this.fields_for("accounting"),
		];
		this.body.append(`
			<div class="frappe-card" style="padding: 15px; margin-bottom: 15px;">
				<h5>${__("Summary")}</h5>
				<table class="table table-sm">
					${line(__("Company"), text(d.company))}
					${line(__("Canton of the company's seat"), text(d.canton))}
					${line(__("UID number"), text(d.ch_uid_bfs))}
					${line(__("Person in charge of the payroll"), text([d.ch_contact_person, d.ch_contact_phone].filter(Boolean).join(", ")))}
					${line(__("Administration fees (%)"), pct(d.avs_admin_fee_rate))}
					${line(__("Occupational accidents, employer (%)"), pct(d.laa_professional_rate))}
					${line(__("Non-occupational accidents, employee (%)"), pct(d.laa_nonprofessional_rate))}
					${line(__("IJM, employee (%)"), pct(d.ijm_rate_employee))}
					${line(__("Family allowances contribution (%)"), pct(d.family_allowance_rate))}
					${line(__("13th month salary"), option("thirteenth_month_mode", d.thirteenth_month_mode))}
					${line(__("Some employees are taxed at source"), d.qst_enabled ? __("Yes") : __("No"))}
					${line(__("How are the social charges booked?"), option("ch_payroll_booking_method", d.ch_payroll_booking_method))}
					${line(__("Allowances the employer pays out for an insurer"), option("ch_third_party_allowance_booking", d.ch_third_party_allowance_booking))}
					${line(__("Salary transit account (net pay)"), text(d.default_payroll_payable_account))}
					${line(__("Bank account paying the salaries"), text([d.payment_account, d.payment_iban].filter(Boolean).join(" — ")))}
					${line(__("The canton approved our expense regulation"), d.has_expense_regulation ? text(`${d.lohnausweis_expense_regulation_canton || ""} ${d.lohnausweis_expense_regulation_date ? frappe.datetime.str_to_user(d.lohnausweis_expense_regulation_date) : ""}`) : __("No"))}
				</table>
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
				.on("click", () => {
					if (!this.collect(true)) return;
					this.step += 1;
					this.render_step();
				});
		} else {
			$(`<button class="btn btn-primary btn-sm">${__("Apply")}</button>`)
				.appendTo(nav)
				.on("click", () => this.apply());
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
		if (this.steps[this.step].key === "certificate" && !this.data.has_expense_regulation) {
			this.data.lohnausweis_expense_regulation_canton = "";
			this.data.lohnausweis_expense_regulation_date = null;
		}
		return true;
	}

	async apply() {
		const r = await frappe.call({
			method: "hrms.regional.switzerland.company_setup.apply_company_setup",
			type: "POST",
			args: { data: JSON.stringify(this.data) },
			freeze: true,
			freeze_message: __("Saving the payroll setup..."),
		});
		const res = r.message || {};
		const list = (items) =>
			(items || []).map((item) => `<li>${frappe.utils.escape_html(item)}</li>`).join("");
		let message = `<p>${__("Default social insurance configuration: {0}", [
			`<a href="/app/swiss-social-insurance-config/${encodeURIComponent(res.config)}">${frappe.utils.escape_html(res.config)}</a>`,
		])}</p>`;
		if (res.accounts) {
			if (res.accounts.set.length) {
				message += `<p>${__("Accounts assigned")}:</p><ul>${list(res.accounts.set)}</ul>`;
			}
			if (res.accounts.missing.length) {
				message += `<p class="text-warning">${__(
					"No account found in the chart for"
				)}:</p><ul>${list(res.accounts.missing)}</ul>`;
			}
		}
		message += `<p><a href="/app/swiss-payroll-cycle">${__("Go to the monthly payroll cycle")}</a></p>`;
		frappe.msgprint({ title: __("Payroll setup saved"), message, indicator: "green" });
		this.load(this.data.company);
		this.step = 0;
	}
}
