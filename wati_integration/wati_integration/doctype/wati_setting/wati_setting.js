frappe.ui.form.on("Wati Setting", {
    refresh(frm) {
        // ADDON v2.0.2 — Show enabled/disabled status banner
        if (frm.doc.enabled === 0) {
            // BUG FIX: set_headline_alert is not present in all Frappe v16 minor builds.
            // Guard it the same way clear_headline is already guarded below.
            if (typeof frm.dashboard.set_headline_alert === "function") {
                frm.dashboard.set_headline_alert(
                    '<span class="indicator red">WATI Sending is DISABLED — all outgoing messages are paused.</span>'
                );
            }
        } else {
            // clear_headline may not exist on all Frappe v16 minor builds — guard it
            if (typeof frm.dashboard.clear_headline === "function") {
                frm.dashboard.clear_headline();
            } else if (typeof frm.dashboard.reset === "function") {
                frm.dashboard.reset();
            }
        }

        // "Test Connection" button — calls the server-side test_connection method
        frm.add_custom_button(__("Test Connection"), function () {
            frm.call({
                method: "test_connection",
                doc: frm.doc,
                callback: function () {
                    // Response feedback is handled server-side via frappe.msgprint
                }
            });
        }, __("Actions"));
    },

    enabled(frm) {
        // Refresh to update the status banner immediately on toggle
        frm.refresh();
    }
});

