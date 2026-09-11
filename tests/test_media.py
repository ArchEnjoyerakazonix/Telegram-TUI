"""Tests for media support: mpv voice playback and chafa photo rendering."""

import re
import shutil
import subprocess
import wave

import pytest

from telegram_tui import media
from telegram_tui.media import (
    MediaPlayerNotFound,
    VoicePlayer,
    render_photo,
    write_mock_photo,
    write_mock_voice,
)
from telegram_tui.widgets.photo import (
    COMPACT_COLS,
    COMPACT_ROWS,
    EXPANDED_COLS,
    EXPANDED_ROWS,
)


# -- mock media files --------------------------------------------------------


def test_mock_voice_is_valid_wav(tmp_path):
    path = write_mock_voice(tmp_path / "v.wav")
    with wave.open(str(path)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 8000
        assert wav.getnframes() > 8000  # at least a second of audio


def test_mock_photo_is_valid_png(tmp_path):
    path = write_mock_photo(tmp_path / "p.png")
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data.endswith(b"IEND\xaeB`\x82") or b"IDAT" in data


# -- voice player --------------------------------------------------------------


def test_player_missing_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    player = VoicePlayer("definitely-not-installed")
    with pytest.raises(MediaPlayerNotFound):
        player.play(tmp_path / "any.wav")


def test_player_spawns_background_process(monkeypatch, tmp_path):
    spawned = {}

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            spawned["cmd"] = cmd
            spawned["kwargs"] = kwargs
            self._pid = 1234

        def poll(self):
            return 0  # exited

        def terminate(self):
            spawned["terminated"] = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr(media.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(media.subprocess, "Popen", FakeProc)

    player = VoicePlayer("mpv")
    player.play(tmp_path / "voice.wav")
    assert spawned["cmd"][:2] == ["mpv", "--no-video"]
    assert spawned["cmd"][-1].endswith("voice.wav")
    assert spawned["kwargs"]["stdout"] == subprocess.DEVNULL
    assert player.playing is False  # FakeProc already "exited"

    player.stop()
    assert player._proc is None


def test_player_stop_terminates_running(monkeypatch, tmp_path):
    terminated = []

    class RunningProc:
        def poll(self):
            return None  # still running

        def terminate(self):
            terminated.append(True)

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(media.shutil, "which", lambda name: "/usr/bin/mpv")
    monkeypatch.setattr(media.subprocess, "Popen", lambda cmd, **kw: RunningProc())
    player = VoicePlayer("mpv")
    player.play(tmp_path / "v.wav")
    assert player.playing is True
    player.stop()
    assert terminated == [True]


# -- photo rendering -------------------------------------------------------------


def test_render_photo_without_chafa_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    assert render_photo(tmp_path / "x.png") is None


def test_render_photo_invokes_chafa(monkeypatch, tmp_path):
    img = write_mock_photo(tmp_path / "x.png")
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0, stdout="██▓▒".encode(), stderr=b""
        )

    monkeypatch.setattr(media.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    out = render_photo(img, cols=40, rows=20)
    assert out is not None and "██" in out
    assert "chafa" in calls["cmd"][0]
    assert "-s" in calls["cmd"] and "40x20" in calls["cmd"]


def test_photo_format_detection(monkeypatch=None):
    assert media.detect_photo_format({"KITTY_WINDOW_ID": "1"}) == ["--format", "symbols"]
    assert media.detect_photo_format({"TERM": "xterm-kitty"}) == ["--format", "symbols"]
    assert media.detect_photo_format({"TERM": "alacritty"}) == ["--format", "symbols"]


def test_render_photo_chafa_failure_returns_none(monkeypatch, tmp_path):
    img = write_mock_photo(tmp_path / "x.png")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(media.shutil, "which", lambda name: "/usr/bin/chafa")
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    assert render_photo(img) is None


# -- preview geometry --------------------------------------------------------

needs_chafa = pytest.mark.skipif(
    shutil.which("chafa") is None, reason="chafa is not installed"
)

_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def rendered_size(path, cols, rows):
    """Actual (columns, rows) chafa produced for a box."""
    output = render_photo(path, cols, rows)
    assert output is not None
    lines = output.rstrip("\n").split("\n")
    return max(len(_ESCAPES.sub("", line)) for line in lines), len(lines)


@needs_chafa
def test_compact_preview_keeps_a_portrait_photo_legible(tmp_path):
    """Chafa fits inside the box, so a short box crushes tall photos.

    A 64x10 compact box rendered a 720x1280 photo twelve columns wide — a
    sliver you could not make anything out in.
    """
    portrait = write_mock_photo(tmp_path / "portrait.png", 720, 1280)

    width, _height = rendered_size(portrait, COMPACT_COLS, COMPACT_ROWS)

    assert width >= 18, "a portrait preview must be wide enough to read"


@needs_chafa
def test_previews_stay_inside_the_box_they_are_given(tmp_path):
    for name, (w, h) in {
        "portrait.png": (720, 1280),
        "landscape.png": (1280, 720),
        "square.png": (800, 800),
    }.items():
        image = write_mock_photo(tmp_path / name, w, h)
        for cols, rows in ((COMPACT_COLS, COMPACT_ROWS), (EXPANDED_COLS, EXPANDED_ROWS)):
            width, height = rendered_size(image, cols, rows)
            assert width <= cols, f"{name} overflowed {cols} columns"
            assert height <= rows + 1, f"{name} overflowed {rows} rows"


@needs_chafa
def test_expanding_makes_a_photo_bigger_in_both_directions(tmp_path):
    portrait = write_mock_photo(tmp_path / "portrait.png", 720, 1280)

    compact = rendered_size(portrait, COMPACT_COLS, COMPACT_ROWS)
    expanded = rendered_size(portrait, EXPANDED_COLS, EXPANDED_ROWS)

    assert expanded[0] > compact[0] and expanded[1] > compact[1]
