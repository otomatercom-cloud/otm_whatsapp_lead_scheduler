# -*- coding: utf-8 -*-
"""Lightweight reply-triggered chatbot for the lead scheduler side.

Deliberately NOT a reuse of otm_whatsapp_chatbot's ChatbotEngine - that
engine is tightly coupled to otm_whatsapp_coexistence's own
otm.whatsapp.phone/conversation/contact/message models (every otm.whatsapp.
chatbot record REQUIRES a phone_id). This engine only reuses the two pieces
of that module that are genuinely transport-agnostic:
  - the FAQ keyword-matching shape (copied as otm.whatsapp.lead.chatbot.faq,
    see that model's own docstring for why it's a copy, not a shared table)
  - otm.whatsapp.ai.provider + its AiProviderClient (already provider-
    agnostic, no Coexistence-specific fields at all - genuinely shared)

Only called for a message that is a direct WhatsApp quote-reply to a
stage-triggered template this module itself sent (see
controllers/lead_whatsapp_inbound.py) - never for an arbitrary incoming
message, per the explicit scope decision.
"""
import logging

_logger = logging.getLogger(__name__)


class LeadChatbotEngine:
    def __init__(self, env):
        # Always sudo: this is only ever instantiated from the public,
        # token-authenticated inbound webhook controller (see
        # controllers/lead_whatsapp_inbound.py), never from a real logged-in
        # user's session - env there has no meaningful user-level access of
        # its own, so every lookup this engine does must run with elevated
        # rights, same as the controller's own Bot/Message sudo() calls.
        # ODOO 19 RULE: Environment.sudo() was removed - calling .sudo()
        # directly on an env object (not a recordset) now raises
        # AttributeError: 'Environment' object has no attribute 'sudo'.
        # The replacement is calling the environment itself with su=True:
        # env(su=True). Recordset-level .sudo() (e.g. some_record.sudo())
        # is unaffected and still works exactly as before - only the bare
        # env.sudo() form broke.
        self.env = env(su=True)

    def handle_reply(self, source_message, bot, customer_text):
        """`source_message` is the otm.whatsapp.lead.message that was replied
        to (already resolved by the controller via wa_message_id). Returns
        the reply text sent (or None if nothing was sent - e.g. chatbot
        disabled, no FAQ/AI match and no fallback configured)."""
        ICP = self.env["ir.config_parameter"].sudo()
        # ODOO RULE: a Boolean field's config_parameter is stored as Python's
        # str(bool) - "True"/"False" (capitalized), not lowercase "true"/
        # "false". Comparing against a lowercase literal here always failed,
        # so the chatbot silently treated itself as disabled even when the
        # settings checkbox was ticked and saved. Normalize case before
        # comparing.
        enabled = (ICP.get_param("otm_whatsapp_lead_scheduler.chatbot_enabled", default="False") or "").strip().lower()
        if enabled not in ("true", "1"):
            return None

        text = (customer_text or "").strip()
        if not text:
            return None

        reply_text = self._match_faq(text, bot.company_id.id)
        if not reply_text:
            reply_text = self._try_ai(source_message, text)
        if not reply_text:
            reply_text = ICP.get_param("otm_whatsapp_lead_scheduler.chatbot_fallback_message", default="")
            reply_text = (reply_text or "").strip() or None

        if not reply_text:
            _logger.info(
                "Lead chatbot: no FAQ/AI match and no fallback configured for lead %s - "
                "nothing sent, officer handles it personally.", source_message.id,
            )
            return None

        self._send_reply(source_message, bot, reply_text)
        return reply_text

    # ------------------------------------------------------------------
    def _match_faq(self, text, company_id):
        # sudo() bypasses the model's own multi-company ir.rule (there is no
        # logged-in user/session here to drive it), so company scoping is
        # done explicitly here instead - otherwise a sudo search would match
        # another company's FAQs too.
        Faq = self.env["otm.whatsapp.lead.chatbot.faq"]
        faqs = Faq.search([("active", "=", True), ("company_id", "=", company_id)])
        for faq in faqs:
            if faq.matches(text):
                return faq.answer
        return None

    def _try_ai(self, source_message, text):
        ICP = self.env["ir.config_parameter"].sudo()
        provider_id = ICP.get_param("otm_whatsapp_lead_scheduler.chatbot_ai_provider_id")
        if not provider_id:
            return None
        provider = self.env["otm.whatsapp.ai.provider"].sudo().browse(int(provider_id))
        if not provider.exists() or not provider.active:
            return None

        system_prompt = (
            "You are a helpful assistant for an educational institution's admissions "
            "team, replying to a prospective student's WhatsApp message. Be polite, "
            "keep responses concise, and if you can't answer confidently, say the "
            "officer will follow up personally rather than guessing."
        )
        history = self._build_history(source_message)
        client = provider._get_client()
        reply, error = client.generate_reply(system_prompt, history, text)
        if error:
            _logger.info("Lead chatbot AI call did not produce a reply: %s", error)
        return reply

    def _build_history(self, source_message, max_messages=6):
        """Last N messages (either direction) for this SAME lead only -
        never another lead's conversation, matching otm_whatsapp_chatbot's
        own cost/scope control."""
        Message = self.env["otm.whatsapp.lead.message"]
        prior = Message.search(
            [("lead_id", "=", source_message.lead_id.id), ("id", "!=", source_message.id)],
            order="id desc", limit=max_messages,
        )
        history = []
        for m in reversed(prior):
            role = "user" if m.direction == "in" else "assistant"
            if m.message:
                history.append({"role": role, "content": m.message})
        return history

    def _send_reply(self, source_message, bot, reply_text):
        from odoo import fields as _fields

        client = bot._get_client()
        result = client.send_direct_message(source_message.lead_id.phone_number, reply_text)
        vals = {
            "lead_id": source_message.lead_id.id,
            "bot_id": bot.id,
            "direction": "out",
            "message": reply_text,
            # required once state != 'draft' (see the model's own constraint)
            "scheduled_datetime": _fields.Datetime.now(),
        }
        if result.get("success"):
            vals.update({
                "state": "sent",
                "sent_date": _fields.Datetime.now(),
                "wa_message_id": result.get("message_id"),
                "wa_remote_jid": result.get("jid"),
            })
        else:
            vals.update({
                "state": "failed",
                "last_error": result.get("error") or "Unknown error from the WhatsApp bot service.",
                "last_attempt_date": _fields.Datetime.now(),
            })
        self.env["otm.whatsapp.lead.message"].sudo().create(vals)
