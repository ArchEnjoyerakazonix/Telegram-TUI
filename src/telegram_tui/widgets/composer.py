"""Bottom panel: multiline message composer with hotkeys."""

from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import TextArea


class Composer(TextArea):
    """Multiline input: Enter sends, Alt+Enter inserts a newline."""

    BINDINGS = [
        Binding("enter", "send", "Send", priority=True, show=True),
        Binding("alt+enter", "insert_newline", "Newline"),
        Binding("ctrl+g", "toggle_grow", "Grow/shrink"),
        Binding("escape", "app.back_to_list", "Chats", show=False),
    ]

    class Sent(Message):
        """Posted when the user submits the text."""

        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    def action_send(self) -> None:
        text = self.text.strip()
        if not text:
            return
        self.post_message(self.Sent(text))
        self.load_text("")
        self.cursor_location = (0, 0)

    def action_insert_newline(self) -> None:
        self.insert("\n")

    def action_toggle_grow(self) -> None:
        styles = self.styles
        styles.height = 12 if (styles.height.value or 0) <= 6 else 5
