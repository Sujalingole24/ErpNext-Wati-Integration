# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class WatiMessageLog(Document):
    pass


@frappe.whitelist()
def get_log_stats(from_date=None, to_date=None):
    """
    ADDON: Return message delivery stats for a date range.
    Used by the dashboard chart on the Wati Integration workspace.

    Returns a list of {date, success, failed} dicts.

    BUG FIX #1 — SQL Injection: from_date / to_date were previously
    interpolated directly into the SQL string via an f-string, allowing
    any logged-in user to inject arbitrary SQL.  Now uses parameterised
    %s placeholders passed as a tuple to frappe.db.sql().

    BUG FIX #5 — Permission: added System Manager role check so that
    only authorised users can query message stats and mobile numbers.
    """
    # ── Permission guard (Fix #5) ─────────────────────────────────────────
    if "System Manager" not in frappe.get_roles():
        frappe.throw(frappe._("Not permitted"), frappe.PermissionError)

    # ── Build parameterised WHERE clause (Fix #1) ─────────────────────────
    conditions = ""
    values = []

    if from_date:
        conditions += " AND DATE(sent_at) >= %s"
        values.append(from_date)
    if to_date:
        conditions += " AND DATE(sent_at) <= %s"
        values.append(to_date)

    rows = frappe.db.sql(
        f"""
        SELECT
            DATE(sent_at)                                               AS date,
            SUM(CASE WHEN status_code = '200' THEN 1 ELSE 0 END)      AS success,
            SUM(CASE WHEN status_code != '200' THEN 1 ELSE 0 END)     AS failed
        FROM `tabWati Message Log`
        WHERE 1=1 {conditions}
        GROUP BY DATE(sent_at)
        ORDER BY date DESC
        LIMIT 30
        """,
        tuple(values) if values else None,
        as_dict=1,
    )
    return rows
