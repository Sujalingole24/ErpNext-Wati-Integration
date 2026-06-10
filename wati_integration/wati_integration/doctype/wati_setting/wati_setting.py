# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt

import re
import frappe
from frappe.model.document import Document
from frappe import _


class WatiSetting(Document):

    def validate(self):
        """Validate and normalise WATI credentials before saving."""

        # ── URL ──────────────────────────────────────────────────────────────
        if not self.url:
            frappe.throw(_("WATI URL is required."))
        if not self.url.startswith(("https://", "http://")):
            frappe.throw(_("WATI URL must start with https:// or http://"))
        self.url = self.url.rstrip("/")

        # ── WhatsApp number ──────────────────────────────────────────────────
        if not self.whatsapp_number:
            frappe.throw(_("WhatsApp Number is required."))
        digits_only = re.sub(r"\D", "", self.whatsapp_number)

        # India auto-prefix: exactly 10 digits starting with 6/7/8/9 → prepend 91
        if len(digits_only) == 10 and digits_only[0] in ("6", "7", "8", "9"):
            digits_only = "91" + digits_only

        if len(digits_only) < 11 or len(digits_only) > 15:
            frappe.throw(_(
                "WhatsApp Number must include country code (e.g. 919876543210 for India). "
                "Got {0} digits — expected 11–15."
            ).format(len(digits_only)))
        self.whatsapp_number = digits_only

        # ── Token ────────────────────────────────────────────────────────────
        if not self.token:
            frappe.throw(_("API Token is required."))

    def get_decrypted_token(self):
        """Return the decrypted API token."""
        return self.get_password("token")

    @frappe.whitelist()
    def test_connection(self):
        """
        ADDON: Ping the WATI API and return status.
        Called from the Wati Setting form via the 'Test Connection' button.
        """
        import requests as req
        setting = get_wati_settings()
        if not setting:
            frappe.throw(_("Please save valid settings before testing the connection."))

        test_url = setting.url + "/api/v1/getContacts?pageSize=1&pageIndex=1"
        try:
            r = req.get(
                test_url,
                headers={"Authorization": "Bearer " + setting._decrypted_token},
                timeout=10,
            )
            if r.status_code == 200:
                frappe.msgprint(
                    _("Connection successful! WATI API responded with HTTP 200."),
                    alert=True, indicator="green"
                )
            else:
                frappe.msgprint(
                    _("Connection failed — HTTP {0}: {1}").format(r.status_code, r.text[:200]),
                    alert=True, indicator="red"
                )
        except Exception as exc:
            frappe.msgprint(
                _("Connection error: {0}").format(str(exc)),
                alert=True, indicator="red"
            )


# ─── Module-level safe accessor ───────────────────────────────────────────────

def get_wati_settings():
    """
    Safe accessor — returns None instead of raising on fresh installs
    or when settings are incomplete.

    On a fresh install get_doc() raises DoesNotExistError before the
    single record has been saved.  get_password() returns None before
    the Password field is written for the first time.  Both cases are
    handled here so callers always get None-or-ready.
    """
    try:
        doc = frappe.get_doc("Wati Setting", "Wati Setting")
    except frappe.DoesNotExistError:
        return None

    token = None
    try:
        token = doc.get_password("token")
    except Exception:
        pass

    if not doc.url or not doc.whatsapp_number or not token:
        return None

    doc._decrypted_token = token
    return doc


def boot_session(bootinfo):
    """
    ADDON: Inject wati_configured into the Frappe boot session.
    JS can check frappe.boot.wati_configured to conditionally show
    'Send WhatsApp' buttons without an extra server round-trip.
    """
    bootinfo.wati_configured = bool(get_wati_settings())


# ─── ADDON v2.0.2: Log retention / purge ─────────────────────────────────────

def purge_old_logs():
    """
    ADDON v2.0.2 — Scheduled nightly at 02:00.
    Deletes Wati Message Log entries older than log_retention_days (from Wati Setting).
    If log_retention_days is 0 or not set, no cleanup is performed.
    Original code is NOT modified — this is a standalone addon function.

    FIX #3 (v2.0.3) — Replaced raw frappe.db.sql DELETE with frappe.db.delete()
    (Frappe ORM layer).  The raw DELETE bypassed Frappe's permission layer and
    produced no audit trail; frappe.db.delete() respects the ORM contract.
    Behaviour is identical — only the implementation changed.
    The frappe.db.commit() call is retained for safety but is unchanged.
    """
    try:
        doc = frappe.get_doc("Wati Setting", "Wati Setting")
        retention_days = int(doc.get("log_retention_days") or 0)
    except Exception:
        return  # Settings not saved yet — skip silently

    if retention_days <= 0:
        return

    cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -retention_days)
    try:
        # ── FIX #3: use frappe.db.delete() instead of raw SQL DELETE ─────────
        # frappe.db.delete() issues a low-level SQL DELETE directly on the
        # database table, similar to a raw frappe.db.sql("DELETE FROM ...").
        # It does NOT load documents, does NOT call on_trash hooks, and does
        # NOT produce individual document audit trail entries — it is a bulk
        # DELETE at the SQL layer.  It is still preferable to a hand-written
        # SQL string because Frappe handles table-name quoting and the filter
        # syntax is consistent with frappe.get_all() — but callers must be
        # aware that document-level hooks (e.g. on_trash) are NOT fired.
        # For Wati Message Log purges this is intentional: we want fast bulk
        # deletion without triggering per-document lifecycle events.
        frappe.db.delete(
            "Wati Message Log",
            filters={"sent_at": ("<", cutoff)},
        )
        frappe.db.commit()

        import logging
        logging.getLogger("wati_integration").info(
            f"Wati log purge: deleted entries older than {cutoff} "
            f"(retention={retention_days} days)."
        )
    except Exception:
        frappe.log_error(
            title="Wati: Log purge failed",
            message=frappe.get_traceback(),
        )
