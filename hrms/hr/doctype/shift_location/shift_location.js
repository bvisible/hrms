// Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Shift Location", {
	refresh: async (frm) => {
		//// Neoffice — read through hrms.api.get_hr_settings, which every signed-in user reads (the PWA
		//// does): HR Settings may be closed to the HR staff (neoffice-maintenance#712), and
		//// frappe.db.get_single_value then opened « No permission for HR Settings » at every refresh.
		const { allow_geolocation_tracking } = await frappe.xcall("hrms.api.get_hr_settings");

		if (!allow_geolocation_tracking)
			hide_field([
				"checkin_radius",
				"fetch_geolocation",
				"latitude",
				"longitude",
				"geolocation",
			]);

		if (!frm.doc.__islocal)
			hrms.add_shift_tools_button_to_form(frm, {
				action: "Assign Shift",
				shift_location: frm.doc.name,
			});
	},

	fetch_geolocation: (frm) => {
		hrms.fetch_geolocation(frm);
	},
});
