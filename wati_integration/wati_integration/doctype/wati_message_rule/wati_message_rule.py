# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt

import re
import json
import requests
import frappe
from frappe.model.document import Document
from frappe.utils import parse_val, nowdate, now_datetime
from frappe import _

try:
    from frappe.utils.safe_exec import get_safe_globals
except ImportError:
    def get_safe_globals():
        return {}

from wati_integration.hooks import WATI_INTERNAL_DOCTYPES
from wati_integration.wati_integration.doctype.wati_setting.wati_setting import get_wati_settings


# ─── Exceptions ──────────────────────────────────────────────────────────────

class WatiRateLimitError(Exception):
    """
    Raised by send_whatsapp_message() when WATI returns HTTP 429.
    Caught by _send_one_with_retry() in send_wati_message.py so that
    bulk sends can back off and retry instead of silently dropping messages.
    Defined here (rather than in send_wati_message.py) to avoid a circular
    module-level import — send_wati_message imports send_whatsapp_message
    from this module, so any exception it raises must live here too.
    """
    pass


# ─── Phone number helper ─────────────────────────────────────────────────────

# E.164 bounds (WATI expects digits only, no leading '+')
_MIN_INTL_DIGITS = 11   # blocks bare 10-digit local numbers (India without 91)
_MAX_INTL_DIGITS = 15   # ITU E.164 maximum
_INDIA_CC        = "91"  # Country code auto-prepended for 10-digit Indian numbers

def sanitize_phone(number):
    """
    Normalize a phone number for the WATI API.
    WATI expects E.164 digits only, no leading '+', e.g. '919876543210'.

    India auto-prefix rule (all end-users are India-based):
      • Exactly 10 digits starting with 6, 7, 8 or 9  →  prepend '91'
        e.g. '9876543210' becomes '919876543210'
      • Any other 10-digit number is rejected (not a valid Indian mobile).

    After auto-prefix:
      • <11 digits  → logged and rejected (still missing country code)
      • >15 digits  → rejected (exceeds ITU E.164 maximum)
      • Non-digits or empty  → rejected

    Returns the cleaned E.164 string, or None for invalid numbers.
    """
    if not number:
        return None
    cleaned = re.sub(r"[\s\-().+]", "", str(number))
    if not cleaned.isdigit():
        return None

    # ── India 10-digit auto-prefix ────────────────────────────────────────
    if len(cleaned) == 10:
        if cleaned[0] in ("6", "7", "8", "9"):
            # Valid Indian mobile — prepend country code
            cleaned = _INDIA_CC + cleaned
        else:
            # 10-digit but not a valid Indian mobile pattern — reject
            frappe.log_error(
                title="Wati: Phone number missing country code",
                message=(
                    f"Number '{number}' (cleaned: '{cleaned}') has 10 digits but does not "
                    f"match an Indian mobile pattern (must start with 6/7/8/9). "
                    f"WATI requires a full international number, e.g. '91{cleaned}' for India. "
                    f"Message NOT sent. Fix the number in the source document."
                ),
            )
            return None

    # ── Length guard ──────────────────────────────────────────────────────
    if len(cleaned) < _MIN_INTL_DIGITS:
        frappe.log_error(
            title="Wati: Phone number missing country code",
            message=(
                f"Number '{number}' (cleaned: '{cleaned}') has only {len(cleaned)} digits. "
                f"WATI requires an international number with country code, "
                f"e.g. '91{cleaned}' for India. "
                f"Message NOT sent. Fix the number in the source document."
            ),
        )
        return None
    if len(cleaned) > _MAX_INTL_DIGITS:
        return None

    return cleaned


# ─── DocType class ───────────────────────────────────────────────────────────

class WatiMessageRule(Document):

    def validate(self):
        self.validate_mobile_no_field()
        if self.conditions:
            self.validate_condition()

    def validate_condition(self):
        temp_doc = frappe.new_doc(self.ref_doctype)
        try:
            frappe.safe_eval(self.conditions, None, get_context(temp_doc.as_dict()))
        except Exception:
            frappe.throw(_("The Condition '{0}' is invalid").format(self.conditions))

    def validate_mobile_no_field(self):
        if not (self.mobile_no_field or "").strip():
            frappe.throw(_("Select Mobile No Field Name."))
        self.mobile_no_field = self.mobile_no_field.strip()

    @frappe.whitelist()
    def set_variable(self):
        if self.message_template:
            template_doc = frappe.get_doc("Message Template", self.message_template)
            for variable in template_doc.template_variables.split(","):
                variable = variable.strip()
                if not variable:
                    continue
                if not frappe.db.exists("Template Variable", {
                    "template_variable": variable,
                    "parenttype": "Wati Message Rule",
                    "ref_doctype": self.ref_doctype,
                    "parent": self.name,
                }):
                    self.append("template_variable", dict(
                        template_variable=variable,
                        ref_doctype=self.ref_doctype,
                    ))
        else:
            self.template_variable = []

    @frappe.whitelist()
    def send_test_message(self, mobile_no):
        """
        ADDON: Send a test message for this rule to a given mobile number.
        Available as a button on the Wati Message Rule form.

        BUG FIX: @frappe.whitelist() alone makes this callable by ANY logged-in
        user — no role check means any user who can read a Wati Message Rule
        can trigger an outgoing WhatsApp send. Added System Manager guard.
        """
        frappe.only_for("System Manager")
        mobile = sanitize_phone(mobile_no)
        if not mobile:
            frappe.throw(_("Invalid mobile number: {0}").format(mobile_no))

        # Build dummy data from the template variables (empty values)
        data = []
        for field in self.template_variable:
            data.append({
                "name": field.get("template_variable"),
                "value": "[TEST]",
            })

        send_whatsapp_message(
            self.message_template,
            mobile,
            json.dumps(data),
            self.name,
            self.doctype,
            called_from_background=False,
        )


# ─── Safe eval context ───────────────────────────────────────────────────────

def get_context(doc):
    safe_globals = get_safe_globals()
    frappe_utils = safe_globals.get("frappe", {}).get("utils", {})
    return {
        "doc": doc,
        "nowdate": nowdate,
        "frappe": frappe._dict(utils=frappe_utils),
    }


# ─── Hook entry point ────────────────────────────────────────────────────────

def send_message_for_event(doc, method):
    """
    Called by doc_events hook for every doctype on every configured event.
    - Never raises — errors are logged silently.
    - Never calls frappe.db.commit() — inside a hook transaction.
    - Skips WATI-internal doctypes to prevent infinite recursion.
    """
    try:
        if doc.doctype in WATI_INTERNAL_DOCTYPES:
            return

        if (
            (frappe.flags.in_import and frappe.flags.mute_emails)
            or frappe.flags.in_patch
            or frappe.flags.in_install
        ):
            return

        get_message_rule(doc, doc.doctype, method)

    except Exception:
        frappe.log_error(title="Wati Error Log", message=frappe.get_traceback())


# ─── Rule evaluation ─────────────────────────────────────────────────────────

def get_message_rule(doc, doctype, method):
    event_map = {
        "on_submit":    "Submit",
        "after_insert": "New",
        "on_cancel":    "Cancel",
        "on_update":   "Save",
    }
    # NOTE: "on_change" is deliberately NOT in this map and NOT registered in
    # hooks.py — registering it with "*" fires a DB query on every single save
    # across the entire ERPNext instance.  Value Change rules are evaluated
    # inside the "after_save" path below, where get_doc_before_save() is still
    # available and old/new field values can be compared safely.

    based_on = event_map.get(method)
    if not based_on:
        return

    # For after_save on non-insert docs, also pick up Value Change rules —
    # they share the same hook but require old/new value comparison.
    based_on_filter = [based_on]
    if based_on == "Save" and not doc.flags.in_insert:
        based_on_filter.append("Value Change")

    rules = frappe.get_all(
        "Wati Message Rule",
        filters={"based_on": ["in", based_on_filter], "ref_doctype": doctype, "enable": 1},
        fields=["*"],
        limit=0,  # Fix #2 — never truncate at Frappe v16 default of 20 records
    )
    if rules:
        evaluate_message_rule(doc, rules)


def evaluate_message_rule(doc, rules):
    """
    Evaluate each rule against the current document.

    Fix #3 — based_on is now read from rule.based_on (per-rule) instead of
    being passed as a function argument.  This lets a single call process a
    mixed list of "Save" and "Value Change" rules returned by get_message_rule(),
    applying the correct logic for each rule type individually.

    Fix #7 — frappe.db.has_column() is cached per (doctype, field) pair before
    the loop runs.  The original called it inside the loop on every Value Change
    rule, issuing a separate INFORMATION_SCHEMA query for each rule even when
    multiple rules watch the same field.  The cache eliminates the redundant
    queries without changing any observable behaviour.
    """
    # Build a per-field column-existence cache for Value Change rules so
    # frappe.db.has_column() is called at most once per unique field name,
    # not once per rule.
    _col_cache = {}

    for rule in rules:
        context = get_context(doc)

        if rule.conditions:
            try:
                result = frappe.safe_eval(rule.conditions, None, context)
            except Exception:
                frappe.log_error(
                    title="Wati Condition Eval Error",
                    message=frappe.get_traceback(),
                )
                continue
            if not result:
                continue

        # Value Change rules: only fire when the watched field actually changed.
        # evaluated here (during after_save) rather than on_change — see the
        # comment in get_message_rule() for the reason on_change is excluded.
        if rule.based_on == "Value Change" and not doc.is_new():
            field = rule.fields
            if field not in _col_cache:
                _col_cache[field] = frappe.db.has_column(doc.doctype, field)
            if not _col_cache[field]:
                continue
            doc_before = doc.get_doc_before_save()
            old_value = parse_val(doc_before.get(field) if doc_before else None)
            if doc.get(field) == old_value:
                continue

        send_message_using_template(doc, rule)


# ─── Message sending ─────────────────────────────────────────────────────────

def send_message_using_template(doc, rule):
    rule_doc = frappe.get_doc("Wati Message Rule", rule.name)
    data = []
    for field in rule_doc.template_variable:
        data.append({
            "name":  field.get("template_variable"),
            "value": str(doc.get(field.get("document_variable")) or ""),
        })

    raw_mobile = doc.get(rule_doc.mobile_no_field)
    mobile = sanitize_phone(raw_mobile)

    if not mobile:
        frappe.log_error(
            title="Wati: Missing or Invalid Mobile Number",
            message=(
                f"Rule '{rule_doc.name}' — field '{rule_doc.mobile_no_field}' "
                f"is empty or invalid on {doc.doctype} {doc.name} "
                f"(raw value: {raw_mobile!r})"
            ),
        )
        return

    send_whatsapp_message(
        rule_doc.message_template,
        mobile,
        json.dumps(data),
        doc.name,
        doc.doctype,
        rule_name=rule_doc.name,  # ADDON v2.0.2 — pass rule name for log
    )


def send_whatsapp_message(template, mobile, data, document, doctype,
                          called_from_background=False,
                          rule_name=""):
    """
    Core message sender.

    - Uses get_wati_settings() — safe on fresh installs (no DoesNotExistError).
    - 15-second timeout on all HTTP calls.
    - Raises WatiRateLimitError on HTTP 429 so _bulk_send() can retry.
    - Logs token as 'Bearer ***' — never stores the plain token.
    - No frappe.db.commit() — safe inside hook transactions.
    - bulk_send_delay, max_retries, retry_wait_seconds are read from Wati Setting.
    - ADDON v2.0.2: Checks global enabled kill switch before sending.
    - ADDON v2.0.2: Logs message_template and wati_rule to Wati Message Log.

    BUG FIX #3 — sent_at field: The wati_message_log.json schema replaced the
    broken fetch_from="creation" Read Only field (which showed blank in Frappe v16
    list view) with a proper Datetime field called 'sent_at'.  This function now
    explicitly sets sent_at = now_datetime() on every log insert so the "Sent At"
    column in the Message Log list view shows the correct timestamp.
    """
    wati_setting = get_wati_settings()
    if not wati_setting:
        msg = _(
            "Wati Setting is not configured. "
            "Please save URL, WhatsApp Number, and API Token before sending messages."
        )
        if called_from_background:
            frappe.log_error(title="Wati Config Error", message=msg)
            return
        frappe.throw(msg)

    # ADDON v2.0.2 — Global kill switch check
    # wati_setting is a Frappe Document object; use getattr with fallback.
    # wati_setting.get() exists on Document but defaults to None not 1 when the
    # column was added by the patch and has never been explicitly set on this record.
    if int(getattr(wati_setting, "enabled", 1) or 1) == 0:
        if not called_from_background:
            frappe.msgprint(
                _("WATI sending is currently disabled. Enable it in Wati Setting."),
                alert=True, indicator="orange",
            )
        return

    clean_mobile = sanitize_phone(mobile)
    if not clean_mobile:
        frappe.log_error(
            title="Wati: Invalid Phone Number",
            message=f"Cannot send to '{mobile}' — not a valid phone number.",
        )
        return

    # WATI v1 API: recipient goes in ?whatsappNumber= query param (NOT in the URL path).
    # The sender's business number goes in channel_number in the request body.
    # Previous code had them swapped: mobile was in the path and business number
    # was in ?whatsappNumber=, which caused all sends to fail silently.
    base_url = (
        wati_setting.url
        + "/api/v1/sendTemplateMessage"
        + "?whatsappNumber="
        + clean_mobile
    )

    payload = json.dumps({
        "template_name":  template,
        "broadcast_name": template,
        "parameters":     json.loads(data) if isinstance(data, str) else data,
        # channel_number is REQUIRED by WATI v1 API — the sender's WhatsApp business number.
        "channel_number": sanitize_phone(wati_setting.whatsapp_number),
    })

    headers = {
        "Authorization": "Bearer " + wati_setting._decrypted_token,
        "Content-Type":  "application/json",
    }

    try:
        response = requests.post(base_url, data=payload, headers=headers, timeout=15)
        status_code = response.status_code
        response_text = response.text
    except requests.exceptions.Timeout:
        status_code = 0
        response_text = "Request timed out after 15 seconds"
    except requests.exceptions.ConnectionError as exc:
        status_code = 0
        response_text = f"Connection error: {exc}"
    except requests.exceptions.RequestException as exc:
        status_code = 0
        response_text = str(exc)

    is_rate_limited = (status_code == 429)

    # ── Parse WATI response body (200 ≠ delivered) ────────────────────────
    # WATI can return HTTP 200 but {"result": false, "info": "...reason..."}.
    # This happens when WhatsApp quality rating is low, opt-in is missing, etc.
    wati_result = True   # optimistic default if body cannot be parsed
    wati_info   = ""
    if status_code == 200:
        try:
            resp_json   = response.json()
            wati_result = resp_json.get("result", True)
            wati_info   = resp_json.get("info", "")
        except Exception:
            wati_result = True
            wati_info   = response_text

        if not wati_result:
            frappe.log_error(
                title="Wati: Delivery Rejected by WhatsApp",
                message=(
                    "Mobile: {} | Template: {}\n"
                    "WATI info: {}\n"
                    "HTTP 200 but result=false — likely quality rating or opt-in issue.\n"
                    "Check WhatsApp Manager → Phone Numbers → Quality Rating in Meta dashboard."
                ).format(clean_mobile, template, wati_info),
            )

    # Log with masked token
    log_headers = {k: ("Bearer ***" if k == "Authorization" else v) for k, v in headers.items()}
    try:
        frappe.get_doc(dict(
            doctype          = "Wati Message Log",
            mobile_no        = clean_mobile,
            url              = base_url,
            payload          = payload,
            headers          = json.dumps(log_headers),
            status_code      = str(status_code),
            response         = response_text,
            document         = document,
            ref_doctype      = doctype,
            sent_at          = now_datetime(),   # FIX #3 — populate the real Datetime field
            direction        = "Outgoing",       # ADDON v2.0.2
            message_template = template or "",   # ADDON v2.0.2
            wati_rule        = rule_name or "",  # ADDON v2.0.2
        )).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(
            title="Wati: Failed to write Message Log",
            message=frappe.get_traceback(),
        )

    if is_rate_limited:
        raise WatiRateLimitError(
            f"WATI returned HTTP 429 (rate limited) for {clean_mobile}."
        )

    if not called_from_background:
        if status_code == 200:
            frappe.msgprint(
                _("WhatsApp message sent to {0}").format(clean_mobile),
                alert=True, indicator="green",
            )
        else:
            frappe.msgprint(
                _("WhatsApp message failed for {0} (HTTP {1})").format(clean_mobile, status_code),
                alert=True, indicator="red",
            )
    else:
        if status_code not in (200, 429):
            frappe.log_error(
                title="Wati: Message Send Failed",
                message=(
                    f"Mobile: {clean_mobile} | Template: {template} | "
                    f"HTTP {status_code}\n{response_text}"
                ),
            )
