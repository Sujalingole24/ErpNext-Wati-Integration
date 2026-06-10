# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt

import logging
import time
import json
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, nowdate
from frappe import _
from wati_integration.wati_integration.doctype.wati_message_rule.wati_message_rule import (
    send_whatsapp_message,
    sanitize_phone,
    WatiRateLimitError,
)

logger = logging.getLogger("wati_integration")


# WatiRateLimitError is defined in wati_message_rule.py (where send_whatsapp_message lives)
# and imported above — no circular dependency.

# ─── FIX #2 (v2.0.3) — Bulk-send batch size ──────────────────────────────────
# The original _bulk_send() + _send_one_with_retry() calls time.sleep() inline
# inside the long-queue worker thread.  For small lists this is fine, but for
# large sends (500+ recipients) a single 429 retry sequence can block the worker
# for minutes, starving every other long-queue job on that worker.
#
# Fix: _bulk_send() now splits the recipient list into pages of BULK_BATCH_SIZE
# records and re-enqueues each page as a separate background job.  Each batch
# job handles at most BULK_BATCH_SIZE recipients, so a 429 sleep only blocks
# that worker for that batch's retry duration — other jobs keep running.
#
# BULK_BATCH_SIZE is read from Wati Setting → bulk_batch_size (new field added
# by the v2.0.3 migration patch).  It defaults to 100 when not set.
# Set to 0 to disable batching and use the original single-job behaviour.
#
# The original _send_one_with_retry() and all other functions are UNCHANGED.
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_BULK_BATCH_SIZE = 100


def _get_bulk_batch_size():
    """
    FIX #2 — Read bulk_batch_size from Wati Setting.
    Returns 0 if batching is disabled, _DEFAULT_BULK_BATCH_SIZE as fallback.
    """
    try:
        val = frappe.db.get_single_value("Wati Setting", "bulk_batch_size")
        return int(val or _DEFAULT_BULK_BATCH_SIZE)
    except Exception:
        return _DEFAULT_BULK_BATCH_SIZE


class SendWatiMessage(Document):

    def validate(self):
        if self.when_to_send == "Schedule" and not self.schedule_date_and_time:
            frappe.throw(_(
                "Please set 'Schedule Date And Time' before submitting a scheduled message."
            ))

    @frappe.whitelist()
    def get_variables(self):
        """
        Populate the template variable child table from the chosen Message Template.

        BUG FIX (v2.0.3) — Returns the variable list explicitly so the JS callback
        can use frm.clear_table() / frm.add_child() to rebuild the grid properly.
        Relying solely on Frappe's automatic r.docs sync was unreliable in Frappe v16:
        child rows generated via self.append() carry auto-generated local names that
        frappe.model.sync() may not merge correctly, causing the variables grid to
        appear empty until a manual page reload.
        """
        if self.message_template:
            self.send_message_variables = []
            template_doc = frappe.get_doc("Message Template", self.message_template)
            for var in (template_doc.template_variables or "").split(","):
                var = var.strip()
                if var:
                    self.append("send_message_variables", dict(template_variable=var))
        else:
            self.send_message_variables = []

        # Return a plain list of dicts so the JS callback can rebuild the grid
        # without depending on frappe.model.sync() for child-table new-row handling.
        return [
            {"template_variable": row.template_variable, "value": row.value or ""}
            for row in self.send_message_variables
        ]

    def on_submit(self):
        if self.when_to_send == "Now":
            # BUG FIX #2 — enqueue_after_commit was removed in Frappe v15.30+ / v16.
            # The old kwarg raised TypeError in some v16 minor versions, silently failing
            # all immediate sends.  The correct v16 pattern is frappe.db.after_commit.add()
            # which guarantees the job is enqueued only after the document transaction
            # commits, preserving the original intent.
            doc_name = self.name
            frappe.db.after_commit.add(lambda: frappe.enqueue(
                "wati_integration.wati_integration.doctype.send_wati_message"
                ".send_wati_message.enqueue_send_message",
                send_sms_data=[{"name": doc_name}],
                queue="long",
            ))
        else:
            # Scheduled messages: nothing to do here.
            # The cron job (cron_job_for_schedule_message) picks up all submitted
            # docs where sent=0 and schedule_date_and_time <= now.
            # There is no 'status' field on this doctype — that line was a bug.
            pass

    @frappe.whitelist()
    def get_delivery_summary(self):
        """
        ADDON: Return a delivery summary for this document.
        Shows how many logs exist, breakdown by status code.
        """
        logs = frappe.get_all(
            "Wati Message Log",
            filters={"document": self.name},
            fields=["status_code", "mobile_no", "response"],
            limit=0,  # Fix #6 guard: return all logs, not the default 20
        )
        summary = {}
        for log in logs:
            code = log.get("status_code") or "unknown"
            summary[code] = summary.get(code, 0) + 1

        return {
            "total": len(logs),
            "by_status": summary,
        }


# ─── Cron job ────────────────────────────────────────────────────────────────

@frappe.whitelist()
def cron_job_for_schedule_message():
    """Every minute: pick up scheduled messages whose time has come."""
    pending = frappe.db.sql(
        """
        SELECT name
        FROM `tabSend Wati Message`
        WHERE docstatus = 1
          AND sent = 0
          AND schedule_date_and_time IS NOT NULL
          AND schedule_date_and_time <= %s
        """,
        now_datetime(),
        as_dict=1,
    )
    if pending:
        frappe.enqueue(enqueue_send_message, send_sms_data=pending, queue="long")


def enqueue_send_message(send_sms_data):
    """Process each pending message document in the background queue."""
    for row in send_sms_data:
        try:
            doc = frappe.get_doc("Send Wati Message", row["name"])
            send_message(doc)
            # Only mark sent=1 after a successful send_message() call.
            # If send_message() raises, the except block below logs the error
            # and leaves sent=0 so the cron job can retry on the next run.
            frappe.db.set_value("Send Wati Message", row["name"], "sent", 1)
            frappe.db.commit()
        except Exception:
            frappe.log_error(
                title="Wati: Failed to send scheduled message",
                message=frappe.get_traceback(),
            )
            # Do NOT set sent=1 here — leave sent=0 so the scheduler retries.


# ─── ADDON: Daily digest ──────────────────────────────────────────────────────

def daily_delivery_digest():
    """
    ADDON: Runs every day at 08:00 via scheduler_events.
    Counts yesterday's Wati Message Log entries by status code and writes
    a summary to the application log.

    BUG FIX #7 — The original used frappe.log_error() for informational data,
    which creates noisy "error" alerts in the Error Log for System Managers.
    Now uses Python's standard logger so digests appear in the bench log
    (logs/worker.error.log) as INFO entries — not as errors.
    """
    yesterday = frappe.utils.add_days(nowdate(), -1)

    rows = frappe.db.sql(
        """
        SELECT status_code, COUNT(*) as cnt
        FROM `tabWati Message Log`
        WHERE DATE(sent_at) = %s
        GROUP BY status_code
        """,
        yesterday,
        as_dict=1,
    )

    if not rows:
        return  # Nothing to report

    lines = [f"Wati delivery digest for {yesterday}:"]
    total = 0
    for row in rows:
        lines.append(f"  HTTP {row['status_code']}: {row['cnt']} messages")
        total += row["cnt"]
    lines.append(f"  Total: {total}")

    logger.info("\n".join(lines))


# ─── Routing ─────────────────────────────────────────────────────────────────

def send_message(doc):
    dispatch = {
        "All Supplier":   send_message_supplier,
        "All Employee":   send_message_employee,
        "All Customer":   send_message_customer,
        "All Lead":       send_message_lead,
        "Group":          send_message_group,
        # ADDON v2.0.2 — new targets
        "Single Contact": send_message_single_contact,
        "Custom Number":  send_message_custom_number,
    }
    handler = dispatch.get(doc.message_send_to)
    if handler:
        handler(doc)
    else:
        frappe.log_error(
            title="Wati: Unknown message_send_to",
            message=f"'{doc.message_send_to}' is not a recognised target in {doc.name}",
        )


def send_message_supplier(doc):
    # BUG FIX #6 — limit=0 added to all bulk get_all() calls.
    # Frappe v16 defaults get_all() to 20 records when no limit is specified,
    # silently truncating large installs and only messaging the first 20 recipients.
    _bulk_send(doc, frappe.get_all(
        "Supplier",
        filters={"disabled": 0},
        fields=["name", "mobile_no"],
        limit=0,
    ))


def send_message_employee(doc):
    _bulk_send(doc, frappe.get_all(
        "Employee",
        filters={"status": "Active"},
        fields=["name", "cell_number as mobile_no"],
        limit=0,  # Fix #6
    ))


def send_message_customer(doc):
    _bulk_send(doc, frappe.get_all(
        "Customer",
        filters={"disabled": 0},
        fields=["name", "mobile_no"],
        limit=0,  # Fix #6
    ))


def send_message_lead(doc):
    _bulk_send(doc, frappe.get_all(
        "Lead",
        filters={},
        fields=["name", "mobile_no"],
        limit=0,  # Fix #6
    ))


def send_message_group(doc):
    group_doc = frappe.get_doc("Wati Group", doc.group)
    template_data = get_template_data(doc)
    sent = skipped = failed = 0
    for row in group_doc.wati_group_details:
        if row.enable and sanitize_phone(row.get("mobile_no")):
            ok = _send_one_with_retry(
                doc, row.get("mobile_no"), template_data,
            )
            if ok:
                sent += 1
            else:
                failed += 1
        else:
            skipped += 1

    if failed or skipped:
        frappe.log_error(
            title="Wati: Group Send summary",
            message=(
                f"{doc.name} (Group: {doc.group}): "
                f"{sent} sent, {skipped} skipped (disabled or no mobile), "
                f"{failed} failed after retries."
            ),
        )


# ─── ADDON v2.0.2: Single Contact sender ─────────────────────────────────────

def send_message_single_contact(doc):
    """
    ADDON v2.0.2 — Send to a single ERPNext Contact record.
    Fetches mobile_no from Contact.mobile_no (or phone as fallback).
    """
    if not doc.contact:
        frappe.log_error(
            title="Wati: Single Contact — no contact set",
            message=f"{doc.name}: message_send_to is 'Single Contact' but no contact is selected.",
        )
        return

    contact_doc = frappe.get_doc("Contact", doc.contact)
    mobile = None

    # Try mobile_no first, then phone field
    for phone_row in (contact_doc.phone_nos or []):
        if phone_row.is_primary_mobile_no:
            mobile = sanitize_phone(phone_row.phone)
            break
    if not mobile:
        for phone_row in (contact_doc.phone_nos or []):
            candidate = sanitize_phone(phone_row.phone)
            if candidate:
                mobile = candidate
                break

    if not mobile:
        frappe.log_error(
            title="Wati: Single Contact — no valid mobile",
            message=(
                f"{doc.name}: Contact '{doc.contact}' has no valid mobile number. "
                "Please add a phone number to the Contact."
            ),
        )
        return

    template_data = get_template_data(doc)
    _send_one_with_retry(doc, mobile, template_data)


# ─── ADDON v2.0.2: Custom Number sender ──────────────────────────────────────

def send_message_custom_number(doc):
    """
    ADDON v2.0.2 — Send to a manually entered mobile number.
    Uses the custom_mobile_no field on Send Wati Message.
    """
    mobile = sanitize_phone(doc.custom_mobile_no)
    if not mobile:
        frappe.log_error(
            title="Wati: Custom Number — invalid mobile",
            message=(
                f"{doc.name}: 'Custom Number' selected but custom_mobile_no "
                f"'{doc.custom_mobile_no}' is empty or invalid."
            ),
        )
        return

    template_data = get_template_data(doc)
    _send_one_with_retry(doc, mobile, template_data)


# ─── Bulk send with 429 retry ─────────────────────────────────────────────────

def _get_retry_settings():
    """Read retry/delay values from Wati Setting, with safe defaults."""
    from wati_integration.wati_integration.doctype.wati_setting.wati_setting import get_wati_settings
    s = get_wati_settings()
    bulk_delay  = float(getattr(s, "bulk_send_delay", 0.5)  or 0.5)  if s else 0.5
    max_retries = int(getattr(s, "max_retries", 3)          or 3)     if s else 3
    retry_wait  = int(getattr(s, "retry_wait_seconds", 5)   or 5)     if s else 5
    return bulk_delay, max_retries, retry_wait


def _send_one_with_retry(doc, mobile, template_data):
    """
    Send to one recipient with 429-aware retry logic.
    Reads max_retries and retry_wait_seconds from Wati Setting.
    """
    _, max_retries, retry_wait = _get_retry_settings()

    for attempt in range(1, max_retries + 1):
        try:
            send_whatsapp_message(
                doc.message_template,
                mobile,
                template_data,
                doc.name,
                doc.doctype,
                called_from_background=True,
            )
            return True  # success
        except WatiRateLimitError:
            frappe.log_error(
                title="Wati: 429 Rate Limit — retrying",
                message=(
                    f"{doc.name}: WATI returned 429 for {mobile} "
                    f"(attempt {attempt}/{max_retries}). Waiting {retry_wait}s."
                ),
            )
            time.sleep(retry_wait)
        except Exception:
            frappe.log_error(
                title="Wati: Unexpected send error",
                message=frappe.get_traceback(),
            )
            return False  # non-429 errors not retried

    frappe.log_error(
        title="Wati: Message delivery failed",
        message=f"{doc.name}: Failed to deliver to {mobile} after {max_retries} attempts.",
    )
    return False


def _bulk_send(doc, recipients):
    """
    Send to a list of recipients with per-message delay and 429 retry.

    FIX #2 (v2.0.3) — Batch enqueue for large recipient lists.
    When bulk_batch_size > 0 (default 100), recipients are split into pages
    and each page is dispatched as a separate background job.  This prevents
    time.sleep() retry waits from blocking the long-queue worker for the
    entire recipient list when WATI rate-limits mid-send.

    Set bulk_batch_size = 0 in Wati Setting to disable batching and use the
    original single-job behaviour (unchanged code path below).
    """
    bulk_delay, _, _ = _get_retry_settings()
    batch_size = _get_bulk_batch_size()

    # ── FIX #2: split into batches when batch_size > 0 ───────────────────────
    if batch_size > 0 and len(recipients) > batch_size:
        # Serialise the minimum data needed — mobile_no only (no frappe doc
        # objects, which are not JSON-serialisable).
        mobile_list = [
            r.get("mobile_no") for r in recipients if sanitize_phone(r.get("mobile_no"))
        ]
        for start in range(0, len(mobile_list), batch_size):
            batch = mobile_list[start: start + batch_size]
            frappe.enqueue(
                "wati_integration.wati_integration.doctype.send_wati_message"
                ".send_wati_message._bulk_send_batch",
                doc_name=doc.name,
                mobile_batch=batch,
                queue="long",
            )
        frappe.log_error(
            title="Wati: Bulk send batched",
            message=(
                f"{doc.name}: {len(mobile_list)} recipients split into "
                f"{(len(mobile_list) + batch_size - 1) // batch_size} batches "
                f"of {batch_size}."
            ),
        )
        return
    # ── END FIX #2 ────────────────────────────────────────────────────────────

    # Original single-job path — unchanged.
    template_data = get_template_data(doc)
    sent = skipped = failed = 0

    for row in recipients:
        mobile = sanitize_phone(row.get("mobile_no"))
        if not mobile:
            skipped += 1
            continue

        ok = _send_one_with_retry(doc, mobile, template_data)
        if ok:
            sent += 1
        else:
            failed += 1

        time.sleep(bulk_delay)

    if skipped or failed:
        frappe.log_error(
            title="Wati: Bulk Send summary",
            message=(
                f"{doc.name}: {sent} sent, {skipped} skipped (no valid mobile), "
                f"{failed} failed after retries."
            ),
        )


def _bulk_send_batch(doc_name, mobile_batch):
    """
    FIX #2 (v2.0.3) — Worker function for a single batch of recipients.
    Enqueued by _bulk_send() when batch_size > 0.  Each call processes at most
    bulk_batch_size recipients so a 429 sleep only blocks this one worker slot.
    """
    try:
        doc = frappe.get_doc("Send Wati Message", doc_name)
    except Exception:
        frappe.log_error(
            title="Wati: Batch send — doc not found",
            message=f"Send Wati Message '{doc_name}' could not be loaded.",
        )
        return

    bulk_delay, _, _ = _get_retry_settings()
    template_data = get_template_data(doc)
    sent = failed = 0

    for mobile in mobile_batch:
        ok = _send_one_with_retry(doc, mobile, template_data)
        if ok:
            sent += 1
        else:
            failed += 1
        time.sleep(bulk_delay)

    if failed:
        frappe.log_error(
            title="Wati: Batch Send summary",
            message=(
                f"{doc_name}: batch of {len(mobile_batch)} — "
                f"{sent} sent, {failed} failed."
            ),
        )


def get_template_data(doc):
    data = []
    for field in doc.send_message_variables:
        data.append({
            "name":  field.get("template_variable"),
            "value": field.get("value") or "",
        })
    return json.dumps(data)
