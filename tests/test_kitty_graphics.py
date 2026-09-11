"""Tests for kitty's graphics protocol: the escape commands and the placeholders."""

from __future__ import annotations

import re

import pytest

from telegram_tui import kitty_graphics as kg
from telegram_tui.kitty_diacritics import ROWCOLUMN_DIACRITICS
from telegram_tui.media import write_mock_photo


# -- terminal detection ------------------------------------------------------


@pytest.mark.parametrize(
    "environ,supported",
    [
        ({"TERM": "xterm-kitty"}, True),
        ({"KITTY_WINDOW_ID": "1", "TERM": "screen"}, True),
        ({"TERM": "xterm-256color"}, False),
        ({"TERM": ""}, False),
        ({"TERM": "xterm-kitty", "TELEGRAM_TUI_NO_KITTY": "1"}, False),
    ],
)
def test_terminal_detection(environ, supported):
    assert kg.is_supported(environ) is supported


# -- the escape commands -----------------------------------------------------


def test_transmit_names_a_png_file_and_silences_replies():
    command = kg.transmit("/tmp/pic.png", 4242, cols=10, rows=5)

    send, place = command.split("\033\\")[:2]
    assert send.startswith("\033_G") and "a=t" in send and "t=f" in send
    assert "f=100" in send, "kitty takes PNG or raw pixels, nothing else"
    assert "i=4242" in send and "q=2" in send, "a reply would be typed into the UI"
    assert send.endswith("L3RtcC9waWMucG5n")  # base64 of the path

    assert "a=p" in place and "U=1" in place, "placeholders need a virtual placement"
    assert "c=10" in place and "r=5" in place and "i=4242" in place


def test_delete_frees_the_image():
    assert kg.delete(7) == "\033_Ga=d,d=I,i=7,q=2\033\\"


# -- the placeholder grid ----------------------------------------------------


def test_placeholder_cells_spell_out_their_own_position():
    text = kg.placeholder_text(0x010203, cols=3, rows=2)

    lines = text.plain.split("\n")
    assert len(lines) == 2
    for row, line in enumerate(lines):
        assert line.count(kg.PLACEHOLDER) == 3
        for col, cell in enumerate(line.split(kg.PLACEHOLDER)[1:]):
            assert cell == chr(ROWCOLUMN_DIACRITICS[row]) + chr(ROWCOLUMN_DIACRITICS[col])


def test_placeholder_colour_carries_the_image_id():
    """Kitty reads the id out of the foreground colour, so it must be exact."""
    text = kg.placeholder_text(0xAB12CD, cols=2, rows=1)

    colours = {span.style.color.triplet for span in text.spans}
    assert colours == {(0xAB, 0x12, 0xCD)}


def test_placeholder_grid_is_bounded_by_the_diacritic_table():
    huge = kg.placeholder_text(1, cols=10_000, rows=1)
    assert huge.plain.count(kg.PLACEHOLDER) == len(ROWCOLUMN_DIACRITICS)


@pytest.mark.parametrize("cols,rows", [(0, 5), (5, 0), (-1, -1)])
def test_empty_grid_for_an_empty_box(cols, rows):
    assert kg.placeholder_text(1, cols, rows).plain == ""


# -- geometry ----------------------------------------------------------------


def test_png_size_reads_the_header(tmp_path):
    image = write_mock_photo(tmp_path / "p.png", 320, 180)
    assert kg.png_size(image) == (320, 180)


def test_png_size_rejects_anything_else(tmp_path):
    not_png = tmp_path / "x.jpg"
    not_png.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 40)
    assert kg.png_size(not_png) is None
    assert kg.png_size(tmp_path / "missing.png") is None


def test_fit_cells_keeps_proportions():
    # A cell is about twice as tall as wide, so a square image needs half as
    # many rows as columns.
    assert kg.fit_cells((800, 800), 40, 40) == (40, 20)


def test_fit_cells_respects_both_limits():
    cols, rows = kg.fit_cells((400, 1200), 44, 18)
    assert cols <= 44 and rows <= 18

    cols, rows = kg.fit_cells((1600, 400), 44, 18)
    assert cols <= 44 and rows <= 18


def test_fit_cells_without_a_known_size():
    assert kg.fit_cells(None, 30, 12) == (30, 12)


# -- image ids ---------------------------------------------------------------


def test_ids_are_unique_and_recycled():
    ids = kg.ImageIds()
    first = [ids.allocate() for _ in range(5)]

    assert len(set(first)) == 5
    assert ids.live == set(first)

    ids.release(first[0])
    assert first[0] not in ids.live


def test_ids_stay_inside_the_24_bit_colour_they_travel_in():
    ids = kg.ImageIds()
    for _ in range(500):
        image_id = ids.allocate()
        assert 0 < image_id <= 0xFFFFFF


# -- the widget picks the right renderer ------------------------------------


async def run_with_photo(monkeypatch, supported: bool, release: bool = False) -> dict:
    """Open a chat holding a photo and report how the widget rendered it."""
    from telegram_tui.app import TelegramTUI
    from telegram_tui.engine import MockEngine
    from telegram_tui.widgets.photo import PhotoWidget

    sent: list[str] = []
    monkeypatch.setattr(kg, "is_supported", lambda environ=None: supported)
    monkeypatch.setattr(kg, "write_to_terminal", lambda payload: sent.append(payload) or True)

    engine = MockEngine(seed=5)
    chat_id = next(c for c in engine.chats if any(m.has_photo for m in engine.history(c)))
    app = TelegramTUI(engine=engine, live_traffic=False)
    async with app.run_test(size=(120, 40)) as pilot:
        app.open_chat(chat_id, force=True)
        for _ in range(10):
            await pilot.pause(0.05)
        widget = app.query(PhotoWidget).first()
        image_id = widget._kitty_id
        if release:
            widget._release_kitty_image()
        return {"image_id": image_id, "sent": sent, "live": set(kg.IMAGE_IDS.live)}


async def test_kitty_terminals_get_real_pixels(monkeypatch):
    result = await run_with_photo(monkeypatch, supported=True)

    assert result["image_id"] is not None
    assert any("a=t" in payload for payload in result["sent"]), "image must be transmitted"
    assert any("a=p" in payload for payload in result["sent"]), "placement must be created"
    assert all("q=2" in payload for payload in result["sent"]), "replies must be silenced"


async def test_other_terminals_fall_back_to_characters(monkeypatch):
    result = await run_with_photo(monkeypatch, supported=False)

    assert result["image_id"] is None
    assert result["sent"] == [], "nothing may be written to a terminal that cannot show it"


async def test_releasing_a_photo_frees_the_image(monkeypatch):
    result = await run_with_photo(monkeypatch, supported=True, release=True)
    image_id = result["image_id"]

    assert any(f"a=d,d=I,i={image_id}" in payload for payload in result["sent"])
    assert image_id not in kg.IMAGE_IDS.live
