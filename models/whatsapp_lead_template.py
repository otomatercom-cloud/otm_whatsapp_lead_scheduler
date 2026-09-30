# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class _SafeDict(dict):
    """A dict that leaves an unknown {placeholder} exactly as typed instead
    of raising KeyError - so a template referencing {course} still renders
    (with the literal text "{course}" left visible) even for a lead where
    that particular field is empty/renamed, rather than blocking the send
    entirely with a cryptic KeyError."""

    def __missing__(self, key):
        return "{%s}" % key


class OtmWhatsappLeadTemplate(models.Model):
    """A reusable WhatsApp message. Placeholders are plain str.format()
    braces, e.g. {lead_name} - kept intentionally simple (no QWeb/Jinja)
    since this is a single line of chat text, not a document."""

    _name = "otm.whatsapp.lead.template"
    _description = "WhatsApp Lead Message Template"
    _rec_name = "name"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    body = fields.Text(
        required=True,
        help="Available placeholders: {lead_name}, {phone_number}, {course}, {place}, "
        "{college_name}, {officer_name}. An unrecognised placeholder is left as-is "
        "rather than blocking the send.",
    )
    notes = fields.Text(help="Internal notes for whoever maintains this template - not sent.")

    def render(self, lead, officer=False):
        """Returns the final text for `lead` (a leads.logic record). Never
        raises on a missing/renamed field - a broken placeholder is a typo
        to fix later, not a reason to fail a send in front of a customer."""
        self.ensure_one()
        officer = officer or lead.lead_owner.user_id
        values = _SafeDict(
            lead_name=lead.name or "",
            phone_number=lead.phone_number or "",
            course=lead.course_interested or lead.preferred_course or "",
            place=lead.place or "",
            college_name=lead.college_name or "",
            officer_name=officer.name if officer else "",
        )
        try:
            return (self.body or "").format_map(values)
        except (ValueError, IndexError) as exc:
            # A malformed template (stray '{' or '}') - don't crash the
            # send, just log it and fall back to the raw, unrendered body.
            _logger.warning("Template %s: could not render (%s) - sending raw body", self.id, exc)
            return self.body or ""
