# -*- coding: utf-8 -*-
from odoo import fields, models


class OtmWhatsappLeadStageTrigger(models.Model):
    """Admin-configurable "when a lead is at this stage, show this button,
    which sends this template" list. Adding/removing a stage button is a
    data change here, never a code/view change - the lead form always shows
    ONE generic button whose label and template are looked up from this list
    for the lead's current lead_quality (see leads_logic.py).
    """

    _name = "otm.whatsapp.lead.stage.trigger"
    _description = "WhatsApp Stage-Triggered Send Button"
    _rec_name = "button_label"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, index=True
    )

    lead_quality = fields.Selection(
        selection=lambda self: self.env["leads.logic"]._fields["lead_quality"].selection,
        string="Stage (Lead Quality)", required=True,
        help="Which leads.logic 'Lead Quality' value shows this button. Always kept in "
        "sync with leads.logic's own list - a new stage added there is immediately "
        "selectable here, no code change needed.",
    )
    button_label = fields.Char(
        required=True,
        help="What the button says on the lead, e.g. 'Call Back Reminder', 'Send Tomorrow'.",
    )
    template_id = fields.Many2one(
        "otm.whatsapp.lead.template", string="Template", required=True,
        help="Sent immediately, as-is (rendered with this lead's own details), when the "
        "button is clicked - no confirmation screen.",
    )

    _stage_uniq = models.Constraint(
        "unique(lead_quality, company_id)",
        "This stage already has a WhatsApp button configured for this company.",
    )
