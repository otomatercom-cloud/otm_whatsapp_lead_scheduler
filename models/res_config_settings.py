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
