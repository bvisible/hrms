//// Neoffice — added file (no upstream equivalent): desk form of the Swissdec declaration
//// (generate the ELM XML — an internal preview since the certified software transmits —,
//// transmit where a gateway is switched on, follow the status).
// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
// License: GNU General Public License v3. See license.txt

frappe.ui.form.on("Swissdec Declaration", {
	setup(frm) {
		// Filter original_declaration to show only Accepted declarations
		// for the same company and fiscal year
		frm.set_query("original_declaration", () => {
			return {
				filters: {
					company: frm.doc.company,
					fiscal_year: frm.doc.fiscal_year,
					status: "Accepted",
					declaration_type: ["!=", "Correction"],
				},
			};
		});
	},

	refresh(frm) {
		// The ELM declaration is transmitted by the certified payroll software (2026-09-23): the XML
		// made here is an internal preview, and the gateway buttons show only where the gateway is
		// switched on (neoffice-maintenance#653).
		const can_transmit = !!(frm.doc.__onload && frm.doc.__onload.transmission_enabled);
		if (!can_transmit && !frm.is_new()) {
			frm.set_intro(
				__(
					"The ELM declaration is transmitted by the certified payroll software. The XML made here is an internal preview, not valid against the Swissdec schema: do not send it."
				),
				"orange"
			);
		}

		// Populate Employees button
		if (frm.doc.company && frm.doc.fiscal_year && frm.doc.status === "Draft") {
			frm.add_custom_button(
				__("Populate Employees"),
				() => {
					frm.call("populate_employees").then(() => frm.refresh_fields());
				},
				__("Actions")
			);
		}

		// Validate button
		if (frm.doc.employees && frm.doc.employees.length > 0 && frm.doc.status === "Draft") {
			frm.add_custom_button(
				__("Validate"),
				() => {
					frm.call("run_validation").then(() => frm.refresh_fields());
				},
				__("Actions")
			);
		}

		// Internal XML preview button
		if (frm.doc.status === "Validated" || frm.doc.status === "Exported") {
			frm.add_custom_button(
				__("Internal XML preview"),
				() => {
					frm.call("export_xml").then(() => frm.refresh_fields());
				},
				__("Actions")
			);
		}

		// Transmit button
		if (can_transmit && frm.doc.status === "Exported") {
			frm.add_custom_button(
				__("Transmit"),
				() => {
					frappe.confirm(
						__("Are you sure you want to transmit this declaration to Swissdec?"),
						() => {
							frm.call("transmit").then(() => frm.refresh_fields());
						}
					);
				},
				__("Actions")
			);
		}

		// Check Status button
		if (can_transmit && frm.doc.status === "Transmitted") {
			frm.add_custom_button(
				__("Check Status"),
				() => {
					frm.call("check_status").then(() => frm.refresh_fields());
				},
				__("Actions")
			);
		}

		// Import BVG Response button (for Accepted BVG-Projection)
		if (
			frm.doc.declaration_type === "BVG-Projection" &&
			frm.doc.status === "Accepted"
		) {
			frm.add_custom_button(
				__("Import BVG Response"),
				() => {
					frappe.prompt(
						{
							fieldname: "csv_data",
							fieldtype: "Small Text",
							label: __("Paste CSV (employee,contribution)"),
							reqd: 1,
						},
						(values) => {
							// Parse CSV into contributions array
							let contributions = [];
							let lines = values.csv_data.trim().split("\n");
							for (let line of lines) {
								let parts = line.split(",");
								if (parts.length >= 2) {
									contributions.push({
										employee: parts[0].trim(),
										bvg_response_contribution: parseFloat(parts[1].trim()) || 0,
									});
								}
							}
							frm.call("import_bvg_response", {
								contributions: JSON.stringify(contributions),
							}).then(() => frm.refresh_fields());
						},
						__("Import BVG Contributions"),
						__("Import")
					);
				},
				__("Actions")
			);
		}

		// Re-transmit button
		if (can_transmit && frm.doc.status === "Rejected") {
			frm.add_custom_button(
				__("Re-transmit"),
				() => {
					frappe.confirm(
						__("Are you sure you want to re-transmit this rejected declaration?"),
						() => {
							frm.call("retransmit").then(() => frm.refresh_fields());
						}
					);
				},
				__("Actions")
			);
		}

		// Status indicator
		if (frm.doc.status) {
			const indicator_map = {
				Draft: "red",
				Validated: "blue",
				Exported: "orange",
				Transmitted: "yellow",
				Accepted: "green",
				Rejected: "red",
			};
			frm.page.set_indicator(__(frm.doc.status), indicator_map[frm.doc.status] || "grey");
		}
	},
});
