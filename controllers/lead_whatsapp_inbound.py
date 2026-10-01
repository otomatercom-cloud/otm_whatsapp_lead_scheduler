# -*- coding: utf-8 -*-
"""Receives a customer's WhatsApp quote-reply, forwarded by this officer's
own bot_service_update/whatsapp.js instance (see its messages.upsert
listener). Only ever called for a message Baileys confirmed is a direct
quote-reply to something that officer's number sent - this controller's own
job is just to resolve WHICH sent message (via wa_message_id) and hand off
to LeadChatbotEngine; it is never a general-purpose inbound-message webhook.

Auth: the same per-officer API token already used for every outbound call
(LeadBotClient's Bearer token) - reused here as the Bearer token FROM the
bot service TO Odoo, so no second secret needs provisioning. Each officer's
bot instance only knows its own token, so this inherently scopes a request
to that one officer's otm.whatsapp.lead.bot record - never another
officer's.
"""
import json
import logging

from odoo import fields, http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class LeadWhatsappInboundController(http.Controller):

    @http.route(
        "/otm_whatsapp_lead/inbound", type="http", auth="public",
        methods=["POST"], csrf=False, save_session=False,
    )
    def inbound(self, **kwargs):
        auth_header = request.httprequest.headers.get("Authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else None
        if not token:
            return self._json({"ok": False, "error": "missing bearer token"}, status=401)

        try:
            payload = json.loads(request.httprequest.get_data(as_text=True) or "{}")
        except ValueError:
            return self._json({"ok": False, "error": "invalid JSON body"}, status=400)

        text = (payload.get("text") or "").strip()
        quoted_id = payload.get("quoted_id")
        if not quoted_id:
            return self._json({"ok": False, "error": "quoted_id is required"}, status=400)

        Bot = request.env["otm.whatsapp.lead.bot"].sudo()
        bot = Bot.search([("api_token", "=", token)], limit=1)
        if not bot:
            # Never confirm/deny which part of the token was wrong - same
            # care as any other bearer-token auth endpoint.
            return self._json({"ok": False, "error": "unauthorized"}, status=401)

        Message = request.env["otm.whatsapp.lead.message"].sudo()
        source_message = Message.get_by_wa_message_id(bot.id, quoted_id)
        if not source_message:
            _logger.info(
                "Lead inbound webhook: no tracked outgoing message for bot %s / "
                "wa_message_id %s - ignoring (likely a reply to an older/untracked "
                "message, or a message this module didn't send).", bot.id, quoted_id,
            )
            return self._json({"ok": True, "matched": False})

        # Log the customer's reply itself regardless of whether the chatbot
        # has anything configured to say back - the officer should still see
        # it in this lead's WhatsApp message history.
        now = fields.Datetime.now()
        Message.create(
            {
                "lead_id": source_message.lead_id.id,
                "bot_id": bot.id,
                "direction": "in",
                "message": text or "(empty message)",
                "wa_quoted_id": quoted_id,
                "state": "sent",
                "sent_date": now,
                # required once state != 'draft' (see the model's own constraint) -
                # there's no real "scheduled time" for an inbound message, so this
                # is simply "when we received/logged it".
                "scheduled_datetime": now,
            }
        )

        try:
            from ..services.lead_chatbot_engine import LeadChatbotEngine

            LeadChatbotEngine(request.env).handle_reply(source_message, bot, text)
        except Exception:  # noqa: BLE001 - a chatbot bug must never break this webhook
            _logger.exception(
                "Lead chatbot engine failed handling reply to message %s - the "
                "customer's reply was still logged normally.", source_message.id,
            )

        return self._json({"ok": True, "matched": True})

    @staticmethod
    def _json(data, status=200):
        return Response(json.dumps(data), status=status, content_type="application/json")
