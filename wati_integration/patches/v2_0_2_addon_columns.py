# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt
#
# ADDON v2.0.2 Migration Patch
# Adds new columns to existing tables without touching existing data.
# Run automatically by: bench --site YOUR_SITE migrate

import frappe


def execute():
    """
    Safely add new columns introduced in v2.0.2 to existing installations.
    All ADD COLUMN statements use IF NOT EXISTS (MariaDB 10.3+ / MySQL 8+).
    Frappe v16 ships with MariaDB >= 10.6, so this is always safe.
    """

    # ── tabWati Message Log: new columns ──────────────────────────────────────
    log_columns = [
        # direction field — Outgoing / Incoming / Status Update
        "ALTER TABLE `tabWati Message Log` ADD COLUMN IF NOT EXISTS "
        "`direction` VARCHAR(20) DEFAULT 'Outgoing'",

        # message_template — template name used for this log entry
        "ALTER TABLE `tabWati Message Log` ADD COLUMN IF NOT EXISTS "
        "`message_template` VARCHAR(140) DEFAULT ''",

        # wati_rule — rule name that triggered this message
        "ALTER TABLE `tabWati Message Log` ADD COLUMN IF NOT EXISTS "
        "`wati_rule` VARCHAR(140) DEFAULT ''",
    ]

    # ── tabWati Setting: new columns ──────────────────────────────────────────
    setting_columns = [
        # enabled kill switch — 1 = sending active (default), 0 = paused
        "ALTER TABLE `tabWati Setting` ADD COLUMN IF NOT EXISTS "
        "`enabled` TINYINT(1) DEFAULT 1",

        # log_retention_days — 0 = no cleanup
        "ALTER TABLE `tabWati Setting` ADD COLUMN IF NOT EXISTS "
        "`log_retention_days` INT DEFAULT 90",
    ]

    # ── tabWati Message Rule: description field ───────────────────────────────
    rule_columns = [
        "ALTER TABLE `tabWati Message Rule` ADD COLUMN IF NOT EXISTS "
        "`description` TEXT",
    ]

    # ── tabSend Wati Message: contact and custom_mobile_no fields ─────────────
    send_msg_columns = [
        "ALTER TABLE `tabSend Wati Message` ADD COLUMN IF NOT EXISTS "
        "`contact` VARCHAR(140) DEFAULT ''",

        "ALTER TABLE `tabSend Wati Message` ADD COLUMN IF NOT EXISTS "
        "`custom_mobile_no` VARCHAR(140) DEFAULT ''",
    ]

    # ── tabWati Group Details: member_name display column ─────────────────────
    group_detail_columns = [
        "ALTER TABLE `tabWati Group Details` ADD COLUMN IF NOT EXISTS "
        "`member_name` VARCHAR(140) DEFAULT ''",
    ]

    all_statements = (
        log_columns
        + setting_columns
        + rule_columns
        + send_msg_columns
        + group_detail_columns
    )

    for sql in all_statements:
        try:
            frappe.db.sql(sql)
        except Exception as e:
            # Log but don't abort — a column that already exists (older MariaDB)
            # or a table that doesn't exist yet (fresh install) should not break migration.
            frappe.log_error(
                title="Wati v2.0.2 patch: column add warning",
                message=f"SQL: {sql}\nError: {e}",
            )

    frappe.db.commit()
