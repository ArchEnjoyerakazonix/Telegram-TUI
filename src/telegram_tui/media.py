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
    """chafa output flags matching Textual cell renderer."""
    # Textual renders through Rich character cells. Raw Kitty/Sixel graphics
    # protocols escape codes get dumped as base64 text into the widget buffer.
    # Therefore, we always use Unicode symbols (half-blocks) with truecolor.
    return ["--format", "symbols"]


def render_photo(
    path: Path | str,
    cols: int = 48,
    rows: int = 24,
    renderer: str = "chafa",
    environ: dict | None = None,
) -> str | None:
    """Render an image file as terminal output; None if no renderer."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
    except Exception:
        return None

    binary = shutil.which(renderer)
    if binary is None:
        return None
    cmd = [binary, "-s", f"{cols}x{rows}", *detect_photo_format(environ), str(p)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, timeout=30, check=False
        )
        if result.returncode != 0:
            return None
        return result.stdout.decode(errors="replace")
    except (subprocess.SubprocessError, OSError):
        return None


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


WAVEFORM_BLOCKS = " ▂▃▄▅▆▇█"


def decode_telegram_waveform(raw_bytes: bytes, target_len: int = 24) -> list[int]:
    """Decode Telegram 5-bit packed waveform samples into integer amplitudes (0-31)."""
    if not raw_bytes or target_len <= 0:
        return []
    total_bits = len(raw_bytes) * 8
    num_samples = total_bits // 5
    if num_samples == 0:
        return []

    samples = []
    for i in range(num_samples):
        bit_idx = i * 5
        byte_idx = bit_idx // 8
        bit_offset = bit_idx % 8
        value = (raw_bytes[byte_idx] >> bit_offset) & 0x1F
        if bit_offset > 3 and byte_idx + 1 < len(raw_bytes):
            spill = (raw_bytes[byte_idx + 1] << (8 - bit_offset)) & 0x1F
            value |= spill
        samples.append(value & 0x1F)

    if len(samples) > target_len:
        step = len(samples) / target_len
        return [samples[int(j * step)] for j in range(target_len)]
    return samples


def format_waveform(waveform: bytes | list[int] | None, width: int = 20) -> str:
    """Format waveform data as Unicode amplitude bar (e.g.  ▂▃▅▇▆▅▃▂ )."""
    if width <= 0:
        return ""
    if isinstance(waveform, (bytes, bytearray)):
        samples = decode_telegram_waveform(bytes(waveform), target_len=width)
    elif isinstance(waveform, list) and waveform:
        cleaned: list[int] = []
        for s in waveform:
            try:
                if s is None:
                    cleaned.append(0)
                else:
                    f = float(s)
                    if math.isnan(f) or math.isinf(f):
                        cleaned.append(0)
                    else:
                        cleaned.append(max(0, int(f)))
            except (ValueError, TypeError):
                cleaned.append(0)
        samples = cleaned
    else:
        # Default rhythmic wave
        samples = [int(15 + 11 * math.sin(i * 0.5) + 5 * math.cos(i * 1.3)) for i in range(width)]

    if not samples:
        return " ▂▃▅▆▇▅▃ "[:width]

    max_val = max(max(samples), 1)
    chars = []
    num_blocks = len(WAVEFORM_BLOCKS)
    for s in samples[:width]:
        idx = min(num_blocks - 1, max(0, int(s / max_val * (num_blocks - 1))))
        chars.append(WAVEFORM_BLOCKS[idx])
    return "".join(chars)


def open_external_media(path: Path | str) -> subprocess.Popen | None:
    """Open media in native desktop viewer (imv, swayimg, feh, mpv, or xdg-open)."""
    try:
        p = Path(path)
        if not p.is_file():
            return None
    except Exception:
        return None

    suffix = p.suffix.lower()
    is_video = suffix in (".mp4", ".mkv", ".webm", ".avi", ".mov")
    is_image = suffix in (".png", ".jpg", ".jpeg", ".webp", ".gif")

    candidates: list[list[str]] = []
    if is_video:
        candidates.append(
            ["mpv", "--autofit=480x480", "--geometry=480x480", "--title=Telegram Video", "--really-quiet", str(p)]
        )
        candidates.append(["xdg-open", str(p)])
    elif is_image:
        for v in ("imv", "swayimg", "feh", "sxiv", "eog"):
            if shutil.which(v):
                candidates.append([v, str(p)])
                break
        candidates.append(["xdg-open", str(p)])
    else:
        candidates.append(["xdg-open", str(p)])

    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                return subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                )
            except (subprocess.SubprocessError, OSError):
                continue
    return None

