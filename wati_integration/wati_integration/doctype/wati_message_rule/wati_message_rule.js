function set_wati_rule_options(frm) {
    if (!frm.doc.ref_doctype) return;

    frappe.model.with_doctype(frm.doc.ref_doctype, function () {
        const meta = frappe.get_meta(frm.doc.ref_doctype);

        // All valid fields
        const all_fields = meta.fields
            .filter(df =>
                df.fieldname &&
                !["Section Break", "Column Break", "HTML", "Button"].includes(df.fieldtype)
            )
            .map(df => df.fieldname);

        // Mobile Number Fields
        const phone_types = ["Data", "Phone", "Small Text"];

        const mobile_fields = meta.fields
            .filter(df =>
                df.fieldname &&
                phone_types.includes(df.fieldtype)
            )
            .map(df => df.fieldname);

        // Mobile No Field dropdown
        frm.set_df_property(
            "mobile_no_field",
            "options",
            ["", ...mobile_fields].join("\n")
        );
        frm.refresh_field("mobile_no_field");

        // Fields dropdown
        frm.set_df_property(
            "fields",
            "options",
            ["", ...all_fields].join("\n")
        );
        frm.refresh_field("fields");

        // Child Table: Template Variable
        if (
            frm.fields_dict.template_variable &&
            frm.fields_dict.template_variable.grid
        ) {
            const grid = frm.fields_dict.template_variable.grid;
            const options = ["", ...all_fields].join("\n");

            if (grid.update_docfield_property) {
                grid.update_docfield_property(
                    "document_variable",
                    "options",
                    options
                );
            } else if (grid.get_field("document_variable")) {
                grid.get_field("document_variable").df.options = options;
            }

            grid.refresh();
            frm.refresh_field("template_variable");
        }
    });
}

frappe.ui.form.on("Wati Message Rule", {

    setup(frm) {
        set_wati_rule_options(frm);
    },

    onload(frm) {
        set_wati_rule_options(frm);
    },

    refresh(frm) {
        set_wati_rule_options(frm);

        // Prevent duplicate buttons
        frm.remove_custom_button(__("Set Variables"));
        frm.remove_custom_button(__("Send Test Message"), __("Actions"));

        if (!frm.is_new()) {

            frm.add_custom_button(__("Set Variables"), function () {
                frm.call({
                    method: "set_variable",
                    doc: frm.doc,
                    callback: function () {
                        set_wati_rule_options(frm);
                        frm.refresh_field("template_variable");
                    }
                });
            });

            frm.add_custom_button(
                __("Send Test Message"),
                function () {
                    frappe.prompt(
                        [
                            {
                                fieldname: "mobile_no",
                                fieldtype: "Data",
                                label: __("Mobile Number"),
                                reqd: 1,
                                description: __("Enter a number to send the test message. Example: 971501234567")
                            }
                        ],
                        function (values) {
                            frm.call({
                                method: "send_test_message",
                                doc: frm.doc,
                                args: {
                                    mobile_no: values.mobile_no
                                }
                            });
                        },
                        __("Test Message"),
                        __("Send")
                    );
                },
                __("Actions")
            );
        }
    },

    ref_doctype(frm) {
        set_wati_rule_options(frm);
    }
});