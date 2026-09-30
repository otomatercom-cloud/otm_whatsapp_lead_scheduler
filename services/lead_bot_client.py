# -*- coding: utf-8 -*-
"""Thin HTTP client for one Admission Officer's own instance of the
companion `otm-whatsapp-group-bot-service` (Node.js, Baileys-based,
unofficial). Deliberately mirrors otm_whatsapp_group_scheduler's
GroupBotClient shape exactly - a small class taking the config record,
private _get/_post helpers, one public method per operation, never raising
on an HTTP/business error (callers get a dict back and decide what to do).

The only difference from GroupBotClient: send_direct_message() calls
POST /send-direct (a phone number) instead of POST /send (a group JID) -
see bot_service_update/ shipped alongside this module for the small,
additive change that endpoint needs on the Node side. get_status()/get_qr()
are unchanged - same wire format, same service codebase, just one more
instance of it running per officer.
"""
import logging

import requests

_logger = logging.getLogger(__name__)

TIMEOUT = 30


class LeadBotClient:
    def __init__(self, bot):
        """`bot` is an otm.whatsapp.lead.bot recordset of 1."""
        self.bot = bot
        self.base_url = (bot.base_url or "").rstrip("/")
        self.token = bot.sudo().api_token

    def _headers(self):
        return {"Authorization": "Bearer %s" % self.token, "Content-Type": "application/json"}

    def _url(self, path):
        return "%s%s" % (self.base_url, path)

    @staticmethod
    def _parse(resp):
        try:
            data = resp.json()
        except ValueError:
            return {"error": "Non-JSON response (HTTP %s)" % resp.status_code}
        if resp.status_code >= 400 and "error" not in data:
            data["error"] = "HTTP %s" % resp.status_code
        return data

    def get_status(self):
        """Returns {"state":..., "connected": bool, "phone_number":..., "last_error":...}
        or {"error": "..."} if the service itself is unreachable."""
        if not self.base_url or not self.token:
            return {"error": "WhatsApp connection is not configured (base URL/token missing)."}
        try:
            resp = requests.get(self._url("/status"), headers=self._headers(), timeout=TIMEOUT)
        except requests.RequestException as exc:
            return {"error": "Could not reach this officer's WhatsApp bot service: %s" % exc}
        return self._parse(resp)

    def get_qr(self):
        """Returns {"qr": "data:image/png;base64,..." or None} or {"error": "..."}."""
        if not self.base_url or not self.token:
            return {"error": "WhatsApp connection is not configured (base URL/token missing)."}
        try:
            resp = requests.get(self._url("/qr"), headers=self._headers(), timeout=TIMEOUT)
        except requests.RequestException as exc:
            return {"error": "Could not reach this officer's WhatsApp bot service: %s" % exc}
        return self._parse(resp)

    def send_direct_message(self, phone_number, message, media=None):
        """`phone_number` is a plain number as stored on the lead (e.g.
        '9198xxxxxxxx' or '+9198xxxxxxxx') - the service is responsible for
        normalising it into a WhatsApp JID. `media`: optional dict
        {"base64":..., "mime_type":..., "file_name":..., "media_type":
        "image"|"video"|"document"} - same shape GroupBotClient sends, since
        the Node service's /send and /send-direct share one _buildContent()
        helper. Returns {"success": True, "message_id": ...} or
        {"success": False, "error": ...} - NEVER raises; caller
        (otm.whatsapp.lead.message._process_send()) reads the dict, matching
        every other client in this codebase's contract."""
        if not self.base_url or not self.token:
            return {"success": False, "error": "WhatsApp connection is not configured."}
        if not phone_number:
            return {"success": False, "error": "No phone number to send to."}
        payload = {"to": phone_number, "message": message or ""}
        if media:
            payload["media"] = {
                "base64": media.get("base64"),
                "mimeType": media.get("mime_type"),
                "fileName": media.get("file_name"),
                "mediaType": media.get("media_type"),
            }
        try:
            resp = requests.post(
                self._url("/send-direct"), headers=self._headers(), json=payload, timeout=TIMEOUT
            )
        except requests.RequestException as exc:
            _logger.warning("Lead bot service unreachable sending to %s: %s", phone_number, exc)
            return {"success": False, "error": "Could not reach the WhatsApp bot service: %s" % exc}
        result = self._parse(resp)
        if "success" not in result:
            result["success"] = not bool(result.get("error"))
        return result
