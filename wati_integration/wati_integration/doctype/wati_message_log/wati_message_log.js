frappe.ui.form.on("Wati Message Log", {
    refresh(frm) {
        // Color-code the status code field for quick visual feedback
        if (frm.doc.status_code) {
            let code = parseInt(frm.doc.status_code);
            let color = code === 200 ? "green" : "red";
            frm.fields_dict["status_code"].$wrapper.find(".control-value").css("color", color);
        }

        // Pretty-print JSON payload and response fields.
        // Use set_input() + refresh_field() instead of set_value() so the form
        // is NOT marked dirty (no misleading "Not Saved" indicator on a read-only log).
        ["payload", "response"].forEach(function (field) {
            if (frm.doc[field]) {
                try {
                    let pretty = JSON.stringify(JSON.parse(frm.doc[field]), null, 2);
                    frm.doc[field] = pretty;               // update model without dirty flag
                    frm.refresh_field(field);              // re-render the field widget
                } catch (e) { /* not JSON — leave as-is */ }
            }
        });
    }
});
