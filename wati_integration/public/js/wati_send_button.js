// Copyright (c) 2022, Bhavesh Maheshwari and contributors
// ADDON v2.0.2 — Inject "Send WhatsApp" button on standard ERPNext forms
//
// This script is loaded on every Frappe desk page (registered via app_include_js in hooks.py).
// It checks frappe.boot.wati_configured before doing anything, so it's a no-op
// on sites where WATI is not set up.
//
// Supported doctypes: Sales Order, Purchase Order, Sales Invoice, Purchase Invoice,
//   Lead, Customer, Supplier, Employee, Quotation, Delivery Note, Payment Entry
//
// When clicked, a dialog opens allowing the user to:
//   1. Pick a Wati Message Rule that applies to the current doctype
//   2. Enter a mobile number override (optional)
//   3. Send immediately

(function () {
    "use strict";

    // Doctypes where the button will be injected.
    // Add or remove as needed — this list does NOT affect any existing logic.
    const WATI_BUTTON_DOCTYPES = [
        "Sales Order",
        "Purchase Order",
        "Sales Invoice",
        "Purchase Invoice",
        "Lead",
        "Customer",
        "Supplier",
        "Employee",
        "Quotation",
        "Delivery Note",
        "Payment Entry",
        "Contact",
    ];

    function injectWatiButton(frm) {
        // Only inject once per form render
        if (frm.__wati_button_added) return;
        frm.__wati_button_added = true;

        frm.add_custom_button(__("Send WhatsApp"), function () {
            openWatiDialog(frm);
        }, __("Actions"));
    }

    function openWatiDialog(frm) {
        // Fetch all enabled rules for this doctype
        frappe.call({
            method: "frappe.client.get_list",
            args: {
                doctype: "Wati Message Rule",
                filters: { ref_doctype: frm.doctype, enable: 1 },
                fields: ["name", "message_template", "mobile_no_field"],
                limit: 0,  // 0 = no limit — fetch ALL enabled rules for this doctype.
                           // The previous hard-coded 50 silently dropped any rules
                           // beyond the 51st, making them invisible in the dialog.
            },
            callback: function (r) {
                const rules = (r.message || []);
                if (!rules.length) {
                    frappe.msgprint({
                        title: __("No WATI Rules Found"),
                        message: __(
                            "No enabled Wati Message Rules found for {0}. "
                            + "Please create a rule in <b>Wati Message Rule</b> first.",
                            [frm.doctype]
                        ),
                        indicator: "orange",
                    });
                    return;
                }

                const ruleOptions = rules.map(r => r.name);

                const dialog = new frappe.ui.Dialog({
                    title: __("Send WhatsApp Message"),
                    fields: [
                        {
                            fieldname: "rule",
                            fieldtype: "Select",
                            label: __("Select Rule"),
                            options: ruleOptions,
                            reqd: 1,
                            description: __("Choose the message rule to apply"),
                        },
                        {
                            fieldname: "mobile_override",
                            fieldtype: "Data",
                            label: __("Mobile Number Override"),
                            description: __(
                                "Optional. Leave blank to use the mobile number from the document. "
                                + "You can enter a 10-digit Indian number (e.g. 9876543210) — "
                                + "country code 91 will be added automatically."
                            ),
                        },
                    ],
                    primary_action_label: __("Send"),
                    primary_action(values) {
                        // ── India country-code auto-prefix ──────────────────────────────
                        // If user entered a 10-digit Indian mobile (starts with 6/7/8/9),
                        // silently prepend 91 so WATI receives a valid E.164 number.
                        // If the number is already 12 digits (e.g. 919876543210) leave it alone.
                        let mobileOverride = (values.mobile_override || "").replace(/[\s\-()+.]/g, "");
                        if (mobileOverride.length === 10 && /^[6-9]/.test(mobileOverride)) {
                            mobileOverride = "91" + mobileOverride;
                        } else if (mobileOverride && (!/^\d+$/.test(mobileOverride) || mobileOverride.length < 11)) {
                            // Not a 10-digit Indian number and not a valid international number
                            frappe.msgprint({
                                title: __("Invalid Mobile Number"),
                                message: __(
                                    "The mobile number <b>{0}</b> appears to be missing a country code. "
                                    + "Enter a 10-digit Indian number (e.g. 9876543210) or a full international number (e.g. 919876543210).",
                                    [values.mobile_override]
                                ),
                                indicator: "red",
                            });
                            return;  // Keep dialog open so user can fix the number
                        }
                        // ── End country-code validation ─────────────────────────────────
                        dialog.hide();
                        frappe.call({
                            method: "wati_integration.wati_integration.api.send_from_form",
                            args: {
                                doctype: frm.doctype,
                                docname: frm.docname,
                                rule_name: values.rule,
                                mobile_override: mobileOverride,  // already normalised above
                            },
                            freeze: true,
                            freeze_message: __("Sending WhatsApp message…"),
                            callback: function (res) {
                                if (res && res.message && res.message.status === "ok") {
                                    frappe.show_alert({
                                        message: __("WhatsApp message sent successfully."),
                                        indicator: "green",
                                    });
                                } else {
                                    frappe.show_alert({
                                        message: __("Send failed — check Wati Message Log for details."),
                                        indicator: "red",
                                    });
                                }
                            },
                        });
                    },
                });
                dialog.show();
            },
        });
    }

    // Hook into every doctype listed above.
    // frappe.after_ajax is not available in all Frappe v16 minor builds.
    // frappe.ready() fires once the desk JS is fully initialised — safe on v16.
    function registerHooks() {
        if (!frappe.boot || !frappe.boot.wati_configured) return;

        WATI_BUTTON_DOCTYPES.forEach(function (doctype) {
            frappe.ui.form.on(doctype, {
                refresh(frm) {
                    // Only show on saved (non-new) documents
                    if (!frm.is_new()) {
                        injectWatiButton(frm);
                    }
                },
            });
        });
    }

    // frappe.ready is the correct Frappe v16 hook for desk-init callbacks
    if (typeof frappe !== "undefined" && typeof frappe.ready === "function") {
        frappe.ready(registerHooks);
    } else {
        // Fallback: defer until frappe object is available
        document.addEventListener("DOMContentLoaded", function () {
            setTimeout(registerHooks, 0);
        });
    }
})();
