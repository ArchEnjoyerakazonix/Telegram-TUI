"""Data models for the Telegram TUI client (pydantic v2)."""

from __future__ import annotations

import datetime as dt
from enum import Enum

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


class Message(BaseModel):
    id: int
    chat_id: int
    sender_id: int
    text: str
    timestamp: dt.datetime = Field(default_factory=utcnow)
    reply_to: int | None = None
