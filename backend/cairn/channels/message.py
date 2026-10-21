"""The single normalized Message schema (F1).

Every channel turns its input into this object, so the orchestrator never
knows or cares where a conversation started. Everything specific to a
transport (email subject and thread headers, widget session, outside-agent
identity) lives inside ``channel``; the rest of the object is the same for
the same message whichever way it arrived.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ChannelType = Literal["web", "email", "pap", "playground", "eval"]


class ChannelInfo(BaseModel):
    type: ChannelType
    envelope: dict[str, Any] = Field(default_factory=dict)


class CustomerRef(BaseModel):
    email: str | None = None
    phone: str | None = None
    crm_id: str | None = None
    name: str | None = None
    verified: bool = False

    def keys(self) -> dict[str, str]:
        return {k: v for k, v in (("email", self.email), ("phone", self.phone), ("crm_id", self.crm_id)) if v}


class Attachment(BaseModel):
    filename: str
    content_type: str
    size: int


class Message(BaseModel):
    tenant_id: str
    channel: ChannelInfo
    customer: CustomerRef = Field(default_factory=CustomerRef)
    content: str
    attachments: list[Attachment] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
