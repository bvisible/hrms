// //// Neoffice — added file (no upstream equivalent): frank a submitted payslip with a Swiss Post
// //// WebStamp (hrms/regional/switzerland/webstamp.py), when the swisspost_barcode app is installed.
// //// The stamp carries the franking and the address; the Swiss payslip prints it in the envelope
// //// window. Preview is free; the order is billed by Swiss Post (a TEST preview on a test account).

frappe.ui.form.on("Salary Slip", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (!(frappe.boot.versions && frappe.boot.versions.swisspost_barcode)) return;
		frm.add_custom_button(__("WebStamp"), () => open_payslip_webstamp(frm));
	},
});

function open_payslip_webstamp(frm) {
	frappe.call({
		method: "hrms.regional.switzerland.webstamp.get_stamp_options",
		args: { salary_slip: frm.doc.name },
		callback: (r) => r.message && show_payslip_webstamp_dialog(frm, r.message),
	});
}

function show_payslip_webstamp_dialog(frm, options) {
	const esc = frappe.utils.escape_html;
	const recipient = options.recipient;
	const products = options.products || [];
	const test = options.environment !== "Production";
	const label = (p) => `${p.product_name} — CHF ${format_number(p.price, null, 2)}`;

	const dialog = new frappe.ui.Dialog({
		title: __("Frank this payslip"),
		fields: [
			{
				fieldname: "intro",
				fieldtype: "HTML",
				options: `<div class="text-muted small" style="margin-bottom: 8px;">
					${__(
						"The stamp carries the postage and the address: the printed payslip shows it in the envelope window.",
					)}
					${__(
						"Preview is free and never billed; ordering bills the stamp to the company's WebStamp account.",
					)}
					${
						test
							? `<br><b>${__(
									"Test environment: the stamp is a preview marked TEST and nothing is billed.",
							  )}</b>`
							: ""
					}
				</div>`,
			},
			{
				fieldname: "recipient",
				fieldtype: "HTML",
				options: `<div style="margin-bottom: 8px;">
					<div class="text-muted small">${__("Recipient")}</div>
					<div>${esc(recipient.name)}<br>${esc(recipient.street)}<br>${esc(recipient.zip)} ${esc(
						recipient.city,
					)}</div>
				</div>`,
			},
			{
				fieldname: "product",
				fieldtype: "Select",
				label: __("Product"),
				reqd: 1,
				options: products.map(label).join("\n"),
				default: products.length ? label(products[0]) : "",
			},
			{ fieldname: "stamp", fieldtype: "HTML" },
		],
		primary_action_label: __("Order the stamp"),
		primary_action: (values) => order(values),
		secondary_action_label: __("Preview (free)"),
		secondary_action: () => preview(dialog.get_values()),
	});

	const chosen = (values) => products.find((p) => label(p) === (values && values.product));
	const show_stamp = (src, note) =>
		dialog.fields_dict.stamp.$wrapper.html(
			`${note ? `<div class="text-muted small" style="margin: 6px 0;">${note}</div>` : ""}
			<img src="${src}" style="width: 100%; max-width: 420px; border: 1px solid var(--border-color);">`,
		);
	if (options.stamp_url) {
		show_stamp(
			options.stamp_url,
			__("A stamp was already ordered for this payslip. Ordering again bills a new one."),
		);
	}

	function call(values, preview_only, done) {
		const product = chosen(values);
		if (!product) return;
		frappe.call({
			method: "hrms.regional.switzerland.webstamp.stamp_salary_slip",
			type: "POST",
			args: {
				salary_slip: frm.doc.name,
				product_number: product.product_number,
				product_name: product.product_name,
				product_price: product.price,
				preview: preview_only ? 1 : 0,
			},
			freeze: true,
			callback: (r) => {
				const res = r.message || {};
				if (!res.success) {
					frappe.msgprint({
						title: __("WebStamp"),
						message: esc(res.message || ""),
						indicator: "red",
					});
					return;
				}
				done(res, product);
			},
		});
	}

	function preview(values) {
		call(values, true, (res) => show_stamp(res.image_data));
	}

	function order(values) {
		const product = chosen(values);
		if (!product) return;
		const question = test
			? __("Order a TEST stamp (nothing is billed)?")
			: __("Order this stamp for CHF {0}? Swiss Post bills it.", [
					format_number(product.price, null, 2),
			  ]);
		frappe.confirm(question, () =>
			call(values, false, (res) => {
				dialog.hide();
				frappe.show_alert({
					message: __(
						"Stamp ordered: the printed payslip now carries it in the envelope window.",
					),
					indicator: "green",
				});
				frm.reload_doc();
			}),
		);
	}

	dialog.show();
}
