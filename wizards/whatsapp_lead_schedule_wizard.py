# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OtmWhatsappLeadScheduleWizard(models.TransientModel):
    """Small popup opened from the "Schedule WhatsApp" button on a lead:
    pick a template (or type free text) and a date/time, confirm, done. The
    actual scheduled record it creates is an ordinary otm.whatsapp.lead.message
    - this wizard is just a convenient way to create one from the lead's own
    form instead of the WhatsApp menu."""

    _name = "otm.whatsapp.lead.schedule.wizard"
    _description = "Schedule WhatsApp Message"

    lead_id = fields.Many2one("leads.logic", required=True)
    phone_number = fields.Char(related="lead_id.phone_number", readonly=True)
    bot_id = fields.Many2one(
        "otm.whatsapp.lead.bot", string="Send Via", required=True,
        help="Defaults to this lead's own Admission Officer's WhatsApp connection.",
    )
    template_id = fields.Many2one("otm.whatsapp.lead.template", string="Template")
    message = fields.Text(required=True)
    attachment_data = fields.Binary(string="Attachment")
    attachment_filename = fields.Char(string="File Name")
    scheduled_datetime = fields.Datetime(
        required=True, default=lambda self: fields.Datetime.now(),
    )

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        lead_id = res.get("lead_id") or self.env.context.get("default_lead_id")
        if lead_id:
            lead = self.env["leads.logic"].browse(lead_id)
            bot = self.env["otm.whatsapp.lead.bot"].get_for_user(lead.lead_owner.user_id)
            if bot:
                res["bot_id"] = bot.id
        return res

    @api.onchange("template_id")
    def _onchange_template_id(self):
        for rec in self:
            if rec.template_id and rec.lead_id:
                rec.message = rec.template_id.render(rec.lead_id)
            if rec.template_id and rec.template_id.attachment_data:
                rec.attachment_data = rec.template_id.attachment_data
                rec.attachment_filename = rec.template_id.attachment_filename

    def action_confirm(self):
        self.ensure_one()
        if not self.bot_id:
            raise UserError(
                _("No WhatsApp connection is configured for this lead's Admission Officer. "
                  "Add one under WhatsApp > Configuration > Lead Bot Connections.")
            )
        message = self.env["otm.whatsapp.lead.message"].create(
            {
                "lead_id": self.lead_id.id,
                "bot_id": self.bot_id.id,
                "template_id": self.template_id.id if self.template_id else False,
                "message": self.message,
                "attachment_data": self.attachment_data,
                "attachment_filename": self.attachment_filename,
                "scheduled_datetime": self.scheduled_datetime,
            }
        )
        message.action_schedule()
        return {
            "type": "ir.actions.act_window",
            "name": _("WhatsApp Message"),
            "res_model": "otm.whatsapp.lead.message",
            "view_mode": "form",
            "res_id": message.id,
            "target": "current",
        }
