"""Terminal media support: voice playback via mpv, photo previews via chafa.

Voice: spawns the configured player (mpv by default) in the background.
Photos: renders a preview to ANSI/sixel/kitty glyphs using chafa when
available; the output format follows the terminal ($TERM / KITTY_WINDOW_ID).
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import wave
import zlib
from pathlib import Path


class MediaPlayerNotFound(RuntimeError):
    pass


class VoicePlayer:
    """Background process wrapper around mpv (or any compatible CLI player)."""

    def __init__(self, player_cmd: str = "mpv") -> None:
        self.player_cmd = player_cmd
        self._proc: subprocess.Popen | None = None

    def play(self, path: Path) -> None:
        self.stop()
        if shutil.which(self.player_cmd) is None:
            raise MediaPlayerNotFound(
                f"проигрыватель '{self.player_cmd}' не найден в PATH"
            )
        self._proc = subprocess.Popen(
            [self.player_cmd, "--no-video", "--really-quiet", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    @property
    def playing(self) -> bool:
        return self._proc is not None and self._proc.poll() is None


def detect_photo_format(environ: dict | None = None) -> list[str]:
    """chafa output flags matching the current terminal's graphics support."""
    import os

    env = os.environ if environ is None else environ
    if env.get("KITTY_WINDOW_ID") or "kitty" in env.get("TERM", ""):
        return ["--format", "kitty"]
    return ["--format", "symbols"]


def render_photo(
    path: Path,
    cols: int = 48,
    rows: int = 24,
    renderer: str = "chafa",
    environ: dict | None = None,
) -> str | None:
    """Render an image file as terminal output; None if no renderer."""
    binary = shutil.which(renderer)
    if binary is None:
        return None
    cmd = [binary, "-s", f"{cols}x{rows}", *detect_photo_format(environ), str(path)]
    result = subprocess.run(
        cmd, capture_output=True, timeout=30, check=False
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode(errors="replace")


# -- mock media files (so media works out of the box in mock mode) ------------


def write_mock_voice(path: Path, seconds: float = 1.2, freq: float = 440.0) -> Path:
    """A short sine-wave WAV so mpv has something to actually play."""
    rate = 8000
    frames = bytearray()
    for i in range(int(rate * seconds)):
        envelope = min(1.0, (rate * seconds - i) / (rate * 0.1))
        sample = int(12000 * envelope * math.sin(2 * math.pi * freq * i / rate))
        frames += struct.pack("<h", sample)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(bytes(frames))
    return path


def write_mock_photo(path: Path, width: int = 64, height: int = 40) -> Path:
    """A tiny valid PNG with a color gradient, written without Pillow."""
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: none
        for x in range(width):
            raw += bytes((int(255 * x / width), int(255 * y / height), 160))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    return path
