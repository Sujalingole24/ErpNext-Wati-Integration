# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt
#
# ADDON v2.0.2 — Install hook
# Called by Frappe after the app is installed on a site.
# Ensures the Workspace fixture is synced immediately so the sidebar
# shows "Wati Integration" without needing a separate bench migrate.

import frappe


def after_install():
    """
    Sync Workspace fixture on fresh install so the sidebar module appears
    immediately without needing a manual bench migrate.

    BUG FIX: removed two unused imports:
      - make_records (frappe.desk.page.setup_wizard.setup_wizard)
      - sync_customizations (frappe.modules.utils)
    Both were imported but never called. On several Frappe v16 minor builds
    these import paths do not exist, causing an ImportError that swallowed
    the entire after_install() call silently.
    frappe.reload_doc() is the correct stable API; no other imports needed.
    """
    try:
        frappe.reload_doc("wati_integration", "workspace", "wati_integration", force=True)
        frappe.db.commit()
    except Exception:
        # Non-fatal — bench migrate will pick it up
        frappe.log_error(
            title="Wati: after_install workspace sync warning",
            message=frappe.get_traceback(),
        )
