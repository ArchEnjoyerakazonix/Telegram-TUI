"""Photo preview widget: renders an image inline via chafa (ANSI/kitty/sixel)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from ..media import render_photo
from ..models import Message, format_size

#: Rows a preview gets before the reader asks for more. Kept small so a photo
#: is something you glance at without losing the conversation around it.
COMPACT_ROWS = 10


class PhotoWidget(Static):
    """Shows a placeholder, then swaps in the chafa-rendered preview."""

    DEFAULT_CSS = """
    PhotoWidget {
        width: 1fr;
        height: auto;
        color: $text-muted;
    }
    """

    def __init__(self, message: Message, backend) -> None:  # noqa: ANN001
        super().__init__("🖼 photo — loading…", markup=False)
        self._message = message
        self._backend = backend
        self._path: Path | None = None
        self.expanded = False

    def on_mount(self) -> None:
        self.run_worker(self._load(), exit_on_error=False, group="photo")

    def toggle_expanded(self) -> None:
        """Swap between the glanceable preview and a full-height one."""
        self.expanded = not self.expanded
        self.run_worker(self._load(), exit_on_error=False, group="photo")

    def _preview_box(self) -> tuple[int, int]:
        """Cell box handed to chafa.

        Compact by default; expanded still stops at half the visible feed, since
        an uncapped preview pushes the whole conversation off the screen.
        """
        cols = max(24, min(64, self.app.size.width - 48))
        feed = self.screen.query("#messages")
        feed_height = feed.first().size.height if feed else self.app.size.height
        if self.expanded:
            rows = max(8, min(int(cols * 0.5), feed_height // 2))
        else:
            rows = max(5, min(COMPACT_ROWS, feed_height // 3))
        return cols, rows

    def _caption(self) -> str:
        size = format_size(self._message.file_size)
        return f"🖼 photo{f' · {size}' if size else ''}"

    async def _load(self) -> None:
        if self._path is None:
            try:
                self._path = await self._backend.fetch_photo(self._message)
            except Exception as exc:  # noqa: BLE001
                self.update(f"{self._caption()} — unavailable ({exc})")
                return
        if self._path is None:
            self.update(self._caption())
            return

        cols, rows = self._preview_box()
        loop = asyncio.get_running_loop()
        ansi = await loop.run_in_executor(
            None,
            render_photo,
            Path(self._path),
            cols,
            rows,
            self.app.config.photo_renderer,
        )
        if ansi is None:
            self.update(
                f"{self._caption()} saved: {Path(self._path).name} "
                f"(install '{self.app.config.photo_renderer}' for terminal preview)"
            )
            return
        self.update(Text.from_ansi(ansi.rstrip("\n")))
