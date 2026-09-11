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

        unread = chat.unread
        badge = Text(f" {unread} ", style=_BADGE_STYLES) if unread else Text("")

        type_icon = _TYPE_ICON.get(chat.chat_type, "")
        icon_str = f"{type_icon} " if type_icon else ""
        pin_str = f"{_PIN} " if chat.pinned else ""
        title = Text(f"{pin_str}{icon_str}{chat.title}".strip(), style="bold #e0af68" if chat.pinned else "bold #f0f0f0")

        top = Table.grid(expand=True, padding=0)
        top.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        top.add_column(justify="right")
        top.add_row(title, Text(_time_label(chat.last_activity), style="#7aa2f7"))

        preview_text = chat.preview or "…"
        preview = Text(preview_text, style="#9aa5ce")
        bottom = Table.grid(expand=True, padding=0)
        bottom.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
        bottom.add_column(justify="right")
        bottom.add_row(preview, badge)

        self._top = top
        self._bottom = bottom

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._top, classes="chat-line")
            yield Static(self._bottom, classes="chat-line chat-line-dim")


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

    def item_by_chat(self, chat_id: int) -> ChatItem | None:
        for item in self.query(ChatItem):
            if item.chat_id == chat_id:
                return item
        return None

    def highlighted_chat_id(self) -> int | None:
        item = self.highlighted_child
        return item.chat_id if isinstance(item, ChatItem) else None
