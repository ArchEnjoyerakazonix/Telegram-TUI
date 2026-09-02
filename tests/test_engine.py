"""Unit tests for the mock engine."""

from telegram_tui.engine import MockEngine
from telegram_tui.models import ChatType


def make_engine() -> MockEngine:
    return MockEngine(seed=7)


def test_fixture_has_all_chat_types():
    engine = make_engine()
    types = {c.chat_type for c in engine.chats.values()}
    assert types == {ChatType.PRIVATE, ChatType.GROUP, ChatType.CHANNEL}
    assert len(engine.chats) >= 8


def test_sorted_chats_pins_first():
    engine = make_engine()
    chats = engine.sorted_chats()
    pinned_flags = [c.pinned for c in chats]
    # Pinned chats occupy a prefix of the list.
    assert all(pinned_flags[:2]), pinned_flags


def test_search_filters_by_title():
    engine = make_engine()
    result = engine.sorted_chats("py")
    assert len(result) == 1
    assert result[0].title == "Python Chat"
    assert engine.sorted_chats("нет такого чата") == []


def test_history_and_replies_link():
    engine = make_engine()
    devs = next(c for c in engine.chats.values() if c.title == "Textual Devs")
    history = engine.history(devs.id)
    assert history
    replied = [m for m in history if m.reply_to is not None]
    assert replied, "fixture should contain replies"
    target = engine.get_message(devs.id, replied[0].reply_to)
    assert target is not None


def test_send_marks_me_as_last_sender():
    engine = make_engine()
    alice = next(c for c in engine.chats.values() if c.title == "Alice")
    msg = engine.send(alice.id, "привет из теста")
    assert msg.sender_id == engine.me.id
    assert engine.history(alice.id)[-1].text == "привет из теста"
    assert engine.chats[alice.id].preview.startswith("привет из теста")


def test_plan_auto_reply_only_after_my_message():
    engine = make_engine()
    alice_id = next(c.id for c in engine.chats.values() if c.title == "Alice")
    engine.mark_read(alice_id)
    engine.send(alice_id, "ну?")
    planned = engine.plan_auto_reply(alice_id)
    assert planned is not None
    assert 2.0 <= planned.delay <= 5.0
    reply = planned.factory()
    assert reply.chat_id == alice_id
    assert reply.sender_id != engine.me.id

    # Sending in a channel must not plan a reply.
    channel_id = next(c.id for c in engine.chats.values() if c.chat_type == ChatType.CHANNEL)
    assert engine.plan_auto_reply(channel_id) is None


def test_tick_and_mark_read():
    engine = make_engine()
    chat_id = next(iter(engine.chats))
    before = engine.chats[chat_id].unread
    engine.tick()
    total_unread = sum(c.unread for c in engine.chats.values())
    # tick() either does nothing or adds exactly one unread somewhere
    assert total_unread >= before
    engine.mark_read(chat_id)
    assert engine.chats[chat_id].unread == 0


def test_inject_incoming_targets_chat():
    engine = make_engine()
    chat_id = next(c.id for c in engine.chats.values() if c.title == "Bob")
    msg = engine.inject_incoming(chat_id)
    assert msg.chat_id == chat_id
    assert msg.sender_id != engine.me.id
    assert engine.chats[chat_id].unread >= 1


def test_toggle_pin():
    engine = make_engine()
    chat_id = next(c.id for c in engine.chats.values() if not c.pinned)
    was = engine.chats[chat_id].pinned
    engine.toggle_pin(chat_id)
    assert engine.chats[chat_id].pinned is not was
