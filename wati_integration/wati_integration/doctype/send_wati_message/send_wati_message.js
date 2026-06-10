frappe.ui.form.on("Send Wati Message", {

    refresh(frm) {
        // Show "Get Variables" button when a template is selected and not submitted
        if (frm.doc.message_template && frm.doc.docstatus === 0) {
            frm.add_custom_button(__("Get Variables"), function () {
                _fetch_and_set_variables(frm);
            });
        }

        // ADDON: "Delivery Summary" button on submitted docs
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__("Delivery Summary"), function () {
                frm.call({
                    method: "get_delivery_summary",
                    doc: frm.doc,
                    callback: function (r) {
                        if (r.message) {
                            let d = r.message;
                            let lines = [`<b>Total messages logged: ${d.total}</b><br><br>`];
                            for (let [code, count] of Object.entries(d.by_status || {})) {
                                let color = code === "200" ? "green" : "red";
                                lines.push(`<span style="color:${color}">HTTP ${code}: ${count}</span><br>`);
                            }
                            frappe.msgprint({
                                title: __("Delivery Summary"),
                                message: lines.join(""),
                                indicator: "blue",
                            });
                        }
                    }
                });
            }, __("View"));
        }
    },

    message_template(frm) {
        // Auto-fetch variables when template is changed
        if (frm.doc.message_template) {
            _fetch_and_set_variables(frm);
        } else {
            frm.clear_table("send_message_variables");
            frm.refresh_field("send_message_variables");
        }
    },

    when_to_send(frm) {
        // Show/hide schedule field
        frm.set_df_property(
            "schedule_date_and_time", "reqd",
            frm.doc.when_to_send === "Schedule" ? 1 : 0
        );
    },
});

// ─── Helper: fetch variables and rebuild the child table explicitly ───────────
//
// BUG FIX (v2.0.3) — The old approach used frm.call() with doc:frm.doc and then
// just called frm.refresh_field("send_message_variables") in the callback.
// In Frappe v16, child table rows created via self.append() server-side carry
// auto-generated local names; frappe.model.sync() does not reliably merge them
// back into frm.doc, so the grid stayed empty after the call.
//
// Fix: get_variables() now returns a plain list [{template_variable, value}, ...]
// The callback uses frm.clear_table() + frm.add_child() to rebuild the grid
// without relying on model sync.  After the grid is rebuilt frm.refresh_field()
// renders it.  The template_variable column (Read Only) is set via
// frappe.model.set_value() so Frappe includes it in the save payload.
//
// Also fixes "mobile no & variable no not showing after save":
// Previously the child table was rebuilt server-side but the client-side model
// was not updated, so values appeared on the form but were not in frm.doc and
// were therefore not submitted on Save.  Now the client model is explicitly
// rebuilt from the server response before any save can happen.
//
function _fetch_and_set_variables(frm) {
    frm.call({
        method: "get_variables",
        doc: frm.doc,
        callback: function (r) {
            frm.clear_table("send_message_variables");

            let rows = (r && r.message) ? r.message : [];
            rows.forEach(function (item) {
                let child = frm.add_child("send_message_variables");
                // Use frappe.model.set_value so the value lands in the model
                // and is included in the form save payload.
                frappe.model.set_value(
                    child.doctype, child.name,
                    "template_variable", item.template_variable
                );
            });

            frm.refresh_field("send_message_variables");
        }
    });
}
