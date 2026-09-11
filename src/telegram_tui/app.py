"""The Telegram TUI application: three-panel layout on Textual."""

from __future__ import annotations

import inspect

from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.widgets import Footer, Header, Input, ListView, Static

from .auth import LoginScreen, WelcomeScreen
from .backend import BaseBackend
from .config import Config
from .engine import MockEngine
from .media import VoicePlayer
from .models import Chat, Message
from .widgets.chat_list import ChatItem, ChatList
from .widgets.chat_view import ChatView
from .widgets.composer import Composer

TICK_SECONDS = 6.0


class BackendIncoming(TextualMessage):
    """Incoming message delivered by a live backend."""

    def __init__(self, message: Message) -> None:
        self.message = message
        super().__init__()


class BackendHistoryReady(TextualMessage):
    """A live backend finished fetching a chat's history."""

    def __init__(self, chat_id: int) -> None:
        self.chat_id = chat_id
        super().__init__()


class TelegramTUI(App[None]):
    """Terminal Telegram client (mock engine by default, Telethon for live)."""

    TITLE = "Telegram TUI"

    CSS = """
    #layout { height: 1fr; }
    #sidebar {
        /* Never more than half the screen: a fixed 36 columns squeezed the
           message panel to zero width on a narrow terminal, which crashed the
           composer's text wrapping. */
        width: 36;
        min-width: 16;
        max-width: 50%;
        height: 1fr;
        background: #16161e;
        border-right: solid #2a2e3f;
    }
    #search {
        height: 3;
        margin: 0;
        background: #1f2335;
        border: solid #2a2e3f;
        color: #c0caf5;
    }
    #search:focus { border: solid #b7e680; }
    ChatList { height: 1fr; background: #16161e; }
    #main { width: 1fr; height: 1fr; background: #1a1b26; }
    #msg-search { display: none; background: #1f2335; border: solid #b7e680; color: #c0caf5; }
    ChatView { height: 1fr; background: #1a1b26; }
    #channel-banner {
        height: 3;
        background: #1f2335;
        color: #7aa2f7;
        content-align: center middle;
        text-style: bold;
        border-top: solid #2a2e3f;
        display: none;
    }
    #composer {
        height: 5;
        background: #16161e;
        border: round #3b4261;
    }
    #composer:focus { border: round #b7e680; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", priority=True),
        Binding("ctrl+f", "focus_panel('search')", "Search", priority=True),
        Binding("ctrl+e", "search_in_chat", "Find in chat", priority=True),
        Binding("ctrl+o", "load_older_history", "Load history", priority=True),
        Binding("ctrl+down", "focus_panel('next')", "Next panel", priority=True),
        Binding("ctrl+up", "focus_panel('prev')", "Prev panel", priority=True, show=False),
        Binding("escape", "back_to_list", "Back to chats", priority=True),
        # Shown by the feed itself, where the selection it acts on lives.
        Binding("o", "open_media", "Open media", priority=False, show=False),
        Binding("ctrl+p", "toggle_pin", "Pin chat", priority=True),
        Binding("ctrl+m", "mark_read", "Mark read", priority=True, show=False),
        Binding("ctrl+u", "force_incoming", "Simulate msg", priority=True, show=False),
    ]

    def __init__(
        self,
        engine: BaseBackend | None = None,
        live_traffic: bool = True,
        config: Config | None = None,
        show_welcome: bool = False,
    ) -> None:
        super().__init__()
        self.engine = engine or MockEngine()
        self.live_traffic = live_traffic
        self.config = config or Config()
        self.show_welcome = show_welcome
        self.current_chat_id: int | None = None
        self._search_query = ""
        self.pending_reply: tuple[int, int] | None = None
        self.voice_player = VoicePlayer(self.config.media_player)

    # -- layout ---------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="layout"):
            with Vertical(id="sidebar"):
                yield Input(placeholder="Search chats… (/ or Ctrl+F)", id="search")
                yield ChatList(id="chat-list")
            with Vertical(id="main"):
                yield Input(
                    placeholder="Search in chat… (Enter/n: next, N: prev, Esc: hide)",
                    id="msg-search",
                )
                yield ChatView(self.engine)
                yield Static("📢 Read-only channel (posting is restricted)", id="channel-banner")
                yield Composer(id="composer", placeholder="Write a message… (Enter — send, Alt+Enter — newline)")
        yield Footer()

    def on_mount(self) -> None:
        if self.show_welcome:
            self.run_worker(self._show_welcome_and_start(), exclusive=True)
            return

        if self.engine.is_mock:
            self._init_ui()
            if self.live_traffic:
                self.set_interval(self.config.traffic_interval, self._engine_tick)
        else:
            self.run_worker(self._bootstrap(), exclusive=True)

    async def _bootstrap(self) -> None:
        """Live-mode startup: connect, authorize in-terminal, load chats."""
        try:
            authorized = await self.engine.start()
        except Exception as exc:  # noqa: BLE001
            self.notify(f"Connection failed: {exc}", severity="error", timeout=8)
            self.exit(message=f"Failed to connect: {exc}")
            return

        if not authorized:
            try:
                granted = await self.push_screen_wait(LoginScreen(self.engine))
            except Exception as exc:  # noqa: BLE001
                self.exit(message=f"Login error: {exc}")
                return
            if not granted:
                self.exit(message="Authentication cancelled. Run again to retry.")
                return

        self.engine.on_incoming = lambda msg: self.post_message(BackendIncoming(msg))
        self.engine.on_history = lambda chat_id: self.post_message(
            BackendHistoryReady(chat_id)
        )

        try:
            await self.engine.load()
        except Exception as exc:  # noqa: BLE001
            self.notify(f"Failed to load chats: {exc}", severity="error", timeout=8)
            self.exit(message=f"Failed to load chats: {exc}")
            return

        self._init_ui()

    def action_load_older_history(self) -> None:
        view = self.query_one(ChatView)
        self.run_worker(view.action_load_older())

    async def _show_welcome_and_start(self) -> None:
        mode = await self.push_screen_wait(WelcomeScreen())
        if mode == "login":
            if not self.config.api_id or not self.config.api_hash:
                from .auth import ApiCredentialsScreen

                creds = await self.push_screen_wait(ApiCredentialsScreen())
                if creds is None or not isinstance(creds, tuple):
                    self._init_ui()
                    return
                self.config.api_id, self.config.api_hash = creds
                self.config.mode = "live"
                try:
                    Config.save_credentials(self.config.api_id, self.config.api_hash, session=self.config.session)
                    self.notify("Credentials saved to ~/.config/telegram-tui/config.toml")
                except Exception:
                    pass

            from .telethon_backend import TelethonBackend

            self.engine = TelethonBackend(self.config.api_id, self.config.api_hash, self.config.session)
            await self._bootstrap()
        else:
            self._init_ui()
            if self.live_traffic:
                self.set_interval(self.config.traffic_interval, self._engine_tick)

    def _init_ui(self) -> None:
        if self.engine.is_mock:
            self.sub_title = "mock engine"
        else:
            me = getattr(self.engine, "users", {}).get(getattr(self.engine, "me_id", 0))
            self.sub_title = f"live · {me}" if me else "live"
        self.refresh_chat_list()
        first = self.engine.sorted_chats()
        if first:
            self.open_chat(first[0].id)
        self.query_one(ChatList).focus()

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

    def open_chat(self, chat_id: int, force: bool = False) -> None:
        if chat_id not in self.engine.chats:
            return
        if chat_id == self.current_chat_id and not force:
            return
        self.current_chat_id = chat_id
        chat = self.engine.chats[chat_id]
        self.engine.mark_read(chat_id)
        self.sub_title = chat.title
        view = self.query_one(ChatView)
        if not self.engine.ensure_history(chat_id):
            view.remove_children()
            view.mount(Static("Loading history…", markup=False))
        else:
            view.show_chat(self.engine.chats[chat_id])

        # Read-only channel banner handling
        channel_banner = self.query_one("#channel-banner", Static)
        composer = self.query_one("#composer", Composer)
        if getattr(chat, "is_read_only", False):
            channel_banner.display = True
            composer.display = False
        else:
            channel_banner.display = False
            composer.display = True

        self.refresh_chat_list()

    @on(ListView.Selected, "#chat-list")
    def chat_selected(self, event: ListView.Selected) -> None:
        assert isinstance(event.item, ChatItem)
        self.open_chat(event.item.chat_id, force=True)

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

    @on(Input.Changed, "#msg-search")
    def msg_search_changed(self, event: Input.Changed) -> None:
        self.query_one(ChatView).update_hits(event.value)

    @on(Input.Submitted, "#msg-search")
    def msg_search_submitted(self, event: Input.Submitted) -> None:
        view = self.query_one(ChatView)
        view.action_next_hit()
        view.focus()

    def action_search_in_chat(self) -> None:
        search = self.query_one("#msg-search", Input)
        search.display = True
        search.focus()

    def hide_msg_search(self) -> None:
        search = self.query_one("#msg-search", Input)
        if search.display:
            search.display = False
            search.value = ""
            self.query_one(ChatView).update_hits("")

    # -- composer -------------------------------------------------------------

    @on(Composer.Sent)
    async def message_sent(self, event: Composer.Sent) -> None:
        if self.current_chat_id is None:
            return
        reply_to = None
        if self.pending_reply and self.pending_reply[0] == self.current_chat_id:
            reply_to = self.pending_reply[1]
        try:
            result = self.engine.send(self.current_chat_id, event.text, reply_to=reply_to)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            self.notify(f"Failed to send: {exc}", severity="error")
            return
        self.clear_pending_reply()
        self.query_one(ChatView).append_message(result)
        self.refresh_chat_list()
        if self.engine.is_mock:
            planned = self.engine.plan_auto_reply(self.current_chat_id)
            if planned is not None:
                chat_id = self.current_chat_id
                self.set_timer(planned.delay, lambda: self._deliver(planned.factory(), chat_id))

    def _deliver(self, message: Message, chat_id: int) -> None:
        chat = self.engine.chats.get(chat_id)
        if chat is not None:
            chat.unread += 1
        self._ingest(message)

    # -- live traffic -----------------------------------------------------------

    def _engine_tick(self) -> None:
        for message in self.engine.tick():
            self._ingest(message)

    @on(BackendIncoming)
    def backend_incoming(self, event: BackendIncoming) -> None:
        self._ingest(event.message)

    @on(BackendHistoryReady)
    def backend_history_ready(self, event: BackendHistoryReady) -> None:
        """Swap the "Loading history…" placeholder for the messages that landed."""
        chat = self.engine.chats.get(event.chat_id)
        if chat is None:
            return
        if event.chat_id == self.current_chat_id:
            self.query_one(ChatView).show_chat(chat)
        self.refresh_chat_list()

    def _ingest(self, message: Message) -> None:
        """Route a freshly created incoming message into the UI."""
        chat = self.engine.chats.get(message.chat_id)
        if chat is None:
            return
        if message.chat_id == self.current_chat_id:
            self.engine.mark_read(message.chat_id)
            self.query_one(ChatView).append_message(message)
        if message.sender_id == self.engine.me_id:
            # Our own message, echoed back from another device: nobody is typing.
            self.refresh_chat_list()
            return
        self.notify_incoming(chat, message)

    def notify_incoming(self, chat: Chat, message: Message) -> None:
        sender = self.engine.sender_name(message.sender_id)
        self.sub_title = f"{chat.title} — {sender} is typing…"
        self.set_timer(2.0, self._clear_typing)
        self.refresh_chat_list()

    def _clear_typing(self) -> None:
        chat = self.engine.chats.get(self.current_chat_id) if self.current_chat_id else None
        self.sub_title = chat.title if chat else ""

    # -- panels / escape ----------------------------------------------------

    def action_focus_panel(self, target: str) -> None:
        if target == "search":
            self.query_one("#search").focus()
            return
        order = ["chat-list", "messages", "composer", "search"]
        focused_id = self.focused.id if self.focused else None
        index = order.index(focused_id) if focused_id in order else 0
        step = -1 if target == "prev" else 1
        for _ in range(len(order)):
            index = (index + step) % len(order)
            try:
                self.query_one(f"#{order[index]}").focus()
            except Exception:
                continue
            return

    def action_back_to_list(self) -> None:
        if len(self.screen_stack) > 1:  # modal is up: Esc cancels it
            if hasattr(self.screen, "action_cancel"):
                self.screen.action_cancel()
            else:
                self.screen.dismiss(None)
            return
        focused = self.focused
        if focused and focused.id == "composer":
            if self.pending_reply:
                self.clear_pending_reply()
                return
            self.query_one(ChatList).focus()
            return
        msg_search = self.query_one("#msg-search", Input)
        if msg_search.display:
            self.hide_msg_search()
            self.query_one(ChatView).focus()
            return
        if focused and focused.id == "search":
            focused.value = ""
            self._search_query = ""
            self.refresh_chat_list()
            self.query_one(ChatList).focus()
            return
        if self.focused and self.focused.id == "chat-list" and self._search_query:
            self.query_one("#search", Input).value = ""
            self._search_query = ""
            self.refresh_chat_list()

    # -- reply -----------------------------------------------------------------

    def reply_selected(self) -> None:
        view = self.query_one(ChatView)
        message = view.selected_message()
        if message is None:
            return
        self.pending_reply = (message.chat_id, message.id)
        composer = self.query_one(Composer)
        first = message.text.splitlines()[0] if message.text else "attachment"
        composer.border_title = (
            f"↱ {self.engine.sender_name(message.sender_id)}: {first[:48]}"
        )
        composer.focus()

    # -- reactions -------------------------------------------------------------

    async def react_to_selected(self, emoji: str) -> None:
        view = self.query_one(ChatView)
        message = view.selected_message()
        if message is None:
            return
        try:
            await self.engine.add_reaction(message.chat_id, message.id, emoji)
        except Exception as exc:  # noqa: BLE001 - RPC errors surface as a toast
            self.notify(f"Failed to add reaction: {exc}", severity="error")
            return
        view.refresh_reactions(message.id)

    def clear_pending_reply(self) -> None:
        self.pending_reply = None
        self.query_one(Composer).border_title = ""

    # -- media -------------------------------------------------------------------

    async def play_selected_voice(self) -> None:
        view = self.query_one(ChatView)
        message = view.selected_message()
        if message is None or not message.has_voice:
            self.notify("No voice message on selected message (key: v)", severity="warning")
            return
        try:
            path = await self.engine.fetch_voice(message)
        except Exception as exc:
            self.notify(f"Failed to get audio: {exc}", severity="error")
            return
        if path is None:
            self.notify("Voice message unavailable", severity="error")
            return
        try:
            self.voice_player.play(path)
        except Exception as exc:  # noqa: BLE001 - MediaPlayerNotFound, OSError
            self.notify(str(exc), severity="error")
            return
        self.notify(f"▶ Playing {path.name} (mpv in background)")

    def action_stop_voice(self) -> None:
        self.voice_player.stop()

    async def open_selected_media(self) -> None:
        view = self.query_one(ChatView)
        message = view.selected_message()
        if message is None:
            return

        from .media import open_external_media

        if message.has_photo:
            try:
                path = await self.engine.fetch_photo(message)
            except Exception as exc:
                self.notify(f"Failed to load photo: {exc}", severity="error")
                return
            if path and path.exists():
                open_external_media(path)
                self.notify(f"🖼 Opening {path.name} in external viewer")
            else:
                self.notify("Photo unavailable", severity="error")
            return

        if message.media_type in ("video_note", "video", "document"):
            try:
                path = await self.engine.fetch_voice(message)
            except Exception as exc:
                self.notify(f"Failed to load media: {exc}", severity="error")
                return
            if path and path.exists():
                open_external_media(path)
                self.notify(f"⭕ Opening {path.name} in video player")
            else:
                self.notify("Media file unavailable", severity="error")
            return

        if message.has_voice or message.media_type == "voice":
            await self.play_selected_voice()
            return

        self.notify("No media files to open on selected message (key: o)", severity="warning")

    def action_open_media(self) -> None:
        self.run_worker(self.open_selected_media())

    def on_unmount(self) -> None:
        self.voice_player.stop()

    # -- chat actions ---------------------------------------------------------

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
        if self.engine.is_mock:
            self._ingest(self.engine.inject_incoming())
