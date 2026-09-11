"""Photo preview widget: renders an image inline via chafa (ANSI/kitty/sixel)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from .. import kitty_graphics
from ..media import render_photo
from ..models import Message, format_size

# Chafa fits the image inside the box, so whichever side binds decides the
# result: a portrait photo is limited by rows, a landscape one by columns. A box
# of 64x10 renders a portrait 720x1280 as 12 columns wide — an unreadable
# sliver — so the compact box has to stay reasonably tall to be worth drawing.
COMPACT_COLS, COMPACT_ROWS = 44, 18
EXPANDED_COLS, EXPANDED_ROWS = 72, 34


class PhotoWidget(Static):
    """Shows a placeholder, then swaps in the chafa-rendered preview."""

    DEFAULT_CSS = """
    PhotoWidget {
        width: 1fr;
        height: auto;
        color: $text-muted;
    }
    """

    def __init__(self, message: Message, backend, thumbnail: bool = False) -> None:  # noqa: ANN001
        super().__init__("…", markup=False)
        self._message = message
        self._backend = backend
        #: A video or GIF cannot play in the feed, so show its poster frame.
        self._thumbnail = thumbnail
        self._path: Path | None = None
        self._kitty_id: int | None = None
        self.expanded = False

    def on_mount(self) -> None:
        self.run_worker(self._load(), exit_on_error=False, group="photo")

    def toggle_expanded(self) -> None:
        """Swap between the glanceable preview and a full-height one."""
        self.expanded = not self.expanded
        self.run_worker(self._load(), exit_on_error=False, group="photo")

    def _preview_box(self) -> tuple[int, int]:
        """Cell box handed to chafa, clamped to what the feed can actually show."""
        feed = self.screen.query("#messages")
        if feed:
            available_cols = feed.first().size.width - 4
            available_rows = feed.first().size.height
        else:
            available_cols = self.app.size.width - 8
            available_rows = self.app.size.height

        if self.expanded:
            cols, rows = EXPANDED_COLS, EXPANDED_ROWS
        else:
            cols, rows = COMPACT_COLS, COMPACT_ROWS
        return min(cols, max(20, available_cols)), min(rows, max(6, available_rows))

    async def _render_with_kitty(self, loop, cols: int, rows: int) -> bool:
        """Draw real pixels when the terminal can, instead of block characters."""
        if not kitty_graphics.is_supported():
            return False
        self._release_kitty_image()

        png = await loop.run_in_executor(
            None, kitty_graphics.as_png, self._path, Path(self._path).with_suffix(".png")
        )
        if png is None:
            return False
        size = await loop.run_in_executor(None, kitty_graphics.png_size, png)
        cols, rows = kitty_graphics.fit_cells(size, cols, rows)

        image_id, payload = kitty_graphics.IMAGES.get(png, cols, rows)
        if payload:
            sent = await loop.run_in_executor(
                None, kitty_graphics.write_to_terminal, payload
            )
            if not sent:
                return False
        self._kitty_id = image_id
        self.update(kitty_graphics.placeholder_text(image_id, cols, rows))
        return True

    def _release_kitty_image(self) -> None:
        """Forget our picture without evicting it.

        The cache owns an image's life: reopening a chat remounts every message,
        and dropping the images here would make the terminal decode them all
        again. They are freed when the cache fills or the app exits.
        """
        self._kitty_id = None

    def _caption(self) -> str:
        if self._thumbnail:
            return ""
        size = format_size(self._message.file_size)
        return f"🖼 photo{f' · {size}' if size else ''}"

    async def _load(self) -> None:
        if self._path is None:
            fetch = (
                self._backend.fetch_thumbnail if self._thumbnail else self._backend.fetch_photo
            )
            try:
                self._path = await fetch(self._message)
            except Exception as exc:  # noqa: BLE001
                self.update(f"{self._caption()} — unavailable ({exc})")
                return
        if self._path is None:
            # No poster frame stored; the summary row already says what this is.
            self.display = not self._thumbnail
            self.update(self._caption())
            return

        cols, rows = self._preview_box()
        loop = asyncio.get_running_loop()
        if await self._render_with_kitty(loop, cols, rows):
            return

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
