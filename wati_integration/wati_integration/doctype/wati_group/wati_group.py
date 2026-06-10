# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class WatiGroup(Document):

    def validate(self):
        """Remove duplicate group members on save."""
        seen = set()
        deduped = []
        for row in self.wati_group_details:
            key = row.get("mobile_no") or row.get("group_member")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            deduped.append(row)
        if len(deduped) != len(self.wati_group_details):
            self.wati_group_details = deduped
            frappe.msgprint(
                _("Duplicate members were removed from the group."),
                alert=True, indicator="orange"
            )

        # ADDON v2.0.2 — Populate member_name for display in the grid
        self._populate_member_names()

    def _populate_member_names(self):
        """
        ADDON v2.0.2 — Fetch a display name for each group member row.
        Maps common doctypes to their 'name' display field.
        Falls back to group_member (the document ID) if the field is not found.
        Original deduplication logic above is not changed.
        """
        name_field_map = {
            "Customer":  "customer_name",
            "Supplier":  "supplier_name",
            "Employee":  "employee_name",
            "Lead":      "lead_name",
            "Contact":   "full_name",
        }
        for row in self.wati_group_details:
            doc_type   = row.get("document_type")
            doc_member = row.get("group_member")
            if not doc_type or not doc_member:
                continue
            name_field = name_field_map.get(doc_type)
            if name_field:
                try:
                    fetched = frappe.db.get_value(doc_type, doc_member, name_field)
                    row.member_name = fetched or doc_member
                except Exception:
                    row.member_name = doc_member
            else:
                row.member_name = doc_member


@frappe.whitelist()
def get_mobile_no(group_member, document_type):
    """Return the mobile number for a given group member and document type."""
    mobile_no_field_map = {
        "Employee": "cell_number",
        "Customer": "mobile_no",
        "Supplier": "mobile_no",
        "Lead":     "mobile_no",
    }
    field = mobile_no_field_map.get(document_type)

    if document_type == "Contact":
        # Contact stores phone numbers in the phone_nos child table.
        # Return the primary mobile number first; fall back to the first
        # available phone entry if no primary mobile is flagged.
        if not frappe.db.exists("Contact", group_member):
            return None
        contact_doc = frappe.get_doc("Contact", group_member)
        # Pass 1 — look for the explicitly flagged primary mobile
        for phone_row in (contact_doc.phone_nos or []):
            if phone_row.is_primary_mobile_no and phone_row.phone:
                return phone_row.phone
        # Pass 2 — return the first non-empty phone entry
        for phone_row in (contact_doc.phone_nos or []):
            if phone_row.phone:
                return phone_row.phone
        return None

    if not field:
        return None
    if frappe.db.exists(document_type, group_member):
        return frappe.db.get_value(document_type, group_member, field)
    return None


@frappe.whitelist()
def import_from_doctype(group_name, document_type):
    """
    ADDON: Import all active records of document_type into the Wati Group.
    Skips records that already exist in the group (no duplicates).
    Returns the number of members added.

    BUG FIX #10 — Permission: the original had no access check, allowing any
    logged-in user to read all Customers/Suppliers/Employees/Leads and write
    them into a Wati Group without needing any permissions on those doctypes.
    Now checks write permission on the Wati Group before proceeding.
    """
    # ── Permission guard (Fix #10) ────────────────────────────────────────
    frappe.has_permission("Wati Group", ptype="write", throw=True)

    field_map = {
        "Employee": ("name", "cell_number", "status", "Active"),
        "Customer": ("name", "mobile_no", "disabled", 0),
        "Supplier": ("name", "mobile_no", "disabled", 0),
        "Lead":     ("name", "mobile_no", None, None),
    }

    if document_type not in field_map:
        frappe.throw(_("Unsupported document type: {0}").format(document_type))

    name_field, mobile_field, status_field, status_value = field_map[document_type]
    filters = {}
    if status_field:
        filters[status_field] = status_value

    records = frappe.get_all(
        document_type,
        filters=filters,
        fields=[name_field, mobile_field],
        limit=0,  # Fix #6 applied here too — fetch all records, not default 20
    )

    group_doc = frappe.get_doc("Wati Group", group_name)
    existing_mobiles = {row.get("mobile_no") for row in group_doc.wati_group_details}

    from wati_integration.wati_integration.doctype.wati_message_rule.wati_message_rule import sanitize_phone

    added = 0
    for rec in records:
        raw_mobile = rec.get(mobile_field)
        # sanitize_phone auto-prepends 91 for valid 10-digit Indian numbers
        mobile = sanitize_phone(raw_mobile)
        if not mobile or mobile in existing_mobiles:
            continue
        group_doc.append("wati_group_details", {
            "document_type": document_type,
            "group_member": rec.get(name_field),
            "mobile_no": mobile,
            "enable": 1,
        })
        existing_mobiles.add(mobile)
        added += 1

    if added:
        group_doc.save()

    return added
