"""Left panel: chat list with search, pins and unread badges."""

from __future__ import annotations

import datetime as dt

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import ListItem, ListView, Static

from ..models import Chat, ChatType

_TYPE_ICON = {
    ChatType.PRIVATE: "",
    ChatType.GROUP: "👥",
    ChatType.CHANNEL: "📢",
}

_BADGE_STYLES = "bold #111413 on #b7e680"
_PIN = "📌"


def _time_label(ts: dt.datetime) -> str:
    local = ts.astimezone()
    if local.date() == dt.date.today():
        return local.strftime("%H:%M")
    return local.strftime("%d.%m")


def _signature(chat: Chat) -> tuple:
    """Everything a row actually shows, so unchanged rows can be left alone."""
    return (
        chat.title,
        chat.pinned,
        chat.unread,
        chat.preview,
        chat.chat_type,
        _time_label(chat.last_activity),
    )


def _top_row(chat: Chat) -> Table:
    type_icon = _TYPE_ICON.get(chat.chat_type, "")
    icon_str = f"{type_icon} " if type_icon else ""
    pin_str = f"{_PIN} " if chat.pinned else ""
    title = Text(
        f"{pin_str}{icon_str}{chat.title}".strip(),
        style="bold #e0af68" if chat.pinned else "bold #f0f0f0",
    )
    grid = Table.grid(expand=True, padding=0)
    grid.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    grid.add_column(justify="right")
    grid.add_row(title, Text(_time_label(chat.last_activity), style="#7aa2f7"))
    return grid


def _bottom_row(chat: Chat) -> Table:
    badge = Text(f" {chat.unread} ", style=_BADGE_STYLES) if chat.unread else Text("")
    preview = Text(chat.preview or "…", style="#9aa5ce")
    grid = Table.grid(expand=True, padding=0)
    grid.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    grid.add_column(justify="right")
    grid.add_row(preview, badge)
    return grid


class ChatItem(ListItem):
    """One row of the chat list: pin, title, time, preview and unread badge."""

    DEFAULT_CSS = """
    ChatItem {
        height: auto;
        padding: 0 1;
        margin: 0 0;
        background: transparent;
        color: #c0caf5;
        border-left: blank;
    }
    ChatItem:hover {
        background: #1f2335;
    }
    ChatItem.-selected {
        background: #24283b;
    }
    ChatItem:focus {
        background: #292e42;
        border-left: thick #b7e680;
    }
    ChatItem Vertical { height: auto; }
    ChatItem Static { height: auto; width: 1fr; }
    """

    def __init__(self, chat: Chat) -> None:
        super().__init__(name=chat.title)
        self.chat_id = chat.id
        self._signature = _signature(chat)
        self._top = Static(_top_row(chat), classes="chat-line")
        self._bottom = Static(_bottom_row(chat), classes="chat-line chat-line-dim")

    def compose(self) -> ComposeResult:
        with Vertical():
            yield self._top
            yield self._bottom

    def update_chat(self, chat: Chat) -> bool:
        """Redraw in place, and only when something visible actually changed."""
        signature = _signature(chat)
        if signature == self._signature:
            return False
        self._signature = signature
        self._top.update(_top_row(chat))
        self._bottom.update(_bottom_row(chat))
        return True


class ChatList(ListView):
    """ListView of ChatItem with vim keys and hotkeys to jump into search."""

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("/", "search", "Search", show=False),
        Binding("p", "app.toggle_pin", "Pin", show=False),
    ]

    DEFAULT_CSS = """
    ChatList {
        height: 1fr;
        background: #16161e;
    }
    """

    def action_search(self) -> None:
        self.app.query_one("#search").focus()

    def sync(self, chats: list[Chat]) -> bool:
        """Update the existing rows in place.

        Returns False when the rows no longer match the chats — a different set
        or a different order — and the caller has to rebuild the list. Rebuilding
        clears the ListView first, so doing it on every incoming message left the
        sidebar blank most of the time in a busy chat.
        """
        items = list(self.query(ChatItem))
        if len(items) != len(chats):
            return False
        for item, chat in zip(items, chats):
            if item.chat_id != chat.id:
                return False
        for item, chat in zip(items, chats):
            item.update_chat(chat)
        return True

    def item_by_chat(self, chat_id: int) -> ChatItem | None:
        for item in self.query(ChatItem):
            if item.chat_id == chat_id:
                return item
        return None

    def highlighted_chat_id(self) -> int | None:
        item = self.highlighted_child
        return item.chat_id if isinstance(item, ChatItem) else None
