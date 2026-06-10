# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt
#
# v2.0.3 Security & Stability Patch
# Adds new columns required by the three fixes introduced in v2.0.3.
# Run automatically by: bench --site YOUR_SITE migrate
#
# What this patch does:
#   FIX #1 — webhook_secret on tabWati Setting (VARCHAR 140, default '')
#             Used by api.wati_webhook() to verify the X-Wati-Secret header.
#   FIX #2 — bulk_batch_size on tabWati Setting (INT, default 100)
#             Controls how many recipients are sent per background job batch.
#   FIX #3 — No schema change needed.
#             purge_old_logs() now uses frappe.db.delete() — pure Python change.
#
# All ADD COLUMN statements use IF NOT EXISTS (safe on MariaDB 10.3+).
# Existing data is never modified.

import frappe


def execute():
    """
    Add v2.0.3 columns to tabWati Setting.
    Safe to run on both fresh installs and existing v2.0.2 deployments.
    """

    setting_columns = [
        # FIX #1 — webhook_secret for DoS / flood protection on the guest endpoint
        "ALTER TABLE `tabWati Setting` ADD COLUMN IF NOT EXISTS "
        "`webhook_secret` VARCHAR(140) DEFAULT ''",

        # FIX #2 — bulk_batch_size controls the recipient page size for large sends
        "ALTER TABLE `tabWati Setting` ADD COLUMN IF NOT EXISTS "
        "`bulk_batch_size` INT DEFAULT 100",
    ]

    for sql in setting_columns:
        try:
            frappe.db.sql(sql)
        except Exception as e:
            # Log but do not abort — a column that already exists on an older
            # MariaDB version (which may not support IF NOT EXISTS) should not
            # break the entire migration run.
            frappe.log_error(
                title="Wati v2.0.3 patch: column add warning",
                message=f"SQL: {sql}\nError: {e}",
            )

    frappe.db.commit()
