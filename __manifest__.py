# -*- coding: utf-8 -*-
{
    "name": "Otomater WhatsApp Lead Message Scheduler",
    "version": "19.0.1.0.0",
    "category": "Customizations",
    "summary": "Per-Admission-Officer WhatsApp numbers, individual lead message scheduling, "
    "and one-click stage-triggered template sends",
    "description": """
Otomater WhatsApp Lead Message Scheduler
==========================================
Lets each Admission Officer connect their OWN WhatsApp number and:

* Schedule an individual WhatsApp message (from a template or free text) to a
  lead/customer for a future date/time.
* Get a "Send WhatsApp" button right on the lead, labeled after the lead's
  current stage (Lead Quality) - e.g. a lead sitting in "Call Back" shows a
  button labeled "Call Back Reminder" (whatever the admin configured). One
  click sends that stage's template to the customer IMMEDIATELY via the
  officer's own configured number - no confirmation screen, no API call to
  Meta.

IMPORTANT - read before using
------------------------------
This does NOT use Meta's official WhatsApp Business Platform Cloud API
(`otm_whatsapp_coexistence`). It talks to a per-officer instance of the
companion `otm-whatsapp-group-bot-service` (unofficial Baileys/WhatsApp-Web
automation - same engine `otm_whatsapp_group_scheduler` uses for group
sends). Using it violates WhatsApp's Terms of Service and carries a real ban
risk for the connected number - that is a business decision made outside
this code, not something this module tries to hide or minimize.

Each Admission Officer's number is a SEPARATE running instance of that Node
service (own port, own auth folder, own QR pairing) - never one shared
number, and never multiple officers sharing one session. This module only
adds a small "send to one phone number" endpoint to that service
(`POST /send-direct`), alongside the group-send endpoint it already has; see
the companion `bot_service_update/` files shipped with this module.

Architecture
------------
* Depends on `custom_leads_19` (the `leads.logic` call-center CRM) and on
  `otm_whatsapp_coexistence` only for shared security/menu placement -
  mirrors `otm_whatsapp_group_scheduler`'s own approach, zero edits to
  either of those modules.
* `otm.whatsapp.lead.bot` - one WhatsApp number/session per Admission
  Officer (`user_id`, unique), same URL/token/QR-pairing UX as the group
  bot connection.
* `otm.whatsapp.lead.template` - reusable message text with placeholders
  ({lead_name}, {phone_number}, {course}, {place}, {college_name},
  {officer_name}).
* `otm.whatsapp.lead.stage.trigger` - admin-configurable list mapping a
  Lead Quality (stage) to a button label + template. Add/remove stages any
  time without a code change.
* `otm.whatsapp.lead.message` - the scheduled/sent message itself: full
  draft/scheduled/processing/sent/failed/cancelled state machine with
  retry, same shape as `otm.whatsapp.group.message`.
* Cron uses `SELECT ... FOR UPDATE SKIP LOCKED` to claim a batch safely
  under concurrent execution, exactly like the group scheduler's cron.
* `leads.logic` gets: a computed stage button (label + visibility driven by
  the trigger list above), a "Schedule WhatsApp" button opening a small
  wizard, and a smart button showing that lead's WhatsApp message history.

Reply chatbot (optional, off by default)
-----------------------------------------
When a customer directly quote-replies (WhatsApp's own reply/quote feature)
to a stage-triggered template this module sent, an officer's bot instance
forwards that reply to a new `/otm_whatsapp_lead/inbound` endpoint. A small
FAQ list (`otm.whatsapp.lead.chatbot.faq`) is checked first, then an
optional AI provider (reusing `otm_whatsapp_chatbot`'s own
`otm.whatsapp.ai.provider` model - genuinely transport-agnostic, no
Coexistence-specific coupling), then an optional fallback message. This is
a deliberately independent, lightweight engine - NOT a reuse of
`otm_whatsapp_chatbot`'s own flow/session engine, which requires a
Coexistence phone number and would otherwise need faking one per officer.
Turned on under WhatsApp > Configuration > Lead Scheduler Settings. Only
ever activates on a direct quote-reply to a tracked outgoing message -
never on an arbitrary incoming message.
""",
    "author": "Otomater",
    "website": "https://otomater.com",
    "license": "OPL-1",
    "depends": [
        "base", "mail", "custom_leads_19", "otm_whatsapp_coexistence",
        # Only for otm.whatsapp.ai.provider (genuinely provider-agnostic,
        # no Coexistence-specific fields) - reused by the reply chatbot's
        # optional AI fallback. The FAQ/rule matching itself is a deliberate
        # independent copy, NOT a dependency on this module's chatbot engine
        # - see models/whatsapp_lead_chatbot_faq.py's docstring for why.
        "otm_whatsapp_chatbot",
    ],
    "data": [
        "security/whatsapp_lead_security_groups.xml",
        "security/ir.model.access.csv",
        "security/whatsapp_lead_security_rules.xml",
        "data/ir_sequence_data.xml",
        "data/ir_cron_data.xml",
        # Load order matters, same reason as otm_whatsapp_group_scheduler's
        # manifest: whatsapp_lead_message_views.xml's list/form is referenced
        # by %(xmlid)d in leads_logic_views.xml's smart button, which
        # resolves eagerly at XML-parse time - so it must load first.
        "wizards/whatsapp_lead_schedule_wizard_views.xml",
        "views/whatsapp_lead_message_views.xml",
        "views/whatsapp_lead_bot_views.xml",
        "views/whatsapp_lead_template_views.xml",
        "views/whatsapp_lead_stage_trigger_views.xml",
        "views/whatsapp_lead_chatbot_faq_views.xml",
        "views/res_config_settings_views.xml",
        "views/leads_logic_views.xml",
        "views/whatsapp_menus.xml",
    ],
    "external_dependencies": {"python": ["requests"]},
    "installable": True,
    "application": False,
    "auto_install": False,
}
