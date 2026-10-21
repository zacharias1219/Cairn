"""Email channel (F1, V1).

Inbound: raw RFC 5322 messages (as delivered by any inbound-parse webhook)
are parsed, quoted history and signatures are stripped, and the thread is
preserved through Message-ID / In-Reply-To / References. Outbound replies
are sent from the customer's own domain, threaded, and DKIM-signed when a
signing key is configured. Replies are written to an outbox first.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import re
import uuid
from email.message import EmailMessage

from cairn.channels.message import Attachment, ChannelInfo, CustomerRef, Message
from cairn.config import get_settings
from cairn.db.core import fetch_one, tenant_tx

_QUOTE_HEADER = re.compile(r"^\s*(On .+wrote:|-----Original Message-----|From: .+|Sent from my .+)\s*$", re.I)


def strip_reply(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        if _QUOTE_HEADER.match(line):
            break
        if line.strip() == "--" or line.strip() == "-- ":
            break
        if line.startswith(">"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def parse_inbound(raw: bytes | str, tenant_id: str) -> Message:
    msg = email.message_from_bytes(raw if isinstance(raw, bytes) else raw.encode(), policy=email.policy.default)
    name, addr = email.utils.parseaddr(str(msg.get("From", "")))
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    attachments = [
        Attachment(filename=p.get_filename() or "attachment", content_type=p.get_content_type(),
                   size=len(p.get_payload(decode=True) or b""))
        for p in msg.iter_attachments()
    ]
    refs = str(msg.get("References", "") or "").split()
    envelope = {
        "message_id": str(msg.get("Message-ID", "")).strip(),
        "in_reply_to": str(msg.get("In-Reply-To", "") or "").strip() or None,
        "references": refs,
        "thread_root": refs[0] if refs else (str(msg.get("In-Reply-To", "") or "").strip() or
                                             str(msg.get("Message-ID", "")).strip()),
        "subject": str(msg.get("Subject", "")),
        "to": str(msg.get("To", "")),
    }
    return Message(tenant_id=tenant_id, channel=ChannelInfo(type="email", envelope=envelope),
                   customer=CustomerRef(email=addr.lower() or None, name=name or None),
                   content=strip_reply(text), attachments=attachments)


def build_reply(*, from_addr: str, to_addr: str, subject: str, body: str, in_reply_to: str | None,
                references: list[str], domain: str) -> tuple[EmailMessage, str]:
    m = EmailMessage()
    mid = email.utils.make_msgid(domain=domain)
    m["From"] = from_addr
    m["To"] = to_addr
    m["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    m["Message-ID"] = mid
    m["Date"] = email.utils.formatdate(localtime=False)
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
        m["References"] = " ".join([*references, in_reply_to] if in_reply_to not in references else references)
    m.set_content(body)
    return m, mid


def dkim_sign(raw: bytes, domain: str) -> tuple[bytes, bool]:
    s = get_settings()
    if not s.dkim_private_key_path:
        return raw, False
    import dkim

    with open(s.dkim_private_key_path, "rb") as f:
        key = f.read()
    sig = dkim.sign(raw, s.dkim_selector.encode(), domain.encode(), key,
                    include_headers=[b"from", b"to", b"subject", b"date", b"message-id", b"in-reply-to"])
    return sig + raw, True


async def find_thread(tenant_id: uuid.UUID, envelope: dict) -> uuid.UUID | None:
    ids = [i for i in [envelope.get("thread_root"), envelope.get("in_reply_to"), *envelope.get("references", [])] if i]
    if not ids:
        return None
    async with tenant_tx(tenant_id) as conn:
        row = await fetch_one(conn, "select id from conversations where external_thread_id = any(%s) "
                                    "order by started_at limit 1", (ids,))
        if row:
            return row["id"]
        row = await fetch_one(conn, "select conversation_id from outbox_emails where message_id = any(%s) limit 1",
                              (ids,))
        return row["conversation_id"] if row else None


async def queue_reply(tenant_id: uuid.UUID, conversation_id: uuid.UUID, inbound: Message, body: str,
                      support_addr: str) -> dict:
    env = inbound.channel.envelope
    domain = support_addr.split("@")[-1]
    m, mid = build_reply(from_addr=support_addr, to_addr=inbound.customer.email or "", subject=env.get("subject", ""),
                         body=body, in_reply_to=env.get("message_id"), references=env.get("references", []),
                         domain=domain)
    raw, signed = dkim_sign(bytes(m), domain)
    async with tenant_tx(tenant_id) as conn:
        conv = await fetch_one(conn, "select customer_id from conversations where id=%s", (conversation_id,))
        row = await fetch_one(conn, """
            insert into outbox_emails (tenant_id, conversation_id, customer_id, to_addr, from_addr, subject, body,
              message_id, in_reply_to, references_hdr, raw, dkim_signed)
            values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id, message_id, dkim_signed""",
            (tenant_id, conversation_id, conv["customer_id"], m["To"], m["From"], m["Subject"], body, mid,
             m["In-Reply-To"], m["References"], raw.decode(errors="replace"), signed))
    return row
