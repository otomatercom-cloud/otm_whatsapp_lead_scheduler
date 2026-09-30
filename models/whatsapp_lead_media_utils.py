# -*- coding: utf-8 -*-
"""Shared media helpers for otm.whatsapp.lead.template and
otm.whatsapp.lead.message - both attach at most ONE image/video/document
(WhatsApp can only carry one media item per message, unlike the group
scheduler's multi-attachment lines), so the sniffing/limits/payload-building
logic lives here once instead of being duplicated on both models.

Deliberately copied from otm_whatsapp_group_scheduler's
whatsapp_group_message_attachment.py (magic-byte sniffing, size limits,
media payload shape) rather than importing across modules - this module
must not depend on otm_whatsapp_group_scheduler, and the logic is small
enough that duplication is cheaper than a cross-module coupling.
"""
import base64
import mimetypes

from odoo import _
from odoo.exceptions import UserError

# Same practical WhatsApp media caps used by the group scheduler.
MEDIA_SIZE_LIMITS = {
    "image": 5 * 1024 * 1024,
    "video": 16 * 1024 * 1024,
    "document": 100 * 1024 * 1024,
}

# File-signature ("magic bytes") table, checked BEFORE falling back to
# guessing from the file name's extension - a user-edited "File Name" is
# free text and not reliable on its own.
_MAGIC_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF", "application/pdf"),
)


def sniff_mimetype(b64_data):
    """Best-effort mimetype from the first bytes of a base64 Binary field
    value. Only decodes a small prefix."""
    if not b64_data:
        return None
    if isinstance(b64_data, str):
        b64_data = b64_data.encode()
    prefix = b64_data[:64]
    prefix = prefix[: len(prefix) - (len(prefix) % 4)]  # keep base64 decodable
    try:
        header = base64.b64decode(prefix)
    except (ValueError, TypeError):
        return None
    for magic, mime in _MAGIC_SIGNATURES:
        if header.startswith(magic):
            return mime
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header[4:8] == b"ftyp":  # MP4/MOV/3GP (ISO base media container)
        return "video/mp4"
    return None


def guess_attachment_type(filename, data):
    """Returns 'image' | 'video' | 'document' for the Selection field."""
    mime = sniff_mimetype(data) or mimetypes.guess_type(filename or "")[0] or ""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    return "document"


def check_attachment_size(filename, data, attachment_type):
    """Raises UserError if `data` is over WhatsApp's practical size cap for
    `attachment_type`. No-op if there's no attachment."""
    if not data or attachment_type in (False, None):
        return
    limit = MEDIA_SIZE_LIMITS.get(attachment_type)
    if not limit:
        return
    raw = data.encode() if isinstance(data, str) else data
    size = len(base64.b64decode(raw))
    if size > limit:
        raise UserError(
            _(
                "'%(name)s' is %(size).1f MB, which is over WhatsApp's practical "
                "%(kind)s limit of %(limit)s MB."
            )
            % {
                "name": filename,
                "size": size / (1024 * 1024.0),
                "kind": attachment_type,
                "limit": limit // (1024 * 1024),
            }
        )


def build_media_payload(filename, data, attachment_type):
    """Returns the {base64, mime_type, file_name, media_type} dict the
    LeadBotClient/Node service expect, or None if there's no attachment."""
    if not data:
        return None
    mime = (
        sniff_mimetype(data)
        or mimetypes.guess_type(filename or "")[0]
        or "application/octet-stream"
    )
    raw = data.decode("ascii") if isinstance(data, bytes) else data
    return {
        "base64": raw,
        "mime_type": mime,
        "file_name": filename,
        "media_type": attachment_type or "document",
    }
