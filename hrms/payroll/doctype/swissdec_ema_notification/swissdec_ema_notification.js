// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swissdec EMA Notification", {
	refresh(frm) {
		// Refresh snapshot button
		if (frm.doc.employee && frm.doc.status === "Draft") {
			frm.add_custom_button(
				__("Refresh Snapshot"),
				() => {
					frm.call("populate_from_employee").then(() => frm.refresh_fields());
				},
				__("Actions")
			);
		}

		// Export XML button
		if (frm.doc.status === "Draft" && frm.doc.employee && frm.doc.event_type) {
			frm.add_custom_button(
				__("Export XML"),
				() => {
					frm.call("export_xml").then(() => frm.refresh_fields());
				},
				__("Actions")
			);
		}

		// Transmit button
		if (frm.doc.status === "Exported") {
			frm.add_custom_button(
				__("Transmit"),
				() => {
					frappe.confirm(
						__("Are you sure you want to transmit this EMA notification?"),
						() => {
							frm.call("transmit").then(() => frm.refresh_fields());
						}
					);
				},
				__("Actions")
			);
		}

		// Check Status button
		if (frm.doc.status === "Transmitted") {
			frm.add_custom_button(
				__("Check Status"),
				() => {
					frm.call("check_status").then(() => frm.refresh_fields());
				},
				__("Actions")
			);
		}

		// Status indicator
		if (frm.doc.status) {
			const indicator_map = {
				Draft: "orange",
				Exported: "blue",
				Transmitted: "yellow",
				Accepted: "green",
				Rejected: "red",
			};
			frm.page.set_indicator(__(frm.doc.status), indicator_map[frm.doc.status] || "grey");
		}
	},
});
