//// Neoffice — added file (no upstream equivalent): desk form of the Swiss Salary Certificate
//// (populate from salary slips, send to the employee, print Form 11).
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

//// Neoffice — the form hero's Send pill (frappe fork, form_hero.js) mails the certificate to the
//// employee instead of opening the generic composer: the PDF in the certificate's language,
//// password-protected like the salary slips when Payroll Settings ask for it, and the date it
//// left recorded on the certificate — the hero's "Sent to employee" step.
if (frappe.ui.form.set_hero_send_action) {
	frappe.ui.form.set_hero_send_action("Swiss Salary Certificate", (frm) => ({
		label: frm.doc.sent_to_employee_on ? __("Resend") : __("Send to employee"),
		icon: "mail",
		primary: !frm.doc.sent_to_employee_on,
		run: () => send_to_employee(frm),
	}));
}

frappe.ui.form.on("Swiss Salary Certificate", {
	setup(frm) {
		// The remarks of box 15 exist in the four languages of the Swissdec standard remarks.
		frm.set_query("language", () => ({ filters: { name: ["in", ["fr", "de", "it", "en"]] } }));
	},

	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.employee && frm.doc.fiscal_year) {
			const populated = !!frm.doc.remark_facts;
			frm.add_custom_button(
				populated ? __("Update from Salary Slips") : __("Populate from Salary Slips"),
				() => populate(frm)
			);
			if (!populated && !frm.is_new()) {
				frm.set_intro(__("Fill the certificate from the submitted salary slips of the year."), "blue");
			}
		}

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				frm.doc.sent_to_employee_on ? __("Resend to Employee") : __("Send to Employee"),
				() => send_to_employee(frm),
				__("Actions")
			);
			frm.add_custom_button(
				__("Preview Barcode"),
				function () {
					frappe.call({
						method: "get_barcode_data",
						doc: frm.doc,
						freeze: true,
						freeze_message: __("Generating barcode..."),
						callback: function (r) {
							if (r.message) {
								show_barcode_dialog(frm, r.message);
							}
						},
					});
				},
				__("Actions")
			);
			if (frm.doc.sent_to_employee_on) {
				frm.set_intro(
					__("Sent to {0} on {1}.", [
						frappe.utils.escape_html(frm.doc.sent_to || ""),
						frappe.datetime.str_to_user(frm.doc.sent_to_employee_on),
					]),
					"green"
				);
			}
		}
	},
});

function populate(frm) {
	frm.call({
		method: "populate_from_salary_slips",
		doc: frm.doc,
		freeze: true,
		freeze_message: __("Reading the salary slips..."),
	}).then(() => frm.save());
}

function send_to_employee(frm) {
	if (!frappe.model.can_email(frm.doctype, frm)) {
		frappe.msgprint(__("You are not allowed to send this certificate by email."));
		return;
	}
	frm.call("get_delivery_options").then(({ message: options }) => {
		if (!options || !options.addresses.length) {
			frappe.msgprint(
				__("{0} has no email address. Add one to the employee record.", [
					frappe.utils.escape_html(frm.doc.employee_name || frm.doc.employee),
				])
			);
			return;
		}
		const notes = [];
		if (options.password_policy) {
			notes.push(
				__("The PDF is protected by a password of the format {0}, as the salary slips.", [
					`<code>${frappe.utils.escape_html(options.password_policy)}</code>`,
				])
			);
		}
		if (options.sent_to_employee_on) {
			notes.push(
				__("Last sent to {0} on {1}.", [
					frappe.utils.escape_html(options.sent_to || ""),
					frappe.datetime.str_to_user(options.sent_to_employee_on),
				])
			);
		}
		const dialog = new frappe.ui.Dialog({
			title: options.sent_to_employee_on
				? __("Resend the salary certificate")
				: __("Send the salary certificate"),
			fields: [
				{
					fieldname: "recipient",
					fieldtype: "Select",
					label: __("Recipient"),
					options: options.addresses,
					default: options.default,
					reqd: 1,
					description: __("The addresses of the employee record."),
				},
				{
					fieldname: "notes",
					fieldtype: "HTML",
					options: notes.length
						? `<div class="text-muted small">${notes.join("<br>")}</div>`
						: "",
				},
			],
			primary_action_label: __("Send"),
			primary_action(values) {
				dialog.hide();
				frm.call({
					method: "send_to_employee",
					doc: frm.doc,
					args: { recipient: values.recipient },
					freeze: true,
					freeze_message: __("Sending..."),
				}).then(() => {
					frappe.show_alert({
						message: __("Salary certificate sent to {0}", [
							frappe.utils.escape_html(values.recipient),
						]),
						indicator: "green",
					});
					frm.reload_doc();
				});
			},
		});
		dialog.show();
	});
}

function show_barcode_dialog(frm, data) {
	let html = "";
	for (let i = 0; i < data.pdf417_images.length; i++) {
		html += `
			<div style="text-align:center; margin-bottom:20px;">
				<h5>${__("PDF417 Barcode")}${data.page_count > 1 ? " (" + (i + 1) + "/" + data.page_count + ")" : ""}</h5>
				<img src="data:image/png;base64,${data.pdf417_images[i]}"
					style="max-width:100%; image-rendering:pixelated;" />
			</div>`;
	}
	html += `
		<div style="text-align:center; margin-top:10px;">
			<h5>${__("CODE128C Identifier")}</h5>
			<img src="data:image/png;base64,${data.code128c_image}"
				style="height:40px;" />
			<div style="font-family:monospace; font-size:12px; margin-top:5px;">
				${data.identifier}
			</div>
		</div>`;

	let d = new frappe.ui.Dialog({
		title: __("Salary Certificate Barcode Preview"),
		size: "large",
	});
	d.$body.html(html);
	d.show();
}
