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
    "video": "🎬 Video",
    "gif": "🌀 GIF",
    "audio": "🎵 Audio",
    "document": "📎 File",
    "contact": "👤 Contact",
    "geo": "📍 Location",
    "poll": "📊 Poll",
}


def media_label(media_type: str, sticker_emoji: str | None = None) -> str:
    """What to show for a message that carries media but no text of its own."""
    label = MEDIA_LABELS.get(media_type, "📎 Attachment")
    if sticker_emoji and media_type == "sticker":
        return f"{label} {sticker_emoji}"
    return label


def format_size(size: int | None) -> str:
    """Byte count as a short human string: 812 B, 480 KB, 12.4 MB, 1.3 GB."""
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        return ""
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024
        if value < 1024:
            return f"{value:.0f} {unit}" if value >= 100 else f"{value:.1f} {unit}"
    return f"{value:.1f} PB"


def format_duration(seconds: int | None) -> str:
    """Seconds as 0:45 or 1:02:03."""
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 0:
        return ""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


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
    file_name: str | None = None
    file_size: int | None = None
    mime_type: str | None = None

    def media_summary(self) -> str:
        """One line describing the attachment: name, then duration, then size."""
        if self.media_type == "text":
            return ""
        parts = [self.file_name or media_label(self.media_type, self.sticker_emoji)]
        duration = format_duration(self.duration)
        if duration:
            parts.append(duration)
        size = format_size(self.file_size)
        if size:
            parts.append(size)
        return " · ".join(parts)
