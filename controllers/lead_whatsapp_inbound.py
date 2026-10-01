# -*- coding: utf-8 -*-
"""Receives a customer's incoming WhatsApp message, forwarded by this
officer's own bot_service_update/whatsapp.js instance (see its
messages.upsert listener). This controller's own job is just to resolve
WHICH lead/sent-message the customer is talking to and hand off to
LeadChatbotEngine.

CHANGED FROM THE ORIGINAL (reply-only) SCOPE: this originally only accepted
an explicit WhatsApp quote-reply (matched via wa_message_id/quoted_id) -
never a general-purpose inbound-message webhook, by deliberate design. Per
an explicit later decision, a plain (non-reply) message is now accepted
too, matched instead to "whatever this bot last sent to this same WhatsApp
chat" (see get_latest_sent_to_jid()). This is a real, knowingly-accepted
trade-off: every message the customer sends in this chat can now trigger
the chatbot, not just explicit replies - there is no narrower signal once
swipe-reply is not required.

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
        from_jid = payload.get("from")
        # CHANGED: quoted_id is no longer required - a customer typing a
        # plain message (not swipe-replying) is now also accepted, per an
        # explicit later decision to drop the "must reply" requirement. At
        # least one of quoted_id/from must still be present to have any
        # hope of matching a lead at all.
        if not quoted_id and not from_jid:
            return self._json({"ok": False, "error": "quoted_id or from is required"}, status=400)

        Bot = request.env["otm.whatsapp.lead.bot"].sudo()
        bot = Bot.search([("api_token", "=", token)], limit=1)
        if not bot:
            # Never confirm/deny which part of the token was wrong - same
            # care as any other bearer-token auth endpoint.
            return self._json({"ok": False, "error": "unauthorized"}, status=401)

        Message = request.env["otm.whatsapp.lead.message"].sudo()
        # Prefer an explicit quote-reply match (precise: this exact message
        # was replied to). Fall back to "whatever this chat's most recent
        # outgoing message was" when there's no quote, or the quoted
        # message isn't tracked - the only signal available for a plain,
        # non-reply message.
        source_message = Message.get_by_wa_message_id(bot.id, quoted_id) if quoted_id else Message.browse()
        if not source_message:
            source_message = Message.get_latest_sent_to_jid(bot.id, from_jid)
        if not source_message:
            _logger.info(
                "Lead inbound webhook: no tracked outgoing message for bot %s matching "
                "quoted_id %s or chat %s - ignoring.", bot.id, quoted_id, from_jid,
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
                "wa_remote_jid": from_jid,
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
