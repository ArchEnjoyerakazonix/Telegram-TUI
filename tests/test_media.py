"""Tests for media support: mpv voice playback and chafa photo rendering."""

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
    assert media.detect_photo_format({"KITTY_WINDOW_ID": "1"}) == ["--format", "kitty"]
    assert media.detect_photo_format({"TERM": "xterm-kitty"}) == ["--format", "kitty"]
    assert media.detect_photo_format({"TERM": "alacritty"}) == ["--format", "symbols"]


def test_render_photo_chafa_failure_returns_none(monkeypatch, tmp_path):
    img = write_mock_photo(tmp_path / "x.png")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(media.shutil, "which", lambda name: "/usr/bin/chafa")
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    assert render_photo(img) is None
