"""True-pixel image rendering through kitty's graphics protocol.

Textual composites the screen itself, so a widget cannot simply emit the escape
sequence that carries an image — it would be written as text. Kitty provides
Unicode placeholders for exactly this case: the image is transmitted once, out
of band, and the widget then renders ordinary characters (U+10EEEE) whose
foreground colour names the image and whose combining diacritics name the cell's
row and column. Kitty replaces those cells with the picture as it paints.

Everything here degrades to "not supported" rather than raising, so the chafa
renderer stays the fallback on any other terminal.
"""

from __future__ import annotations

import base64
import os
import random
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path

from rich.style import Style
from rich.text import Text

from .kitty_diacritics import ROWCOLUMN_DIACRITICS

#: The character kitty replaces with image data.
PLACEHOLDER = "\U0010eeee"

#: Image ids are carried in the foreground colour, so they must fit in 24 bits
#: and avoid 0 (which kitty reads as "no id"). We keep well clear of both ends.
_FIRST_ID = 0x010101
_LAST_ID = 0xFEFEFE

#: Terminals that implement the protocol's Unicode placeholder support.
_SUPPORTING_TERMINALS = ("xterm-kitty", "kitty")


def is_supported(environ: dict | None = None) -> bool:
    """Whether the terminal we are attached to can draw real images."""
    env = os.environ if environ is None else environ
    if env.get("TELEGRAM_TUI_NO_KITTY"):
        return False
    if env.get("KITTY_WINDOW_ID"):
        return True
    term = env.get("TERM", "").lower()
    return any(name in term for name in _SUPPORTING_TERMINALS)


def _apc(payload: str) -> str:
    """Wrap a graphics command in the APC sequence kitty listens for."""
    return f"\033_G{payload}\033\\"


def transmit(path: Path | str, image_id: int, cols: int, rows: int) -> str:
    """Escape sequence that hands kitty the file and reserves a placement.

    ``q=2`` silences kitty's replies. Without it the terminal answers into the
    input stream, and the answer is typed into whatever widget has focus.
    """
    encoded = base64.standard_b64encode(str(path).encode("utf-8")).decode("ascii")
    # t=f: the payload is a path; f=100: the file is a PNG.
    send = _apc(f"a=t,t=f,f=100,i={image_id},q=2;{encoded}")
    # a=p with U=1 creates the virtual placement the placeholders refer to.
    place = _apc(f"a=p,U=1,i={image_id},c={cols},r={rows},q=2")
    return send + place


def delete(image_id: int) -> str:
    """Escape sequence that frees an image kitty is still holding."""
    return _apc(f"a=d,d=I,i={image_id},q=2")


def _diacritic(index: int) -> str:
    return chr(ROWCOLUMN_DIACRITICS[index])


def placeholder_text(image_id: int, cols: int, rows: int) -> Text:
    """The grid of placeholder cells that kitty paints the image over.

    The id is split across the foreground colour (low 24 bits) exactly as the
    protocol expects, and every cell spells out its own row and column so a
    reflow or a partially covered widget cannot smear the picture.
    """
    if cols <= 0 or rows <= 0:
        return Text()
    cols = min(cols, len(ROWCOLUMN_DIACRITICS))
    rows = min(rows, len(ROWCOLUMN_DIACRITICS))
    style = Style(color=f"#{image_id:06x}")

    text = Text()
    for row in range(rows):
        if row:
            text.append("\n")
        row_mark = _diacritic(row)
        for col in range(cols):
            text.append(PLACEHOLDER + row_mark + _diacritic(col), style=style)
    return text


def png_size(path: Path | str) -> tuple[int, int] | None:
    """Pixel size straight out of a PNG header, so no decoder is needed."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return (width, height) if width and height else None


def fit_cells(size: tuple[int, int] | None, max_cols: int, max_rows: int) -> tuple[int, int]:
    """Cell box that keeps the picture's proportions.

    A terminal cell is roughly twice as tall as it is wide, which is why an
    image spanning N columns needs about N/2 rows to stay square.
    """
    max_cols, max_rows = max(1, max_cols), max(1, max_rows)
    if not size:
        return max_cols, max_rows
    width, height = size
    cols = max_cols
    rows = max(1, round(cols * height / width / 2))
    if rows > max_rows:
        rows = max_rows
        cols = max(1, min(max_cols, round(rows * 2 * width / height)))
    return cols, rows


def as_png(source: Path | str, target: Path) -> Path | None:
    """A PNG copy of the image, since kitty only takes PNG or raw pixels.

    Telegram sends photos as JPEG. Conversion needs an outside tool; when there
    is none the caller falls back to the character renderer.
    """
    source = Path(source)
    if source.suffix.lower() == ".png":
        return source
    if target.exists() and target.stat().st_size > 0:
        return target
    for converter in ("magick", "convert", "ffmpeg"):
        binary = shutil.which(converter)
        if binary is None:
            continue
        cmd = (
            [binary, "-loglevel", "quiet", "-i", str(source), "-y", str(target)]
            if converter == "ffmpeg"
            else [binary, str(source), str(target)]
        )
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=20,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if result.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return target
    return None


class ImageIds:
    """Hands out image ids and remembers which are still on the terminal.

    Ids are shared by everything drawing in this terminal window, so the run
    starts at a random point rather than at 1: another program's images would
    otherwise be overwritten by ours, and ours by theirs.
    """

    def __init__(self, start: int | None = None) -> None:
        self._next = start if start is not None else random.randint(_FIRST_ID, _LAST_ID)
        self.live: set[int] = set()

    def allocate(self) -> int:
        image_id = self._next
        self._next = _FIRST_ID if image_id >= _LAST_ID else image_id + 1
        self.live.add(image_id)
        return image_id

    def release(self, image_id: int) -> None:
        self.live.discard(image_id)


class ImageCache:
    """Keeps transmitted images on the terminal so a remount costs nothing.

    Reopening a chat rebuilds its message widgets, and re-sending every photo
    makes the terminal decode them all again. Images stay until the cache is
    full, then the least recently used are dropped.
    """

    def __init__(self, limit: int = 64) -> None:
        self._limit = limit
        self._ids = ImageIds()
        self._entries: OrderedDict[tuple[str, int, int], int] = OrderedDict()

    @property
    def live(self) -> set[int]:
        return self._ids.live

    def get(self, path: Path | str, cols: int, rows: int) -> tuple[int, str]:
        """The id for this image at this size, and what still has to be sent."""
        key = (str(path), cols, rows)
        cached = self._entries.get(key)
        if cached is not None:
            self._entries.move_to_end(key)
            return cached, ""

        image_id = self._ids.allocate()
        self._entries[key] = image_id
        payload = transmit(path, image_id, cols, rows)
        while len(self._entries) > self._limit:
            _, evicted = self._entries.popitem(last=False)
            payload += delete(evicted)
            self._ids.release(evicted)
        return image_id, payload

    def clear(self) -> str:
        """Everything needed to hand the terminal's memory back."""
        payload = "".join(delete(image_id) for image_id in self._entries.values())
        for image_id in self._entries.values():
            self._ids.release(image_id)
        self._entries.clear()
        return payload


#: Ids and images are terminal-wide resources, managed in one place.
IMAGES = ImageCache()


def write_to_terminal(payload: str) -> bool:
    """Send a graphics command straight to the terminal, around Textual.

    The compositor would render the sequence as text, so it has to bypass it.
    None of these commands move the cursor or paint anything, so writing while
    Textual owns the screen is safe.
    """
    if not payload:
        return False
    try:
        with open("/dev/tty", "w", encoding="utf-8") as tty:
            tty.write(payload)
            tty.flush()
        return True
    except OSError:
        return False
