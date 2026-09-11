"""Data models for the Telegram TUI client (pydantic v2)."""

from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class ChatType(str, Enum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"


class User(BaseModel):
    id: int
    name: str
    is_me: bool = False


class Chat(BaseModel):
    id: int
    title: str
    chat_type: ChatType
    pinned: bool = False
    unread: int = 0
    preview: str = ""
    last_activity: dt.datetime = Field(default_factory=utcnow)
    members_count: str = ""
    is_read_only: bool = False


MEDIA_LABELS = {
    "voice": "🎙 Voice message",
    "video_note": "⭕ Video note",
    "sticker": "🎭 Sticker",
    "photo": "🖼 Photo",
    "document": "📎 Attachment",
}


def media_label(media_type: str, sticker_emoji: str | None = None) -> str:
    """What to show for a message that carries media but no text of its own."""
    label = MEDIA_LABELS.get(media_type, "📎 Attachment")
    if sticker_emoji and media_type == "sticker":
        return f"{label} {sticker_emoji}"
    return label


class Message(BaseModel):
    id: int
    chat_id: int
    sender_id: int | None = 0
    text: str = ""
    timestamp: dt.datetime | None = Field(default_factory=utcnow)
    reply_to: int | None = None
    has_voice: bool = False
    has_photo: bool = False
    media_type: str = "text"  # "text" | "photo" | "voice" | "video_note" | "sticker" | "document"
    duration: int | None = None  # duration in seconds for audio/video
    sticker_emoji: str | None = None
    reactions: list[Any] = Field(default_factory=list)
    waveform: list[int] | None = None
