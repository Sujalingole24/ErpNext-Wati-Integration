// Copyright (c) 2022, Bhavesh Maheshwari and contributors
// ADDON v2.0.2 — Wati Delivery Report filters

frappe.query_reports["Wati Delivery Report"] = {
    filters: [
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: frappe.datetime.add_days(frappe.datetime.nowdate(), -30),
            reqd: 1,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.nowdate(),
            reqd: 1,
        },
        {
            fieldname: "ref_doctype",
            label: __("Document Type"),
            fieldtype: "Link",
            options: "DocType",
        },
        {
            fieldname: "message_template",
            label: __("Template"),
            fieldtype: "Link",
            options: "Message Template",
        },
        {
            fieldname: "status_code",
            label: __("Status Code"),
            fieldtype: "Select",
            options: "\n200\n400\n401\n429\n500\n0",
        },
        {
            fieldname: "direction",
            label: __("Direction"),
            fieldtype: "Select",
            options: "\nOutgoing\nIncoming\nStatus Update",
        },
    ],
};
