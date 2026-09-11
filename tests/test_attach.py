"""Tests for picking a file and sending it as an attachment."""

from __future__ import annotations

from pathlib import Path

import pytest

from telegram_tui.app import TelegramTUI
from telegram_tui.engine import MockEngine
from telegram_tui.widgets.attach import AttachScreen, PathInput, complete_path
from telegram_tui.widgets.composer import Composer

SIZE = (110, 34)


@pytest.fixture
def files(tmp_path):
    (tmp_path / "report.pdf").write_bytes(b"p" * 2201000)
    (tmp_path / "holiday.jpg").write_bytes(b"j" * 491520)
    (tmp_path / "reports").mkdir()
    (tmp_path / ".hidden").write_bytes(b"x")
    return tmp_path


@pytest.fixture
async def app():
    app = TelegramTUI(engine=MockEngine(seed=11), live_traffic=False)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        yield app, pilot


async def open_picker(app, pilot):
    await pilot.press("ctrl+r")
    for _ in range(6):
        await pilot.pause(0.05)
        if isinstance(app.screen, AttachScreen):
            break
    assert isinstance(app.screen, AttachScreen), "the picker did not open"
    return app.screen


# -- path completion --------------------------------------------------------


def test_completion_finishes_a_unique_name(files):
    assert complete_path(f"{files}/hol") == str(files / "holiday.jpg")


def test_completion_stops_at_the_shared_prefix(files):
    # report.pdf and reports/ share "report"
    assert complete_path(f"{files}/rep") == str(files / "report")


def test_completion_marks_a_directory_with_a_separator(files):
    assert complete_path(f"{files}/reports").endswith("/")


def test_completion_leaves_unmatched_text_alone(files):
    assert complete_path(f"{files}/nothing-like-this") == f"{files}/nothing-like-this"


def test_completion_survives_an_unreadable_directory():
    assert complete_path("/definitely/not/here/abc") == "/definitely/not/here/abc"


# -- the mock engine's upload ----------------------------------------------


def test_image_is_sent_as_a_photo(files):
    engine = MockEngine(seed=1)
    chat_id = next(iter(engine.chats))

    msg = engine.send_file(chat_id, files / "holiday.jpg", caption="hi")

    assert msg.media_type == "photo"
    assert msg.has_photo is True
    assert msg.text == "hi"
    assert msg.file_size == 491520


def test_force_document_overrides_the_guess(files):
    engine = MockEngine(seed=1)
    chat_id = next(iter(engine.chats))

    msg = engine.send_file(chat_id, files / "holiday.jpg", force_document=True)

    assert msg.media_type == "document"
    assert engine.chats[chat_id].preview == "holiday.jpg · 480 KB"


def test_upload_progress_is_reported(files):
    engine = MockEngine(seed=1)
    seen = []

    engine.send_file(
        next(iter(engine.chats)), files / "report.pdf", progress=lambda a, b: seen.append((a, b))
    )

    assert seen == [(2201000, 2201000)]


# -- the picker, end to end -------------------------------------------------


async def test_attaching_sends_the_file_with_the_composer_text_as_caption(app, files):
    app, pilot = app
    app.query_one(Composer).load_text("look at this")

    screen = await open_picker(app, pilot)
    field = screen.query_one(PathInput)
    field.value = str(files / "holiday.jpg")
    field.focus()
    await pilot.pause()
    await pilot.press("enter")
    for _ in range(8):
        await pilot.pause(0.05)

    sent = app.engine.history(app.current_chat_id)[-1]
    assert sent.file_name == "holiday.jpg"
    assert sent.media_type == "photo"
    assert sent.text == "look at this"
    assert app.query_one(Composer).text == "", "the caption must not be left behind"


async def test_cancelling_the_picker_sends_nothing(app, files):
    app, pilot = app
    before = len(app.engine.history(app.current_chat_id))

    await open_picker(app, pilot)
    await pilot.press("escape")
    for _ in range(6):
        await pilot.pause(0.05)

    assert len(app.engine.history(app.current_chat_id)) == before
    assert not isinstance(app.screen, AttachScreen)


async def test_a_missing_path_is_refused_rather_than_sent(app, files):
    app, pilot = app
    before = len(app.engine.history(app.current_chat_id))

    screen = await open_picker(app, pilot)
    field = screen.query_one(PathInput)
    field.value = str(files / "no-such-file.txt")
    field.focus()
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()

    assert isinstance(app.screen, AttachScreen), "the picker should stay open"
    assert len(app.engine.history(app.current_chat_id)) == before


async def test_read_only_channels_refuse_attachments(app, files):
    app, pilot = app
    channel = next(c for c in app.engine.chats.values() if c.is_read_only)
    app.open_chat(channel.id, force=True)
    await pilot.pause()
    warnings = []
    app.notify = lambda msg, *a, **k: warnings.append(str(msg))

    await pilot.press("ctrl+r")
    for _ in range(6):
        await pilot.pause(0.05)

    assert not isinstance(app.screen, AttachScreen)
    assert any("read-only" in w for w in warnings)


# -- sending several files --------------------------------------------------


async def queue_and_send(app, pilot, screen, paths, send_last=True):
    """Queue every path but the last, which is left in the field for Send."""
    field = screen.query_one(PathInput)
    for path in paths[:-1]:
        field.value = str(path)
        field.focus()
        await pilot.pause()
        await pilot.press("ctrl+n")
        await pilot.pause()
    field.value = str(paths[-1]) if send_last else ""
    field.focus()
    await pilot.pause()
    await pilot.press("enter")
    for _ in range(12):
        await pilot.pause(0.05)


async def test_several_files_are_all_sent(app, files):
    app, pilot = app
    app.query_one(Composer).load_text("three files")
    screen = await open_picker(app, pilot)

    await queue_and_send(
        app, pilot, screen,
        [files / "report.pdf", files / "holiday.jpg", files / "report.pdf"],
    )

    sent = app.engine.history(app.current_chat_id)[-2:]
    assert [m.file_name for m in sent] == ["report.pdf", "holiday.jpg"], (
        "the same file queued twice must only be sent once"
    )


async def test_only_the_first_of_a_batch_carries_the_caption(app, files):
    app, pilot = app
    app.query_one(Composer).load_text("look at these")
    screen = await open_picker(app, pilot)

    await queue_and_send(app, pilot, screen, [files / "report.pdf", files / "holiday.jpg"])

    first, second = app.engine.history(app.current_chat_id)[-2:]
    assert first.text == "look at these"
    assert second.text == ""


async def test_the_composer_is_cleared_once_for_the_whole_batch(app, files):
    app, pilot = app
    app.query_one(Composer).load_text("batch")
    screen = await open_picker(app, pilot)

    await queue_and_send(app, pilot, screen, [files / "report.pdf", files / "holiday.jpg"])

    assert app.query_one(Composer).text == ""


async def test_queueing_an_unreadable_path_adds_nothing(app, files):
    app, pilot = app
    screen = await open_picker(app, pilot)
    field = screen.query_one(PathInput)

    field.value = str(files / "not-here.txt")
    field.focus()
    await pilot.pause()
    await pilot.press("ctrl+n")
    await pilot.pause()

    assert screen._queue == []
    assert isinstance(app.screen, AttachScreen), "the picker stays open"


async def test_sending_stops_at_the_first_failure(app, files):
    app, pilot = app
    calls: list[str] = []
    original = app.engine.send_file

    def failing(chat_id, path, **kwargs):
        calls.append(Path(path).name)
        if len(calls) == 2:
            raise OSError("connection reset")
        return original(chat_id, path, **kwargs)

    app.engine.send_file = failing
    notices: list[str] = []
    app.notify = lambda msg, *a, **k: notices.append(str(msg))

    screen = await open_picker(app, pilot)
    await queue_and_send(
        app, pilot, screen,
        [files / "report.pdf", files / "holiday.jpg", files / "reports"],
    )

    assert len(calls) == 2, "the third file must not be attempted"
    assert any("Failed to send" in n for n in notices), notices
