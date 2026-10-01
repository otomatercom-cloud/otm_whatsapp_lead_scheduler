# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import whatsapp_lead_media_utils as media_utils

_logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRY = 3


class OtmWhatsappLeadMessage(models.Model):
    """A single scheduled (or already-sent, or immediately-sent) WhatsApp
    message to one lead/customer. Same state machine and same
    concurrency-safe cron pattern as otm.whatsapp.group.message
    (otm_whatsapp_group_scheduler) - deliberately, so both are maintained the
    same way - just addressed to one phone number instead of a group JID,
    and always sent through the lead's OWN Admission Officer's bot
    connection.

    Timezone note (same as the group scheduler): `scheduled_datetime` is a
    plain fields.Datetime - the ORM already stores it in UTC and shows/edits
    it in the logged-in user's own timezone. The cron compares against
    fields.Datetime.now(), which returns naive UTC to match what's stored -
    no manual offset code anywhere in this file.
    """

    _name = "otm.whatsapp.lead.message"
    _description = "WhatsApp Lead Message"
    _inherit = ["mail.thread"]
    _order = "scheduled_datetime desc, id desc"
    _rec_name = "reference"

    reference = fields.Char(
        default=lambda self: self.env["ir.sequence"].next_by_code(
            "otm.whatsapp.lead.message"
        )
        or _("New"),
        copy=False,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )
    active = fields.Boolean(default=True)

    lead_id = fields.Many2one(
        "leads.logic", string="Lead", required=True, index=True,
        ondelete="cascade", tracking=True,
    )
    lead_owner_id = fields.Many2one(
        related="lead_id.lead_owner", string="Lead Owner", store=True, readonly=True,
    )
    phone_number = fields.Char(related="lead_id.phone_number", readonly=True, store=False)

    bot_id = fields.Many2one(
        "otm.whatsapp.lead.bot", string="Send Via",
        help="Defaults to the lead's own owner's (Admission Officer's) WhatsApp "
        "connection. Only ever change this if you deliberately want a different "
        "officer's number to send it.",
    )

    template_id = fields.Many2one(
        "otm.whatsapp.lead.template", string="Template",
        help="Optional - pick one to prefill Message below with this lead's own "
        "details already filled in. Message is what actually gets sent, so it can "
        "still be edited afterwards.",
    )
    trigger_id = fields.Many2one(
        "otm.whatsapp.lead.stage.trigger", string="Stage Trigger", readonly=True,
        help="Set automatically when this message was created by clicking a "
        "stage button on the lead - kept for reporting, never edited by hand.",
    )
    message = fields.Text(required=True)

    direction = fields.Selection(
        [("out", "Outgoing"), ("in", "Incoming")],
        default="out", required=True, readonly=True,
        help="'Outgoing' covers every message this module itself sends (scheduled, "
        "stage-triggered, or chatbot auto-reply). 'Incoming' is a customer's own "
        "WhatsApp reply, logged here (never sent anywhere) purely so it shows in this "
        "lead's message history alongside what was sent to them.",
    )
    wa_message_id = fields.Char(
        string="WhatsApp Message ID", readonly=True, copy=False, index=True,
        help="The Baileys/WhatsApp message id (stanzaId) this outgoing message was sent "
        "as. Stored so a customer's later quote-reply to THIS exact message can be "
        "matched back to it (see controllers/lead_whatsapp_inbound.py) - never set by "
        "hand.",
    )
    wa_quoted_id = fields.Char(
        string="Replying To (WhatsApp ID)", readonly=True, copy=False,
        help="For an Incoming message only: the wa_message_id of the outgoing message "
        "the customer quote-replied to.",
    )

    # ── Optional media (one per message - WhatsApp only carries one
    # image/video/document per message) ─────────────────────────────────
    attachment_data = fields.Binary(string="Attachment")
    attachment_filename = fields.Char(string="File Name")
    attachment_type = fields.Selection(
        [("image", "Image"), ("video", "Video"), ("document", "Document")],
        compute="_compute_attachment_type", store=True,
        help="Detected automatically from the file's actual content, not just its name.",
    )

    scheduled_datetime = fields.Datetime(string="Scheduled At", tracking=True, index=True)

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("scheduled", "Scheduled"),
            ("processing", "Processing"),
            ("sent", "Sent"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
        index=True,
    )
    sent_date = fields.Datetime(readonly=True)

    retry_count = fields.Integer(default=0, readonly=True)
    max_retry_count = fields.Integer(
        default=lambda self: int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("otm_whatsapp_lead_scheduler.max_retry_count", default="3")
        ),
        help="This message stops offering Retry once retry_count reaches this.",
    )
    last_attempt_date = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True)

    _scheduled_datetime_required = models.Constraint(
        "check(state = 'draft' or scheduled_datetime is not null)",
        "A message that is not a draft must have a scheduled date/time.",
    )

    @api.depends("attachment_filename", "attachment_data")
    def _compute_attachment_type(self):
        for rec in self:
            rec.attachment_type = (
                media_utils.guess_attachment_type(rec.attachment_filename, rec.attachment_data)
                if rec.attachment_data else False
            )

    @api.constrains("attachment_data", "attachment_type")
    def _check_attachment_size(self):
        for rec in self:
            media_utils.check_attachment_size(rec.attachment_filename, rec.attachment_data, rec.attachment_type)

    @api.onchange("template_id")
    def _onchange_template_id(self):
        for rec in self:
            if rec.template_id and rec.lead_id:
                rec.message = rec.template_id.render(rec.lead_id)
            if rec.template_id and rec.template_id.attachment_data:
                rec.attachment_data = rec.template_id.attachment_data
                rec.attachment_filename = rec.template_id.attachment_filename

    @api.onchange("lead_id")
    def _onchange_lead_id(self):
        for rec in self:
            if rec.lead_id and not rec.bot_id:
                bot = self.env["otm.whatsapp.lead.bot"].get_for_user(rec.lead_id.lead_owner.user_id)
                rec.bot_id = bot.id if bot else False
            if rec.lead_id and rec.template_id:
                rec.message = rec.template_id.render(rec.lead_id)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------
    def _get_bot(self):
        self.ensure_one()
        bot = self.bot_id
        if not bot:
            bot = self.env["otm.whatsapp.lead.bot"].get_for_user(self.lead_id.lead_owner.user_id)
        return bot

    @api.model
    def get_by_wa_message_id(self, bot_id, wa_message_id):
        """Used by controllers/lead_whatsapp_inbound.py to resolve which lead a
        customer's quote-reply belongs to. Scoped to bot_id as well as the
        wa_message_id itself - Baileys message ids are only unique per
        WhatsApp session/instance, never globally."""
        if not wa_message_id:
            return self.browse()
        return self.sudo().search(
            [("bot_id", "=", bot_id), ("wa_message_id", "=", wa_message_id), ("direction", "=", "out")],
            limit=1,
        )

    def _validate_ready(self):
        self.ensure_one()
        if not self.lead_id:
            raise UserError(_("Select a Lead."))
        if not self.lead_id.phone_number:
            raise UserError(_("This lead has no phone number on file."))
        if not self.message:
            raise UserError(_("Enter a message, or pick a Template."))
        if not self._get_bot():
            raise UserError(
                _("No WhatsApp connection is configured for %s (this lead's Admission "
                  "Officer). Add one under WhatsApp > Configuration > Lead Bot Connections.")
                % (self.lead_id.lead_owner.name or self.lead_id.lead_owner.user_id.name or _("this officer"))
            )

    def _validate_ready_for_schedule(self):
        self.ensure_one()
        self._validate_ready()
        if not self.scheduled_datetime:
            raise UserError(_("Set a scheduled date/time."))

    def action_schedule(self):
        for rec in self:
            rec._validate_ready_for_schedule()
            rec.write({"state": "scheduled"})
            _logger.info("Lead message %s scheduled for %s", rec.reference, rec.scheduled_datetime)
        return True

    def action_send_now(self):
        for rec in self:
            # Same defensive guard as otm_whatsapp_coexistence's
            # action_send_now: a malformed/grouped selection must fail
            # loudly here rather than crash deep inside the ORM.
            if not isinstance(rec.id, int):
                raise UserError(
                    _("This 'Send Now' action received an invalid selection. Open the "
                      "message itself and retry from there.")
                )
            rec._validate_ready()
            if not rec.scheduled_datetime:
                rec.scheduled_datetime = fields.Datetime.now()
            rec.write({"state": "processing"})
            rec._process_send()
        return True

    def action_cancel(self):
        self.filtered(lambda r: r.state not in ("sent", "cancelled")).write({"state": "cancelled"})
        return True

    def action_reset_to_draft(self):
        self.filtered(lambda r: r.state in ("cancelled", "failed")).write(
            {"state": "draft", "retry_count": 0, "last_error": False}
        )
        return True

    def action_retry(self):
        for rec in self:
            if rec.state != "failed":
                continue
            if rec.retry_count >= (rec.max_retry_count or DEFAULT_MAX_RETRY):
                raise UserError(
                    _("'%s' has reached its maximum retry count (%s).")
                    % (rec.reference, rec.max_retry_count or DEFAULT_MAX_RETRY)
                )
            rec.write(
                {
                    "retry_count": rec.retry_count + 1,
                    "state": "scheduled",
                    "scheduled_datetime": fields.Datetime.now(),
                }
            )
            _logger.info("Lead message %s queued for retry #%s", rec.reference, rec.retry_count)
        return True

    # ------------------------------------------------------------------
    # Sending - reuses the lead-bot connection's own client, never a
    # second/parallel implementation of the HTTP call.
    # ------------------------------------------------------------------
    def _process_send(self):
        self.ensure_one()
        self.write({"last_attempt_date": fields.Datetime.now()})
        bot = self._get_bot()
        if not bot:
            self._mark_failed(_("No WhatsApp Lead Bot connection configured for this lead's officer."))
            return
        if not self.lead_id.phone_number:
            self._mark_failed(_("This lead has no phone number on file."))
            return

        try:
            client = bot._get_client()
            media = media_utils.build_media_payload(
                self.attachment_filename, self.attachment_data, self.attachment_type
            )
            result = client.send_direct_message(self.lead_id.phone_number, self.message or "", media=media)
            if not result.get("success"):
                self._mark_failed(result.get("error") or _("Unknown error from the WhatsApp bot service."))
                return
        except Exception as exc:  # noqa: BLE001 - one message's failure must never abort the batch
            _logger.exception("Lead message %s: unexpected error sending", self.reference)
            self._mark_failed(str(exc))
            return

        self.write(
            {
                "state": "sent",
                "sent_date": fields.Datetime.now(),
                "last_error": False,
                "wa_message_id": result.get("message_id") or False,
            }
        )
        _logger.info("Lead message %s sent to lead '%s'", self.reference, self.lead_id.name)

    def _mark_failed(self, error_message):
        self.ensure_one()
        self.write({"state": "failed", "last_error": error_message})
        _logger.warning("Lead message %s failed: %s", self.reference, error_message)

    # ------------------------------------------------------------------
    # Cron - concurrency-safe batch claim (identical pattern to
    # otm.whatsapp.group.message._cron_process_group_messages)
    # ------------------------------------------------------------------
    @api.model
    def _cron_process_lead_messages(self):
        enabled = self.env["ir.config_parameter"].sudo().get_param(
            "otm_whatsapp_lead_scheduler.enabled", default="true"
        )
        if enabled == "false":
            return

        batch_size = int(
            self.env["ir.config_parameter"].sudo().get_param(
                "otm_whatsapp_lead_scheduler.batch_size", default="50"
            )
        )
        now = fields.Datetime.now()

        # FOR UPDATE SKIP LOCKED: a second concurrent cron worker simply
        # skips any row this one already has locked, instead of blocking or
        # double-sending it - same safe job-queue pattern as the group
        # scheduler's cron.
        self.env.cr.execute(
            """
            SELECT id FROM otm_whatsapp_lead_message
            WHERE state = 'scheduled' AND scheduled_datetime <= %s
            ORDER BY scheduled_datetime
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (now, batch_size),
        )
        ids = [row[0] for row in self.env.cr.fetchall()]
        if not ids:
            return

        messages = self.browse(ids)
        messages.write({"state": "processing"})
        # Commit now: releases the row locks and persists 'processing' so a
        # crash mid-batch can't leave rows silently stuck as 'scheduled'.
        self.env.cr.commit()

        for message in messages:
            try:
                message._process_send()
            except Exception:  # noqa: BLE001 - one message must never stop the rest of the batch
                _logger.exception("Lead message %s: unexpected error during processing", message.id)
                message.write(
                    {
                        "state": "failed",
                        "last_error": "Unexpected server error - see server logs.",
                        "last_attempt_date": fields.Datetime.now(),
                    }
                )
            self.env.cr.commit()
