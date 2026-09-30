# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LeadsForm(models.Model):
    _inherit = "leads.logic"

    whatsapp_message_ids = fields.One2many(
        "otm.whatsapp.lead.message", "lead_id", string="WhatsApp Messages"
    )
    whatsapp_message_count = fields.Integer(compute="_compute_whatsapp_message_count")

    # Not stored: this must always reflect live stage-trigger configuration,
    # never a stale snapshot from whenever the lead was last saved.
    whatsapp_stage_trigger_id = fields.Many2one(
        "otm.whatsapp.lead.stage.trigger", compute="_compute_whatsapp_stage_trigger",
        string="WhatsApp Stage Trigger",
    )
    whatsapp_stage_button_label = fields.Char(compute="_compute_whatsapp_stage_trigger")

    @api.depends("whatsapp_message_ids")
    def _compute_whatsapp_message_count(self):
        for rec in self:
            rec.whatsapp_message_count = len(rec.whatsapp_message_ids)

    @api.depends("lead_quality", "company_id")
    def _compute_whatsapp_stage_trigger(self):
        Trigger = self.env["otm.whatsapp.lead.stage.trigger"]
        # One search per distinct quality actually present, not per record -
        # cheap even on a list of hundreds of leads.
        by_quality = {}
        for rec in self:
            if rec.lead_quality not in by_quality:
                by_quality[rec.lead_quality] = Trigger.search(
                    [("lead_quality", "=", rec.lead_quality)], limit=1
                )
            trigger = by_quality[rec.lead_quality]
            rec.whatsapp_stage_trigger_id = trigger.id if trigger else False
            rec.whatsapp_stage_button_label = trigger.button_label if trigger else False

    def action_send_stage_whatsapp(self):
        """The one generic stage button on the lead form/kanban. Sends the
        current stage's configured template to the customer IMMEDIATELY,
        via this lead's own Admission Officer's WhatsApp number - no
        confirmation screen, matching the spec ('when they click that
        button, the template message should automatically be sent')."""
        self.ensure_one()
        trigger = self.whatsapp_stage_trigger_id
        if not trigger:
            raise UserError(_("No WhatsApp button is configured for this lead's current stage."))
        if not self.phone_number:
            raise UserError(_("This lead has no phone number on file."))

        bot = self.env["otm.whatsapp.lead.bot"].get_for_user(self.lead_owner.user_id)
        if not bot:
            raise UserError(
                _("No WhatsApp connection is configured for %s. Add one under WhatsApp > "
                  "Configuration > Lead Bot Connections.")
                % (self.lead_owner.name or _("this officer"))
            )
        bot._require_connected()

        message = self.env["otm.whatsapp.lead.message"].create(
            {
                "lead_id": self.id,
                "bot_id": bot.id,
                "template_id": trigger.template_id.id,
                "trigger_id": trigger.id,
                "message": trigger.template_id.render(self, officer=self.lead_owner.user_id),
                "scheduled_datetime": fields.Datetime.now(),
                "state": "processing",
            }
        )
        message._process_send()
        if message.state == "failed":
            raise UserError(
                _("Could not send WhatsApp message: %s") % (message.last_error or _("Unknown error."))
            )
        return True

    def action_open_whatsapp_schedule_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Schedule WhatsApp Message"),
            "res_model": "otm.whatsapp.lead.schedule.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_lead_id": self.id},
        }

    def action_open_whatsapp_messages(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("WhatsApp Messages"),
            "res_model": "otm.whatsapp.lead.message",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)],
            "context": {"default_lead_id": self.id},
        }
