"""The Telegram TUI application: three-panel layout on Textual."""

from __future__ import annotations

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Input, ListView

from .engine import MockEngine
from .models import Chat, Message
from .widgets.chat_list import ChatItem, ChatList
from .widgets.chat_view import ChatView
from .widgets.composer import Composer

TICK_SECONDS = 6.0


class TelegramTUI(App[None]):
    """Terminal Telegram client (mock engine by default)."""

    TITLE = "Telegram TUI"
    SUB_TITLE = "mock engine"

    CSS = """
    #layout { height: 1fr; }
    #sidebar {
        width: 36;
        min-width: 24;
        height: 1fr;
        background: $surface;
        border-right: heavy $panel;
    }
    #search { height: 3; margin: 0; border-bottom: solid $panel; }
    #search:focus { border-bottom: solid $accent; }
    ChatList { height: 1fr; }
    #main { width: 1fr; height: 1fr; }
    ChatView { height: 1fr; }
    #composer {
        height: 5;
        border: round $primary;
    }
    #composer:focus { border: round $accent; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+f", "focus_panel('search')", "Search", priority=True),
        Binding("ctrl+down", "focus_panel('next')", "Next panel", priority=True),
        Binding("ctrl+up", "focus_panel('prev')", "Prev panel", priority=True),
        Binding("escape", "back_to_list", "Back to chats", priority=True),
        Binding("ctrl+p", "toggle_pin", "Pin chat", priority=True),
        Binding("ctrl+m", "mark_read", "Mark read", priority=True),
        Binding("ctrl+u", "force_incoming", "Simulate msg", priority=True),
    ]

    def __init__(self, engine: MockEngine | None = None, live_traffic: bool = True) -> None:
        super().__init__()
        self.engine = engine or MockEngine()
        self.live_traffic = live_traffic
        self.current_chat_id: int | None = None
        self._search_query = ""

    # -- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="layout"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="Search chats… (/ or Ctrl+F)", id="search")
                yield ChatList(id="chat-list")
            with Vertical(id="main"):
                yield ChatView(self.engine)
                yield Composer(id="composer", placeholder="Write a message… (Enter — send, Alt+Enter — newline)")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_chat_list()
        first = self.engine.sorted_chats()
        if first:
            self.open_chat(first[0].id)
        self.query_one(ChatList).focus()
        if self.live_traffic:
            self.set_interval(TICK_SECONDS, self._engine_tick)

    # -- chat list ----------------------------------------------------------

    def refresh_chat_list(self) -> None:
        chat_list = self.query_one(ChatList)
        keep_id = chat_list.highlighted_chat_id() or self.current_chat_id
        chat_list.clear()
        for chat in self.engine.sorted_chats(self._search_query):
            chat_list.mount(ChatItem(chat))
        self._restore_highlight(chat_list, keep_id)

    def _restore_highlight(self, chat_list: ChatList, chat_id: int | None) -> None:
        if chat_id is None:
            return
        items = list(chat_list.query(ChatItem))
        for index, item in enumerate(items):
            if item.chat_id == chat_id:
                chat_list.index = index
                return

    def open_chat(self, chat_id: int) -> None:
        self.current_chat_id = chat_id
        chat = self.engine.chats[chat_id]
        self.engine.mark_read(chat_id)
        self.sub_title = chat.title
        self.query_one(ChatView).show_chat(self.engine.chats[chat_id])
        self.refresh_chat_list()

    @on(ListView.Selected, "#chat-list")
    def chat_selected(self, event: ListView.Selected) -> None:
        assert isinstance(event.item, ChatItem)
        self.open_chat(event.item.chat_id)

    # -- search ---------------------------------------------------------------

    @on(Input.Changed, "#search")
    def search_changed(self, event: Input.Changed) -> None:
        self._search_query = event.value
        self.refresh_chat_list()

    @on(Input.Submitted, "#search")
    def search_submitted(self, event: Input.Submitted) -> None:
        chat_list = self.query_one(ChatList)
        chat_list.focus()
        if chat_list.index is None and chat_list.item_count:
            chat_list.index = 0

    # -- composer -------------------------------------------------------------

    @on(Composer.Sent)
    def message_sent(self, event: Composer.Sent) -> None:
        if self.current_chat_id is None:
            return
        message = self.engine.send(self.current_chat_id, event.text)
        self.query_one(ChatView).append_message(message)
        self.refresh_chat_list()
        planned = self.engine.plan_auto_reply(self.current_chat_id)
        if planned is not None:
            chat_id = self.current_chat_id
            self.set_timer(planned.delay, lambda: self._deliver(planned.factory(), chat_id))

    def _deliver(self, message: Message, chat_id: int) -> None:
        self.engine.chats[chat_id].unread += 1
        self._ingest(message)

    # -- live traffic -----------------------------------------------------------

    def _engine_tick(self) -> None:
        for message in self.engine.tick():
            self._ingest(message)

    def _ingest(self, message: Message) -> None:
        """Route a freshly created incoming message into the UI."""
        chat = self.engine.chats[message.chat_id]
        if message.chat_id == self.current_chat_id:
            self.engine.mark_read(message.chat_id)
            self.query_one(ChatView).append_message(message)
        self.notify_incoming(chat, message)

    def notify_incoming(self, chat: Chat, message: Message) -> None:
        sender = self.engine.sender_name(message.sender_id)
        self.sub_title = f"{chat.title} — {sender} is typing…"
        self.set_timer(2.0, self._clear_typing)
        self.refresh_chat_list()

    def _clear_typing(self) -> None:
        chat = self.engine.chats.get(self.current_chat_id) if self.current_chat_id else None
        self.sub_title = chat.title if chat else ""

    # -- actions ------------------------------------------------------------

    def action_focus_panel(self, target: str) -> None:
        if target == "search":
            self.query_one("#search").focus()
            return
        order = ["chat-list", "composer", "search"]
        focused_id = self.focused.id if self.focused else None
        try:
            index = order.index(focused_id) if focused_id in order else 0
        except ValueError:
            index = 0
        step = -1 if target == "prev" else 1
        for _ in range(len(order)):
            index = (index + step) % len(order)
            try:
                self.query_one(f"#{order[index]}").focus()
            except Exception:
                continue
            return

    def action_back_to_list(self) -> None:
        focused = self.focused
        if focused and focused.id == "search":
            focused.value = ""
            self._search_query = ""
            self.refresh_chat_list()
            self.query_one(ChatList).focus()
            return
        if focused and focused.id == "composer":
            self.query_one(ChatList).focus()
            return
        if self.focused and self.focused.id == "chat-list" and self._search_query:
            self.query_one("#search", Input).value = ""
            self._search_query = ""
            self.refresh_chat_list()

    def selected_chat(self) -> Chat | None:
        chat_list = self.query_one(ChatList)
        chat_id = chat_list.highlighted_chat_id() or self.current_chat_id
        return self.engine.chats.get(chat_id) if chat_id is not None else None

    def action_toggle_pin(self) -> None:
        chat = self.selected_chat()
        if chat:
            self.engine.toggle_pin(chat.id)
            self.refresh_chat_list()

    def action_mark_read(self) -> None:
        chat = self.selected_chat()
        if chat:
            self.engine.mark_read(chat.id)
            self.refresh_chat_list()

    def action_force_incoming(self) -> None:
        self._ingest(self.engine.inject_incoming())
