"""Center panel: scrollable message history with code highlighting and replies.

Vim-style navigation: j/k moves the selection, G/g g jump to the end/start,
'r' replies to the selected message, 'v' plays its voice, '/' searches.
"""

from __future__ import annotations

import datetime as dt
import re

from rich.markup import escape
from rich.syntax import Syntax as RichSyntax
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from ..models import Chat, Message
from .photo import PhotoWidget

_FENCE_RE = re.compile(r"```(\w*)\n(.*?)```", re.DOTALL)

#: Media that gets a one-line "what is this" row rather than bespoke rendering.
_SUMMARISED_MEDIA = frozenset(
    {"video", "gif", "audio", "document", "contact", "geo", "poll"}
)
#: Media Telegram stores a poster frame for, which we can draw in the feed.
_THUMBNAILED_MEDIA = frozenset({"video", "gif", "video_note"})
#: ... and the subset an external viewer can actually open.
_OPENABLE_MEDIA = frozenset({"video", "gif", "audio", "document"})

#: Number keys that post a reaction to the selected message.
QUICK_REACTIONS = {"1": "👍", "2": "❤️", "3": "🔥", "4": "🎉", "5": "🤔"}

_SENDER_STYLES = [
    "bold cyan",
    "bold green",
    "bold yellow",
    "bold magenta",
    "bold blue",
    "bold red",
    "bold orange3",
    "bold violet",
]


def sender_style(sender_id: int | None) -> str:
    if sender_id is None:
        return "bold white"
    return _SENDER_STYLES[abs(sender_id) % len(_SENDER_STYLES)]


def _time_label(ts: dt.datetime | None) -> str:
    if ts is None:
        return ""
    return ts.astimezone().strftime("%H:%M")


class CodeBlock(Static):
    """Code snippet with syntax highlighting (rich/pygments), re-wrapped on resize."""

    DEFAULT_CSS = """
    CodeBlock {
        width: 1fr;
        background: $panel;
        border: round $secondary 20%;
        padding: 0 1;
        margin: 0 0 0 0;
    }
    """

    def __init__(self, code: str, lang: str) -> None:
        super().__init__(markup=False, expand=True)
        self._code = code
        self._lang = lang

    def render(self) -> RichSyntax:
        return RichSyntax(
            self._code,
            lexer=self._lang or "text",
            theme="monokai",
            word_wrap=True,
            padding=(0, 0),
        )


class MessageWidget(Vertical):
    """A single message: header, optional reply quote, text, code, media."""

    DEFAULT_CSS = """
    MessageWidget { height: auto; margin: 0 1 1 0; }
    MessageWidget.-selected { background: $boost; }
    MessageWidget.-selected Static.msg-header { text-style: bold; }
    MessageWidget.-hit { background: $warning 15%; }
    MessageWidget.-miss { opacity: 0.35; }
    /* An image id travels in the foreground colour; dimming would rewrite it. */
    MessageWidget.-miss PhotoWidget { opacity: 1; }
    MessageWidget .msg-reply {
        border-left: thick $accent;
        padding-left: 1;
        text-style: italic;
    }
    MessageWidget .msg-voice { color: #ff9e64; text-style: italic; }
    MessageWidget .msg-video { color: #7aa2f7; text-style: italic; }
    MessageWidget .msg-sticker { color: #bb9af7; }
    MessageWidget .msg-file { color: #7aa2f7; }
    MessageWidget .msg-reactions { margin-top: 1; }
    MessageWidget CodeBlock { margin: 0; }
    .load-older {
        width: 1fr;
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        background: #24283b;
        color: #b7e680;
        text-align: center;
        text-style: bold;
    }
    .load-older:hover {
        background: #3b4261;
    }
    """

    def __init__(
        self,
        message: Message,
        sender_name: str,
        reply_to: Message | None = None,
        reply_to_name: str | None = None,
    ) -> None:
        super().__init__(classes="message")
        self.message = message
        self._sender_name = sender_name
        self._reply_to = reply_to
        self._reply_to_name = reply_to_name or ""

    def compose(self) -> ComposeResult:
        sender_id = self.message.sender_id
        sender_name = self._sender_name or "Unknown"
        time_str = _time_label(self.message.timestamp)
        yield Static(
            f"[{sender_style(sender_id)}]"
            f"{escape(sender_name)}[/] [dim]{time_str}[/]",
            classes="msg-header",
        )

        if self._reply_to is not None:
            first = self._reply_to.text.splitlines()[0] if self._reply_to.text else "…"
            if len(first) > 60:
                first = first[:57] + "…"
            quote = Text()
            quote.append("↱ ", style="dim")
            reply_sender_id = self._reply_to.sender_id if self._reply_to else None
            quote.append(self._reply_to_name or "Unknown", style=sender_style(reply_sender_id))
            quote.append(f": {first}", style="dim")
            yield Static(quote, classes="msg-reply", markup=False)

        if self.message.has_voice or self.message.media_type == "voice":
            from ..media import format_waveform

            dur = f" ({self.message.duration}s)" if self.message.duration else ""
            wave = format_waveform(self.message.waveform, width=18)
            yield Static(
                f"🎙 [bold #ff9e64]voice{dur}[/]  [bold #7aa2f7]{wave}[/]  [dim]v: play, o: open[/]",
                classes="msg-voice",
                markup=True,
            )

        if self.message.media_type == "video_note":
            dur = f" ({self.message.duration}s)" if self.message.duration else ""
            yield Static(
                f"⭕ [bold #7aa2f7]video note{dur}[/]  [dim]o / v: open in mpv (PIP)[/]",
                classes="msg-video",
                markup=True,
            )

        if self.message.media_type == "sticker" or self.message.sticker_emoji:
            emoji = self.message.sticker_emoji or "🎭"
            yield Static(f"🎭 [bold #bb9af7]sticker:[/] {emoji}", classes="msg-sticker", markup=True)

        elif self.message.media_type in _SUMMARISED_MEDIA:
            # media_summary() already leads with the icon for this media type.
            summary = escape(self.message.media_summary())
            hint = "  [dim]o: open[/]" if self.message.media_type in _OPENABLE_MEDIA else ""
            yield Static(
                f"[bold #7aa2f7]{summary}[/]{hint}",
                classes="msg-file",
                markup=True,
            )

        for part in self._split_text(self.message.text):
            if part["kind"] == "code":
                yield CodeBlock(part["text"].rstrip("\n"), part["lang"])
            else:
                yield Static(Text(part["text"]), markup=False)

        if self.message.has_photo or self.message.media_type == "photo":
            yield PhotoWidget(self.message, self.app.engine)
        elif self.message.media_type in _THUMBNAILED_MEDIA:
            yield PhotoWidget(self.message, self.app.engine, thumbnail=True)

        # Always mounted, hidden while empty, so a reaction added later can be
        # rendered in place instead of rebuilding the whole message.
        text = self._reactions_text()
        self._reaction_row = Static(text or Text(), classes="msg-reactions")
        self._reaction_row.display = text is not None
        yield self._reaction_row

    def _reactions_text(self) -> Text | None:
        """Reaction badges, or None when the message has none worth drawing."""
        r_text = Text()
        for item in self.message.reactions:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                emoji, count = item
                emoji = str(emoji) if emoji is not None else "👍"
                try:
                    count = int(count) if count is not None else 1
                except (ValueError, TypeError):
                    count = 1
                r_text.append(f" {emoji} {count} ", style="bold #111413 on #7aa2f7")
                r_text.append(" ")
        return r_text if len(r_text) > 0 else None

    def refresh_reactions(self) -> None:
        """Redraw the reaction row after the backend recorded a new reaction."""
        row = getattr(self, "_reaction_row", None)
        if row is None:
            return
        text = self._reactions_text()
        row.update(text or Text())
        row.display = text is not None

    def set_selected(self, selected: bool) -> None:
        self.set_class(selected, "-selected")

    @staticmethod
    def _split_text(text: str | None) -> list[dict]:
        parts: list[dict] = []
        if not text:
            return parts
        pos = 0
        for match in _FENCE_RE.finditer(text):
            before = text[pos : match.start()]
            if before.strip():
                parts.append({"kind": "text", "text": before})
            parts.append({"kind": "code", "lang": match.group(1), "text": match.group(2)})
            pos = match.end()
        tail = text[pos:]
        if tail.strip():
            parts.append({"kind": "text", "text": tail})
        return parts


class ChatView(VerticalScroll):
    """Scrollable history of the currently open chat, with vim navigation."""

    can_focus = True

    BINDINGS = [
        Binding("j", "sel_next", "↓ msg", show=False),
        Binding("k", "sel_prev", "↑ msg", show=False),
        Binding("G", "sel_last", "Last", show=False),
        Binding("g,g", "sel_first", "First", show=False),
        Binding("r", "app_reply", "Reply"),
        Binding("v", "app_voice", "Play voice"),
        Binding("s", "app.stop_voice", "Stop audio", show=False),
        Binding("o", "app_open_media", "Open media"),
        Binding("z", "toggle_photo", "Zoom photo", show=False),
        Binding("/", "app_find", "Find in chat"),
        Binding("ctrl+o", "load_older", "Load history", priority=True),
        Binding("n", "next_hit", show=False),
        Binding("N", "prev_hit", show=False),
        *[
            Binding(key, f"react('{emoji}')", f"React {emoji}", show=False)
            for key, emoji in QUICK_REACTIONS.items()
        ],
    ]

    DEFAULT_CSS = """
    ChatView { height: 1fr; padding: 0 1; background: #1a1b26; }
    """

    def __init__(self, engine) -> None:  # noqa: ANN001 - avoids circular import
        super().__init__(id="messages")
        self.engine = engine
        self.chat_id: int | None = None
        self._selected: int = -1
        self.hits: list[MessageWidget] = []
        self.hit_index: int = -1

    # -- content ---------------------------------------------------------------

    def show_chat(self, chat: Chat) -> None:
        self.chat_id = chat.id
        self.remove_children()
        self.hits = []
        self.hit_index = -1
        self.mount(Static("⬆ Load older messages (Ctrl+O)", classes="load-older"))
        for message in self.engine.history(chat.id):
            self.mount(self._make_message_widget(message))
        # Freshly mounted widgets have no height until the next refresh, so
        # scrolling right now would measure a stale layout and land at the top.
        self.call_after_refresh(self._jump_to_latest)

    def _jump_to_latest(self) -> None:
        """Select the newest message and pin the viewport to the bottom."""
        self.select(len(self._widgets()) - 1)
        self.scroll_end(animate=False, force=True)

    async def action_load_older(self) -> None:
        if not self.chat_id:
            return
        widgets = self._widgets()
        if not widgets:
            return
        oldest_id = widgets[0].message.id
        try:
            older = await self.engine.fetch_more_history(self.chat_id, offset_id=oldest_id)
        except Exception as exc:
            self.app.notify(f"Failed to load history: {exc}", severity="error")
            return
        if older:
            banners = self.query(".load-older")
            banner = banners.first() if banners else None
            for m in reversed(older):
                w = self._make_message_widget(m)
                if banner:
                    self.mount(w, after=banner)
                else:
                    self.mount(w)
            self.app.notify(f"Loaded {len(older)} older messages", timeout=2)
        else:
            self.app.notify("You have reached the beginning of chat history", timeout=2)

    def append_message(self, message: Message, scroll: bool = True) -> MessageWidget:
        """Add a message to the feed, following it only if the user is already
        at the bottom — someone reading scrollback should not be yanked away."""
        at_bottom = self.scroll_offset.y >= self.max_scroll_y - 1
        widget = self._make_message_widget(message)
        self.mount(widget)
        if scroll and at_bottom:
            self.call_after_refresh(self._jump_to_latest)
        return widget

    def _make_message_widget(self, message: Message) -> MessageWidget:
        reply_to = (
            self.engine.get_message(message.chat_id, message.reply_to)
            if message.reply_to
            else None
        )
        return MessageWidget(
            message,
            sender_name=self.engine.sender_name(message.sender_id),
            reply_to=reply_to,
            reply_to_name=self.engine.sender_name(reply_to.sender_id) if reply_to else None,
        )

    def _widgets(self) -> list[MessageWidget]:
        return [w for w in self.children if isinstance(w, MessageWidget)]

    # -- selection -----------------------------------------------------------

    def select(self, index: int) -> None:
        widgets = self._widgets()
        if not widgets:
            self._selected = -1
            return
        index = max(0, min(index, len(widgets) - 1))
        for i, w in enumerate(widgets):
            w.set_selected(i == index)
        self._selected = index
        self.scroll_to_widget(widgets[index], animate=False)

    def action_sel_next(self) -> None:
        self.select(self._selected + 1)

    def action_sel_prev(self) -> None:
        self.select(self._selected - 1)

    def action_sel_last(self) -> None:
        self.select(len(self._widgets()) - 1)

    def action_sel_first(self) -> None:
        self.select(0)

    def selected_message(self) -> Message | None:
        widgets = self._widgets()
        if 0 <= self._selected < len(widgets):
            return widgets[self._selected].message
        return None

    def action_app_reply(self) -> None:
        self.app.reply_selected()

    async def action_app_voice(self) -> None:
        await self.app.play_selected_voice()

    async def action_app_open_media(self) -> None:
        await self.app.open_selected_media()

    def action_toggle_photo(self) -> None:
        """Expand or collapse the preview on the selected message."""
        widgets = self._widgets()
        if not 0 <= self._selected < len(widgets):
            return
        photos = widgets[self._selected].query(PhotoWidget)
        if photos:
            photos.first().toggle_expanded()

    async def action_react(self, emoji: str) -> None:
        await self.app.react_to_selected(emoji)

    def refresh_reactions(self, message_id: int) -> None:
        for widget in self._widgets():
            if widget.message.id == message_id:
                widget.refresh_reactions()
                return

    def action_app_find(self) -> None:
        self.app.action_search_in_chat()

    # -- in-chat search --------------------------------------------------------

    def update_hits(self, query: str) -> None:
        self.hits = []
        self.hit_index = -1
        q = query.strip().lower()
        for widget in self._widgets():
            widget.remove_class("-hit")
            widget.remove_class("-miss")
            if not q:
                continue
            if q in (widget.message.text or "").lower():
                widget.add_class("-hit")
                self.hits.append(widget)
            else:
                widget.add_class("-miss")
        if self.hits:
            self._scroll_to_hit(0)

    def _scroll_to_hit(self, index: int) -> None:
        self.hit_index = index % len(self.hits)
        self.scroll_to_widget(self.hits[self.hit_index], animate=False, center=True)

    def action_next_hit(self) -> None:
        if self.hits:
            self._scroll_to_hit((self.hit_index + 1) % len(self.hits))

    def action_prev_hit(self) -> None:
        if self.hits:
            self._scroll_to_hit((self.hit_index - 1) % len(self.hits))
