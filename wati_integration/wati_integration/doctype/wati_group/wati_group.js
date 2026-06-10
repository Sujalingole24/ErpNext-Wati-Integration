frappe.ui.form.on("Wati Group", {

    refresh(frm) {
        if (!frm.is_new()) {
            // ADDON: "Import Members" button — imports all records of the selected doctype
            frm.add_custom_button(__("Import Members"), function () {
                let doctype = frm.doc.reference_doctype;
                if (!doctype) {
                    frappe.msgprint(__("Please select a Reference Doctype first."));
                    return;
                }
                frappe.confirm(
                    __("Import all active {0} records into this group?", [doctype]),
                    function () {
                        frappe.call({
                            method: "wati_integration.wati_integration.doctype.wati_group.wati_group.import_from_doctype",
                            args: { group_name: frm.doc.name, document_type: doctype },
                            callback: function (r) {
                                frappe.msgprint(
                                    __("{0} members added.", [r.message || 0]),
                                    __("Import Complete")
                                );
                                frm.reload_doc();
                            }
                        });
                    }
                );
            }, __("Actions"));

            // Summary badge
            let total = (frm.doc.wati_group_details || []).length;
            let enabled = (frm.doc.wati_group_details || []).filter(r => r.enable).length;
            frm.set_intro(
                __("{0} members total, {1} enabled", [total, enabled]),
                "blue"
            );
        }
    },
});

// BUG FIX: member_name was only populated on Python validate() (i.e. on save).
// When a user manually adds a row and picks a group_member, the Member Name
// column stayed blank until the form was saved — confusing UX.
// This child-table trigger fetches the display name and mobile_no immediately
// when group_member is selected, without needing to save first.
// The server-side _populate_member_names() on save remains authoritative;
// this JS is purely a UX improvement for real-time grid feedback.
frappe.ui.form.on("Wati Group Details", {
    group_member(frm, cdt, cdn) {
        const row = frappe.get_doc(cdt, cdn);
        if (!row.group_member || !row.document_type) return;

        // Mirrors Python _populate_member_names() name_field_map
        const nameFieldMap = {
            "Customer": "customer_name",
            "Supplier": "supplier_name",
            "Employee": "employee_name",
            "Lead":     "lead_name",
            "Contact":  "full_name",
        };

        const nameField = nameFieldMap[row.document_type];
        if (nameField) {
            frappe.db.get_value(row.document_type, row.group_member, nameField, (res) => {
                frappe.model.set_value(cdt, cdn, "member_name", (res && res[nameField]) || row.group_member);
            });
        } else {
            // Doctype not in map — use doc ID as fallback
            frappe.model.set_value(cdt, cdn, "member_name", row.group_member);
        }

        // Also auto-fill mobile_no when row is freshly added
        if (!row.mobile_no) {
            frappe.call({
                method: "wati_integration.wati_integration.doctype.wati_group.wati_group.get_mobile_no",
                args: { group_member: row.group_member, document_type: row.document_type },
                callback(res) {
                    if (res.message) {
                        frappe.model.set_value(cdt, cdn, "mobile_no", res.message);
                    }
                },
            });
        }
    },
});
