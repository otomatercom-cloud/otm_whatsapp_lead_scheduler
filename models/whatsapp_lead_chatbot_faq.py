# -*- coding: utf-8 -*-
from odoo import fields, models


class OtmWhatsappLeadChatbotFaq(models.Model):
    """A deliberately independent copy of otm_whatsapp_chatbot's FAQ shape
    (same fields, same matching logic) - NOT a shared/reused record set.

    otm_whatsapp_chatbot's own otm.whatsapp.chatbot.faq is a child of
    otm.whatsapp.chatbot, which REQUIRES a phone_id (Many2one to
    otm.whatsapp.coexistence's own otm.whatsapp.phone, unique per chatbot).
    This module's officer numbers are otm.whatsapp.lead.bot records, not
    otm.whatsapp.phone ones, and there is no single fixed "number" a lead
    chatbot answers for - any officer's number can trigger it. Attaching to
    the real otm.whatsapp.chatbot model would mean faking a Coexistence
    phone number per officer, which risks confusing/breaking the real
    Coexistence chatbot setup. A separate, company-scoped list avoids that
    entirely, at the cost of duplicate data entry if the same FAQ answers
    are wanted in both places - acceptable per the explicit decision not to
    couple these two modules.
    """

    _name = "otm.whatsapp.lead.chatbot.faq"
    _description = "WhatsApp Lead Chatbot FAQ"
    _order = "priority desc, id"

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    active = fields.Boolean(default=True)
    question = fields.Char(required=True)
    keywords = fields.Char(
        required=True,
        help="Comma-separated. The customer's reply is matched against each keyword "
        "per the Match Type below - any single keyword match is enough.",
    )
    match_type = fields.Selection(
        [("contains", "Contains"), ("exact", "Exact Match"), ("starts_with", "Starts With")],
        default="contains", required=True,
    )
    answer = fields.Text(required=True)
    priority = fields.Integer(
        default=10, help="Higher priority FAQs are checked first when several match.",
    )

    def get_keyword_list(self):
        self.ensure_one()
        return [k.strip().lower() for k in (self.keywords or "").split(",") if k.strip()]

    def matches(self, text):
        self.ensure_one()
        text = (text or "").strip().lower()
        if not text:
            return False
        for kw in self.get_keyword_list():
            if self.match_type == "exact" and text == kw:
                return True
            if self.match_type == "contains" and kw in text:
                return True
            if self.match_type == "starts_with" and text.startswith(kw):
                return True
        return False
