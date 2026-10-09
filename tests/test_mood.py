"""The answer's mood tag: parsed and hidden by code, acted out by 小瓜."""

from __future__ import annotations

import os

import pytest

from meihua.companion.agent import Reply, XiaoguaAgent, split_mood
from meihua.companion.session import Session

from test_companion_agent import ScriptedClient, text  # noqa: E402


@pytest.mark.parametrize("answer, expected", [
    ("能成。\n〔加油〕", ("能成。", "加油")),
    ("能成。〔情绪：担心〕", ("能成。", "担心")),
    ("两说。\n[犹豫]", ("两说。", "犹豫")),
    ("今天宜理发。\n【平静】 ", ("今天宜理发。", "平静")),
    ("能成。", ("能成。", None)),
    ("他说〔开心〕了吗？好", ("他说〔开心〕了吗？好", None)),                 # only a tag at the very end
    ("能成。\n〔生气〕", ("能成。\n〔生气〕", None)),                     # not one of ours: left alone
])
def test_split_mood(answer, expected):
    assert split_mood(answer) == expected


def test_the_tag_is_neither_shown_nor_remembered(tmp_path):
    session = Session(tmp_path)
    reply = XiaoguaAgent(client=ScriptedClient([[text("在的，加把劲。\n〔加油〕")]]), session=session).ask("在吗")
    assert reply.text == "在的，加把劲。" and reply.mood == "加油"
    assert session.chat.daily[-1]["a"] == "在的，加把劲。"


@pytest.fixture
def pet(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion import app as companion
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    return companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")


def test_streaming_hides_the_tag_even_half_arrived(pet):
    pet._submit("面试能成吗")
    for delta in ("能成。\n", "〔担"):
        pet.bridge.delta.emit(pet._turn, delta)
    pet.chat._flush_draft()
    assert pet.chat.draft.body.text() == "能成。"


@pytest.mark.parametrize("mood, motion", [("担心", "摇头"), ("犹豫", "歪头"), ("加油", "加油"), ("开心", "点头")])
def test_the_pet_acts_the_mood_out(pet, mood, motion):
    pet._submit("面试能成吗")
    pet.bridge.delta.emit(pet._turn, "能成。")                              # the answer has started
    assert pet.state == "灵光一闪"
    pet.bridge.replied.emit(pet._turn, Reply("能成。", True, [], mood=mood))
    assert pet.queue == [motion, "待机"]


def test_a_calm_answer_just_settles(pet):
    pet._submit("今天宜什么")
    pet.bridge.replied.emit(pet._turn, Reply("宜理发。", True, [], mood="平静"))
    assert pet.state == "灵光一闪" and pet.queue == ["待机"]
