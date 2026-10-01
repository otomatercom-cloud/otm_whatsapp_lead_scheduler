# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    otm_lead_scheduler_enabled = fields.Boolean(
        string="Enable Lead Message Scheduler",
        config_parameter="otm_whatsapp_lead_scheduler.enabled",
        default=True,
        help="Turns the cron that sends due scheduled lead messages on or off. Existing "
        "draft/scheduled records are kept either way. The stage-triggered 'Send WhatsApp' "
        "button on a lead is unaffected - it always sends immediately, not through this cron.",
    )
    otm_lead_scheduler_batch_size = fields.Integer(
        string="Batch Size",
        config_parameter="otm_whatsapp_lead_scheduler.batch_size",
        default=50,
        help="Maximum number of due lead messages the cron claims and sends per run.",
    )
    otm_lead_scheduler_max_retry_count = fields.Integer(
        string="Default Maximum Retries",
        config_parameter="otm_whatsapp_lead_scheduler.max_retry_count",
        default=3,
        help="Default 'Maximum Retries' for newly created lead messages. Each message can "
        "still override this individually.",
    )

    otm_lead_chatbot_enabled = fields.Boolean(
        string="Enable Reply Chatbot",
        config_parameter="otm_whatsapp_lead_scheduler.chatbot_enabled",
        default=False,
        help="When a customer directly quote-replies (on WhatsApp) to a stage-triggered "
        "template this module sent, check the FAQ list below (and the AI provider if "
        "set) and auto-reply through that same officer's number. Off by default - the "
        "officer's own WhatsApp number keeps working normally either way; this only "
        "controls the automatic reply-to-reply behavior.",
    )
    otm_lead_chatbot_ai_provider_id = fields.Many2one(
        "otm.whatsapp.ai.provider", string="AI Provider",
        config_parameter="otm_whatsapp_lead_scheduler.chatbot_ai_provider_id",
        help="Optional. Reuses the same AI Provider configuration as the WhatsApp "
        "Chatbot module (Settings there). Only consulted when no FAQ below matches. "
        "Leave blank to use FAQs only.",
    )
    # ODOO 19 RULE: res.config.settings + config_parameter only accepts
    # boolean/integer/float/char/selection/many2one/datetime - NOT Text.
    # ir_http raises "Field ... must have type ..." (a real crash, not a
    # lint warning) the moment this screen is opened if a Text field here
    # has config_parameter set. Char has no practical length limit in
    # Postgres/Odoo (unless a `size` is given), so it's the correct type
    # for a long fallback message too, never Text, on this specific model.
    otm_lead_chatbot_fallback_message = fields.Char(
        string="Fallback Message",
        config_parameter="otm_whatsapp_lead_scheduler.chatbot_fallback_message",
        help="Sent only when neither a FAQ nor the AI provider (if configured) produced "
        "an answer. Leave blank to send nothing in that case - the reply is still logged "
        "so the officer sees it, they just won't get an automatic WhatsApp reply.",
    )
