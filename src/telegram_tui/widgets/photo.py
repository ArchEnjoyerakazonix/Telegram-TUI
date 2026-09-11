"""Photo preview widget: renders an image inline via chafa (ANSI/kitty/sixel)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from ..media import render_photo
from ..models import Message


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

    def on_mount(self) -> None:
        self.run_worker(self._load(), exit_on_error=False, group="photo")

    def _preview_box(self) -> tuple[int, int]:
        """Cell box handed to chafa.

        The height is capped at half the visible feed: a preview is a preview,
        and an uncapped one pushes the whole conversation off the screen.
        """
        cols = max(24, min(64, self.app.size.width - 48))
        feed = self.screen.query("#messages")
        feed_height = feed.first().size.height if feed else self.app.size.height
        rows = max(8, min(int(cols * 0.5), feed_height // 2))
        return cols, rows

    async def _load(self) -> None:
        try:
            path = await self._backend.fetch_photo(self._message)
        except Exception as exc:  # noqa: BLE001
            self.update(f"🖼 photo unavailable ({exc})")
            return
        if path is None:
            self.update("🖼 photo")
            return
        cols, rows = self._preview_box()
        loop = asyncio.get_running_loop()
        ansi = await loop.run_in_executor(
            None,
            render_photo,
            Path(path),
            cols,
            rows,
            self.app.config.photo_renderer,
        )
        if ansi is None:
            self.update(
                f"🖼 photo saved: {Path(path).name} "
                f"(install '{self.app.config.photo_renderer}' for terminal preview)"
            )
            return
        self.update(Text.from_ansi(ansi.rstrip("\n")))
