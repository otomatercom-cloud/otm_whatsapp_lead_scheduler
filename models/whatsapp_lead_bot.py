# -*- coding: utf-8 -*-
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OtmWhatsappLeadBot(models.Model):
    """One Admission Officer's own WhatsApp number/session.

    Deliberately ONE bot connection per user, never shared: this is what
    makes "each officer has their own WhatsApp number" true. Each record
    points at its OWN running instance of the companion
    otm-whatsapp-group-bot-service (own port, own auth_info folder, own QR
    pairing) - never a second officer's instance. Shape mirrors
    otm.whatsapp.group.bot (from otm_whatsapp_group_scheduler) on purpose -
    same admin experience, same client/service contract - just one config
    record per person instead of per group-number.
    """

    _name = "otm.whatsapp.lead.bot"
    _description = "WhatsApp Lead Bot Connection (per Admission Officer)"
    _inherit = ["mail.thread"]
    _rec_name = "name"

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    active = fields.Boolean(default=True)

    user_id = fields.Many2one(
        "res.users", string="Admission Officer", required=True, tracking=True,
        index=True, ondelete="restrict",
        help="The officer this WhatsApp number belongs to. A lead's 'Send WhatsApp' "
        "button and scheduled messages always use THIS officer's own bot - never "
        "another officer's number.",
    )

    base_url = fields.Char(
        string="Service URL", required=True, tracking=True,
        help="Base URL of THIS officer's own otm-whatsapp-group-bot-service instance, "
        "e.g. http://127.0.0.1:8731 - each officer's number is a separate instance "
        "on its own port, never a shared one. Keep this on a private/internal "
        "network, never exposed publicly.",
    )
    api_token = fields.Char(
        string="API Token", groups="otm_whatsapp_coexistence.group_whatsapp_administrator",
        help="Must match the API_TOKEN configured in that instance's .env file.",
    )

    connection_state = fields.Selection(
        [
            ("not_connected", "Not Connected"),
            ("qr_pending", "Waiting for QR Scan"),
            ("connected", "Connected"),
            ("error", "Error"),
        ],
        default="not_connected",
        tracking=True,
    )
    phone_number = fields.Char(string="Paired Number", readonly=True)
    last_check = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)
    qr_image = fields.Binary(
        string="Pairing QR Code", readonly=True, attachment=False,
        help="The officer scans this from their own WhatsApp app: Settings > Linked "
        "Devices > Link a Device. Refresh this record (Check Connection) if it "
        "expires before it's scanned.",
    )

    _user_uniq = models.Constraint(
        "unique(user_id)",
        "This Admission Officer already has a WhatsApp Lead Bot connection configured.",
    )

    def _get_client(self):
        self.ensure_one()
        from ..services.lead_bot_client import LeadBotClient

        return LeadBotClient(self)

    def action_check_connection(self):
        for rec in self:
            client = rec._get_client()
            status = client.get_status()
            vals = {"last_check": fields.Datetime.now()}
            if status.get("error"):
                vals.update({"connection_state": "error", "last_error": status["error"]})
            else:
                state = status.get("state") or "not_connected"
                vals.update(
                    {
                        "connection_state": state if state in dict(rec._fields["connection_state"].selection) else "error",
                        "phone_number": status.get("phone_number") or False,
                        "last_error": status.get("last_error") or False,
                    }
                )
            rec.write(vals)
            if vals.get("connection_state") == "qr_pending":
                rec._refresh_qr()
        return True

    def _refresh_qr(self):
        self.ensure_one()
        client = self._get_client()
        result = client.get_qr()
        qr_data_url = result.get("qr") if not result.get("error") else None
        if qr_data_url and qr_data_url.startswith("data:image"):
            try:
                b64_part = qr_data_url.split(",", 1)[1]
                base64.b64decode(b64_part)
                self.qr_image = b64_part
            except (ValueError, IndexError):
                _logger.warning("Lead bot %s: malformed QR data URL from service", self.id)
        else:
            self.qr_image = False

    def action_refresh_qr(self):
        for rec in self:
            rec._refresh_qr()
        return True

    @api.model
    def get_for_user(self, user):
        """Returns the (single, active, connected-or-not) bot for `user`, or
        an empty recordset. The one lookup point every caller (stage button,
        wizard, cron) goes through - never a direct search elsewhere."""
        return self.search([("user_id", "=", user.id)], limit=1)

    def _require_connected(self):
        self.ensure_one()
        if self.connection_state != "connected":
            raise UserError(
                _("%(officer)s's WhatsApp number ('%(name)s') is not connected right now "
                  "(status: %(state)s). Open the connection record and Check Connection / "
                  "scan the QR code first.")
                % {
                    "officer": self.user_id.name,
                    "name": self.name,
                    "state": dict(self._fields["connection_state"].selection).get(self.connection_state),
                }
            )
