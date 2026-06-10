# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt
#
# ADDON v2.0.2 — Wati Delivery Report
# Script Report: shows message delivery stats grouped by date, doctype, template.
# Accessible from: ERPNext > Reports > Wati Delivery Report

import frappe
from frappe import _
from frappe.utils import getdate, nowdate, add_days


def execute(filters=None):
    filters = filters or {}
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    return columns, data, None, chart


def get_columns():
    return [
        {
            "fieldname": "sent_date",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 110,
        },
        {
            "fieldname": "ref_doctype",
            "label": _("Document Type"),
            "fieldtype": "Data",
            "width": 150,
        },
        {
            "fieldname": "message_template",
            "label": _("Template"),
            "fieldtype": "Data",
            "width": 180,
        },
        {
            "fieldname": "direction",
            "label": _("Direction"),
            "fieldtype": "Data",
            "width": 110,
        },
        {
            "fieldname": "status_code",
            "label": _("Status Code"),
            "fieldtype": "Data",
            "width": 100,
        },
        {
            "fieldname": "total",
            "label": _("Count"),
            "fieldtype": "Int",
            "width": 80,
        },
    ]


def get_filters_conditions(filters):
    conditions = []
    values = {}

    from_date = filters.get("from_date") or add_days(nowdate(), -30)
    to_date = filters.get("to_date") or nowdate()
    conditions.append("DATE(sent_at) BETWEEN %(from_date)s AND %(to_date)s")
    values["from_date"] = getdate(from_date)
    values["to_date"] = getdate(to_date)

    if filters.get("ref_doctype"):
        conditions.append("ref_doctype = %(ref_doctype)s")
        values["ref_doctype"] = filters["ref_doctype"]

    if filters.get("message_template"):
        conditions.append("message_template = %(message_template)s")
        values["message_template"] = filters["message_template"]

    if filters.get("status_code"):
        conditions.append("status_code = %(status_code)s")
        values["status_code"] = filters["status_code"]

    if filters.get("direction"):
        conditions.append("direction = %(direction)s")
        values["direction"] = filters["direction"]

    where = " AND ".join(conditions)
    return where, values


def get_data(filters):
    where, values = get_filters_conditions(filters)
    # NOTE: 'where' is built entirely from hardcoded string literals in
    # get_filters_conditions() — no user input is ever interpolated into the
    # SQL string itself. All user values go via the parameterized 'values' dict.
    sql = (
        "SELECT DATE(sent_at) AS sent_date, ref_doctype,"
        " COALESCE(NULLIF(message_template, ''), '\u2014') AS message_template,"
        " COALESCE(NULLIF(direction, ''), 'Outgoing') AS direction,"
        " status_code, COUNT(*) AS total"
        " FROM `tabWati Message Log`"
        " WHERE " + where +
        " GROUP BY DATE(sent_at), ref_doctype, message_template, direction, status_code"
        " ORDER BY DATE(sent_at) DESC, total DESC"
    )
    rows = frappe.db.sql(sql, values, as_dict=1)
    return rows


def get_chart(data):
    """Build a simple bar chart — success (200) vs failure by date."""
    date_success = {}
    date_failure = {}

    for row in data:
        d = str(row.get("sent_date") or "")
        if not d:
            continue
        count = row.get("total") or 0
        if str(row.get("status_code")) == "200":
            date_success[d] = date_success.get(d, 0) + count
        else:
            date_failure[d] = date_failure.get(d, 0) + count

    labels = sorted(set(list(date_success.keys()) + list(date_failure.keys())))
    if not labels:
        return None

    return {
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "name": _("Success (200)"),
                    "values": [date_success.get(d, 0) for d in labels],
                },
                {
                    "name": _("Failed"),
                    "values": [date_failure.get(d, 0) for d in labels],
                },
            ],
        },
        "type": "bar",
        "colors": ["#28a745", "#dc3545"],
        "barOptions": {"stacked": 0},
    }
