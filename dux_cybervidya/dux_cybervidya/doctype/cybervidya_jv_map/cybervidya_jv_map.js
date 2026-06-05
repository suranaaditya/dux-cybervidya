// Filter the Debit Account picker to non-group leaf accounts in the chosen company.
frappe.ui.form.on("CyberVidya JV Map", {
	company(frm) {
		// Clear a now-mismatched account when company changes.
		if (frm.doc.account) {
			frappe.db.get_value("Account", frm.doc.account, "company").then((r) => {
				if (r && r.message && r.message.company !== frm.doc.company) {
					frm.set_value("account", null);
				}
			});
		}
	},
	setup(frm) {
		frm.set_query("account", () => {
			return {
				filters: {
					company: frm.doc.company || "",
					is_group: 0,
				},
			};
		});
	},
});
