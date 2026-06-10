# Copyright (c) 2022, Bhavesh Maheshwari and contributors
# For license information, please see license.txt

import re
import frappe
from frappe.model.document import Document
from frappe import _


class MessageTemplate(Document):

    def validate(self):
        if not self.template_message:
            frappe.throw(_("Template Message is required."))

        # Validate placeholder syntax
        try:
            self.template_message.format_map(frappe._dict())
        except (KeyError, IndexError):
            pass  # Named/positional placeholders — fine at design time
        except ValueError as exc:
            frappe.throw(_(
                "Invalid Message Format — check your placeholder syntax: {0}"
            ).format(str(exc)))

        # Extract all {variable_name} tokens → comma-separated in template_variables
        res = re.findall(r'\{([^{}]+?)\}', self.template_message)
        self.template_variables = ", ".join(v.strip() for v in res if v.strip())

    @frappe.whitelist()
    def get_preview(self, sample_values=None):
        """
        ADDON: Return a preview of the message with sample values substituted.
        sample_values: dict of {variable_name: value}
        """
        if not sample_values:
            sample_values = {}
        if isinstance(sample_values, str):
            import json
            sample_values = json.loads(sample_values)

        variables = [v.strip() for v in (self.template_variables or "").split(",") if v.strip()]
        # Build a dict with provided values or "[variable_name]" placeholders
        fill = {v: sample_values.get(v, f"[{v}]") for v in variables}

        try:
            preview = self.template_message.format_map(fill)
        except Exception:
            preview = self.template_message  # fallback to raw

        return preview
