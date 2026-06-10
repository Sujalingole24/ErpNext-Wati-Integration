from . import __version__ as app_version

app_name        = "wati_integration"
app_title       = "Wati Integration"
app_publisher   = "Bhavesh Maheshwari"
app_description = "WATI WhatsApp Integration for ERPNext / Frappe v16"
app_email       = "iambhavesh95863@gmail.com"
app_license     = "MIT"

# ─── v2.0.2 ADDON: JS assets injected into all ERPNext desk pages ─────────────
app_include_js = [
    "/assets/wati_integration/js/wati_send_button.js"
]

# ─── Internal doctypes — excluded from message hook to prevent recursion ──────
WATI_INTERNAL_DOCTYPES = {
    "Wati Message Log",
    "Wati Message Rule",
    "Wati Setting",
    "Send Wati Message",
    "Message Template",
    "Wati Group",
    "Wati Group Details",
    "Template Variable",
    "Send Message Variables",
}

# ─── Document Events ──────────────────────────────────────────────────────────
# "on_change" deliberately excluded — with wildcard "*" it fires a DB query on
# every single save in the entire ERPNext instance (see Issue #1).
# Value Change rules work via after_save; the event_map in get_message_rule()
# handles the mapping internally.
doc_events = {
    "*": {
        "on_submit":    "wati_integration.wati_integration.doctype.wati_message_rule.wati_message_rule.send_message_for_event",
        "after_insert": "wati_integration.wati_integration.doctype.wati_message_rule.wati_message_rule.send_message_for_event",
        "on_cancel":    "wati_integration.wati_integration.doctype.wati_message_rule.wati_message_rule.send_message_for_event",
        "on_update": "wati_integration.wati_integration.doctype.wati_message_rule.wati_message_rule.send_message_for_event",
    }
}

# ─── Scheduled Tasks ──────────────────────────────────────────────────────────
scheduler_events = {
    "cron": {
        # Runs every minute — picks up scheduled messages
        "* * * * *": [
            "wati_integration.wati_integration.doctype.send_wati_message.send_wati_message.cron_job_for_schedule_message"
        ],
        # Runs every day at 08:00 — daily digest summary (addon feature)
        "0 8 * * *": [
            "wati_integration.wati_integration.doctype.send_wati_message.send_wati_message.daily_delivery_digest"
        ],
        # ADDON v2.0.2 — Runs every day at 02:00 — purge old Message Logs
        "0 2 * * *": [
            "wati_integration.wati_integration.doctype.wati_setting.wati_setting.purge_old_logs"
        ],
    }
}

# ─── v2.0.2 ADDON: Website route for WATI incoming webhook ───────────────────
# WATI will POST to: https://<your-site>/api/method/wati_integration.wati_integration.api.wati_webhook
# No additional website_route_rules needed — frappe.whitelist(allow_guest=True) handles it.

# ─── Whitelisted Methods (callable from client JS) ────────────────────────────
# Expose the test-connection helper so Wati Setting can ping the API from UI
override_whitelisted_methods = {}

# ─── Boot Session ─────────────────────────────────────────────────────────────
# Injects wati_configured flag into the boot session so JS can show/hide
# the "Send WhatsApp" button without an extra server call
boot_session = "wati_integration.wati_integration.doctype.wati_setting.wati_setting.boot_session"

# ─── Fixtures ─────────────────────────────────────────────────────────────────
# Ensures the Workspace, Dashboard Chart Source, Dashboard Chart, and Number
# Cards are created/updated on every bench migrate.
# Without this, the Wati Integration workspace and dashboard widgets never
# appear after a fresh install.
fixtures = [
    {
        "dt": "Workspace",
        "filters": [["module", "=", "Wati Integration"]]
    },
    {
        "dt": "Dashboard Chart Source",
        "filters": [["module", "=", "Wati Integration"]]
    },
    {
        "dt": "Dashboard Chart",
        "filters": [["module", "=", "Wati Integration"]]
    },
    {
        "dt": "Number Card",
        "filters": [["module", "=", "Wati Integration"]]
    },
]

# ─── Install hook ─────────────────────────────────────────────────────────────
# Syncs the Workspace immediately on fresh install so sidebar appears
# without needing a manual bench migrate.
after_install = "wati_integration.wati_integration.install.after_install"
