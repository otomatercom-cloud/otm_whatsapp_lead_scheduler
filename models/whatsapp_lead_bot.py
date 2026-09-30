# -*- coding: utf-8 -*-
import base64
import logging
import re

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

    # --- Provisioning (creating the officer's own bot instance on the
    # server) -------------------------------------------------------------
    # Odoo NEVER runs shell commands or touches PM2 itself - that would
    # mean the web/cron process has real shell execution rights on the
    # server, which is a serious privilege-escalation risk. Instead this
    # just records a REQUEST. A separate script (bot_service_update/
    # provisioner.py), run by system cron as whichever Linux user already
    # owns PM2/npm on this box, polls for 'requested' records over
    # Odoo's normal external API, does the actual work
    # (setup_officer_bot.sh), and writes the resulting base_url/api_token
    # back here the same way any external client would.
    provision_state = fields.Selection(
        [
            ("none", "Not Requested"),
            ("requested", "Requested"),
            ("provisioning", "Provisioning..."),
            ("done", "Provisioned"),
            ("error", "Failed"),
            ("removal_requested", "Removal Requested"),
            ("removing", "Removing..."),
            ("removed", "Removed"),
            ("removal_error", "Removal Failed"),
        ],
        default="none", tracking=True, copy=False,
        help="Status of automatically creating/removing this officer's own "
        "bot-service instance on the server. Picked up and actioned by a "
        "script running outside Odoo (see bot_service_update/provisioner.py) "
        "- not instant.",
    )
    provision_slug = fields.Char(
        string="Instance Slug", copy=False,
        help="Used to name the server-side folder/PM2 process for this officer's "
        "instance, e.g. 'priya' -> otm_whatsapp_lead_bot_priya, PM2 process "
        "whatsapp-lead-priya. Auto-suggested from the officer's login; "
        "letters, numbers and dashes only.",
    )
    provision_error = fields.Text(readonly=True, copy=False)
    provision_requested_date = fields.Datetime(readonly=True, copy=False)
    provision_done_date = fields.Datetime(readonly=True, copy=False)

    @api.onchange("user_id")
    def _onchange_user_id_suggest_slug(self):
        for rec in self:
            if rec.user_id and not rec.provision_slug:
                rec.provision_slug = rec._slugify(rec.user_id.login or rec.user_id.name)

    @staticmethod
    def _slugify(text):
        text = (text or "").split("@")[0].lower()
        text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        return text[:24] or "officer"

    def action_request_provisioning(self):
        """Button: ask the external provisioner to create this officer's
        bot-service instance automatically. Does NOT touch the server
        itself - just flags the record; provisioner.py (run by system
        cron, outside Odoo) does the actual work, usually within a few
        minutes depending on how often that cron runs."""
        for rec in self:
            if rec.base_url or rec.api_token:
                raise UserError(
                    _("This connection already has a Service URL/API Token set. "
                      "Provisioning is only for a brand-new, unconfigured connection.")
                )
            if not rec.provision_slug:
                rec.provision_slug = rec._slugify(rec.user_id.login or rec.user_id.name)
            rec.write(
                {
                    "provision_state": "requested",
                    "provision_error": False,
                    "provision_requested_date": fields.Datetime.now(),
                }
            )
        return True

    def action_request_removal(self):
        """Button: ask the external provisioner to tear down this officer's
        bot-service instance (PM2 process + folder) when they leave / are
        offboarded. Deactivates the connection IMMEDIATELY so nothing can
        send through it while the teardown is still pending - the actual
        server-side cleanup (stop PM2, delete the folder) happens later,
        off-server, done by provisioner.py. Service URL/API Token are left
        as-is (both are required fields and pointless to clear anyway -
        once 'active' is False, get_for_user()'s search already excludes
        this record from being used to send anything)."""
        for rec in self:
            if not rec.provision_slug:
                raise UserError(
                    _("No instance slug recorded on this connection - nothing to remove "
                      "automatically. Remove it manually on the server instead.")
                )
            rec.write(
                {
                    "provision_state": "removal_requested",
                    "provision_error": False,
                    "provision_requested_date": fields.Datetime.now(),
                    "active": False,
                    "connection_state": "not_connected",
                }
            )
        return True

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
