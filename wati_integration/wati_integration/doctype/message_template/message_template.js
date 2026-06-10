frappe.ui.form.on("Message Template", {

    refresh(frm) {
        // ADDON: "Preview Message" button
        if (!frm.is_new() && frm.doc.template_message) {
            frm.add_custom_button(__("Preview Message"), function () {
                // Build prompt fields from the template variables
                let variables = (frm.doc.template_variables || "")
                    .split(",")
                    .map(v => v.trim())
                    .filter(Boolean);

                if (!variables.length) {
                    frappe.msgprint(__("This template has no variables."));
                    return;
                }

                let fields = variables.map(v => ({
                    fieldname: v,
                    fieldtype: "Data",
                    label: v,
                }));

                frappe.prompt(fields, function (values) {
                    frm.call({
                        method: "get_preview",
                        doc: frm.doc,
                        args: { sample_values: values },
                        callback: function (r) {
                            if (r.message) {
                                frappe.msgprint({
                                    title: __("Message Preview"),
                                    message: r.message.replace(/\n/g, "<br>"),
                                    indicator: "blue",
                                });
                            }
                        }
                    });
                }, __("Preview Variables"), __("Preview"));
            });
        }
    },

    template_message(frm) {
        // Auto-extract and display variables as user types
        if (frm.doc.template_message) {
            let matches = frm.doc.template_message.match(/\{([^{}]+?)\}/g) || [];
            let vars = [...new Set(matches.map(m => m.slice(1, -1).trim()))].filter(Boolean);
            frm.set_value("template_variables", vars.join(", "));
        }
    },
});
