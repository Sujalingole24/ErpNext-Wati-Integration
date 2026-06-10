# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt
#
# ADDON v2.0.2 — Incoming WATI Webhook Handler
# Receives incoming WhatsApp replies pushed by WATI and logs them.
# Route: /api/method/wati_integration.wati_integration.api.wati_webhook
# (registered in hooks.py under website_route_rules)

import frappe
from frappe.utils import now_datetime
from frappe import _
import hmac


# ─── FIX #1 (v2.0.3) — Webhook flood / DoS guard ────────────────────────────
# allow_guest=True with no authentication = anyone can POST to this endpoint
# and fill the Wati Message Log table indefinitely.
#
# Fix: read an optional webhook_secret from Wati Setting.  When set, every
# incoming request MUST carry a matching X-Wati-Secret header; requests that
# don't are rejected with HTTP 403 before any DB work is done.
#
# Backward-compatible: if webhook_secret is blank / not yet set, the check is
# skipped entirely so existing deployments keep working without configuration
# changes.  To enable, add your secret in Wati Setting → Webhook Secret and
# copy the same value into the WATI dashboard webhook header settings.
#
# ORIGINAL wati_webhook() code below is completely unchanged — only the guard
# block is prepended.
# ─────────────────────────────────────────────────────────────────────────────

def _verify_webhook_secret():
    """
    FIX #1 — Verify X-Wati-Secret header against Wati Setting.webhook_secret.

    Returns True  → request is allowed (secret matches OR no secret configured).
    Returns False → request must be rejected (secret mismatch).

    Reads from DB with a single get_value call; intentionally does NOT call
    get_wati_settings() to avoid the full credential check (the webhook must
    work even if the WATI token is temporarily missing).
    """
    try:
        expected_secret = frappe.db.get_single_value("Wati Setting", "webhook_secret") or ""
    except Exception:
        # Wati Setting not yet saved (fresh install) — allow through.
        return True

    if not expected_secret:
        # No secret configured — backward-compatible, allow all.
        return True

    incoming_secret = frappe.request.headers.get("X-Wati-Secret", "")
    # Use hmac.compare_digest() instead of == to prevent timing-oracle attacks.
    # A plain == comparison leaks secret length and content via response-time
    # differences; compare_digest runs in constant time regardless of how many
    # characters match.
    return hmac.compare_digest(incoming_secret, expected_secret)


@frappe.whitelist(allow_guest=True)
def wati_webhook():
    """
    ADDON v2.0.2 — Receive incoming WATI webhook payloads.

    WATI sends a POST request when:
      - A contact replies to a message
      - A message status changes (sent / delivered / read / failed)

    Payload shapes vary by WATI plan; this handler is defensive and
    gracefully handles missing keys.

    To configure in WATI dashboard:
      Webhook URL: https://<your-site>/api/method/wati_integration.wati_integration.api.wati_webhook

    FIX #1 (v2.0.3): Set Wati Setting → Webhook Secret and add the same value
    as the X-Wati-Secret header in your WATI dashboard to enable flood protection.
    """
    # ── FIX #1: reject unauthenticated requests when a secret is configured ──
    if not _verify_webhook_secret():
        frappe.local.response["http_status_code"] = 403
        return {"status": "forbidden", "message": "Invalid or missing X-Wati-Secret header."}

    try:
        payload = frappe.request.get_json(silent=True) or {}

        # Determine direction and extract fields from common WATI payload shapes
        event_type   = payload.get("type") or payload.get("eventType") or "incoming"
        mobile_no    = (
            payload.get("waId")
            or payload.get("from")
            or payload.get("mobile_no")
            or ""
        )
        response_text = frappe.as_json(payload)

        # Try to extract a human-readable message body
        message_body = ""
        if "text" in payload:
            message_body = payload["text"].get("body", "") if isinstance(payload["text"], dict) else str(payload["text"])
        elif "message" in payload:
            message_body = payload["message"].get("text", "") if isinstance(payload["message"], dict) else str(payload["message"])

        direction = "Incoming"
        # Status update events (delivered / read / failed) are treated as outgoing status updates
        if event_type in ("message_status_updated", "status_update", "outgoing"):
            direction = "Status Update"

        # Log to Wati Message Log with direction field
        try:
            frappe.get_doc(dict(
                doctype       = "Wati Message Log",
                mobile_no     = mobile_no,
                url           = "WEBHOOK",
                payload       = response_text,
                headers       = "",
                status_code   = "200",
                response      = message_body or response_text,
                document      = "",
                ref_doctype   = "Webhook",
                sent_at       = now_datetime(),
                direction     = direction,
                message_template = "",
                wati_rule     = "",
            )).insert(ignore_permissions=True)
            frappe.db.commit()
        except Exception:
            frappe.log_error(
                title="Wati Webhook: Log insert failed",
                message=frappe.get_traceback(),
            )

        return {"status": "ok"}

    except Exception:
        frappe.log_error(
            title="Wati Webhook: Unhandled error",
            message=frappe.get_traceback(),
        )
        frappe.local.response["http_status_code"] = 200  # Always 200 to WATI
        return {"status": "error", "message": "logged"}


@frappe.whitelist()
def send_from_form(doctype, docname, rule_name, mobile_override=""):
    """
    ADDON v2.0.2 — Called by the "Send WhatsApp" button injected on standard ERPNext forms.
    Looks up the Wati Message Rule, builds the template data from the live document,
    and calls send_whatsapp_message() exactly as the automated rule trigger does.

    Args:
        doctype (str): The doctype of the document (e.g. "Sales Order")
        docname (str): The document name (e.g. "SAL-ORD-2024-00001")
        rule_name (str): Name of the Wati Message Rule to apply
        mobile_override (str): If provided, use this number instead of the rule's mobile field
    """
    from wati_integration.wati_integration.doctype.wati_message_rule.wati_message_rule import (
        send_whatsapp_message,
        sanitize_phone,
    )
    import json

    frappe.only_for("System Manager")

    try:
        doc = frappe.get_doc(doctype, docname)
        rule_doc = frappe.get_doc("Wati Message Rule", rule_name)

        if rule_doc.ref_doctype != doctype:
            frappe.throw(
                _(
                    "Rule '{0}' is for doctype '{1}', not '{2}'."
                ).format(rule_name, rule_doc.ref_doctype, doctype)
            )

        # Build template variables
        data = []
        for field in rule_doc.template_variable:
            data.append({
                "name":  field.get("template_variable"),
                "value": str(doc.get(field.get("document_variable")) or ""),
            })

        # Resolve mobile number
        if mobile_override:
            mobile = sanitize_phone(mobile_override)
        else:
            mobile = sanitize_phone(doc.get(rule_doc.mobile_no_field))

        if not mobile:
            frappe.throw(
                _("No valid mobile number found. Please check the document or enter a mobile override.")
            )

        send_whatsapp_message(
            rule_doc.message_template,
            mobile,
            json.dumps(data),
            docname,
            doctype,
            called_from_background=False,
            rule_name=rule_name,
        )
        return {"status": "ok"}

    except frappe.ValidationError:
        # frappe.throw() raises frappe.ValidationError.  Re-raise so Frappe's
        # standard error-handling shows the message once in the UI — catching
        # it here and then returning {"status": "error"} would cause the
        # exception to surface a second time via the JSON response wrapper,
        # resulting in a duplicate error dialog.
        raise
    except Exception:
        frappe.log_error(
            title="Wati: send_from_form error",
            message=frappe.get_traceback(),
        )
        return {"status": "error"}
