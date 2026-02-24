// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swiss Salary Certificate", {
	refresh(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.employee && frm.doc.fiscal_year) {
			frm.add_custom_button(__("Populate from Salary Slips"), function () {
				frm.call("populate_from_salary_slips").then(() => {
					frm.refresh_fields();
				});
			});
		}

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(__("Preview Barcode"), function () {
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
			});
		}
	},
});

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
