"""Tests for picking a file and sending it as an attachment."""

from __future__ import annotations

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
