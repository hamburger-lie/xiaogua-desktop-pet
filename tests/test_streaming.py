"""Streaming answers and the voice settings (no network: the streams are scripted)."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace as NS

import pytest

from meihua.companion.agent import SYSTEM_PROMPT, VOICE_STYLES, XiaoguaAgent
from meihua.companion.openai_compat import OpenAICompatClient, parse_sse

from test_companion_agent import PASSING_RECORD, ScriptedClient, text  # noqa: E402


def sse(*events) -> list[str]:
    return [f"data: {json.dumps(e, ensure_ascii=False)}" for e in events] + ["", "data: [DONE]"]


def text_chunk(value):
    return {"choices": [{"delta": {"content": value}}]}


def tool_chunks(index, call_id, name, arguments):
    """A tool call split the way vendors send it: id + name first, arguments in pieces."""
    half = len(arguments) // 2
    return [{"choices": [{"delta": {"tool_calls": [{"index": index, "id": call_id,
                                                     "function": {"name": name, "arguments": ""}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": index, "function": {"arguments": arguments[:half]}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": index, "function": {"arguments": arguments[half:]}}]}}]}]


class ScriptedStreams(OpenAICompatClient):
    """The OpenAI-compatible client with its HTTP stream replaced by scripted turns."""

    def __init__(self, turns):
        super().__init__("https://ark.example/api/v3", "k")
        self.turns, self.payloads = list(turns), []

    def _stream(self, url, headers, payload, timeout):
        self.payloads.append(payload)
        yield from parse_sse(self.turns.pop(0))


# ------------------------------------------------------------ the wire format

def test_sse_parsing_skips_noise_and_stops_at_done():
    lines = [": keep-alive", "", "data: {\"a\": 1}", "event: ping", "data: not json", "data: [DONE]",
             "data: {\"b\": 2}"]
    assert list(parse_sse(lines)) == [{"a": 1}]


def test_stream_create_passes_text_through_and_stitches_tool_calls():
    arguments = json.dumps({"question": "今天面试能成吗"}, ensure_ascii=False)
    client = ScriptedStreams([sse(text_chunk("先"), text_chunk("看看"), *tool_chunks(0, "c1", "cast_now", arguments))])
    seen = []
    response = client.stream_create(model="m", messages=[{"role": "user", "content": "hi"}], on_text=seen.append)
    assert seen == ["先", "看看"] and client.payloads[0]["stream"] is True
    kinds = [block.type for block in response.content]
    assert kinds == ["text", "tool_use"] and response.content[1].input == {"question": "今天面试能成吗"}


# ------------------------------------------------------------ the agent loop, streamed

def test_only_the_gated_answer_stays_streamed():
    record = json.dumps({"reading_record": PASSING_RECORD}, ensure_ascii=False)
    client = ScriptedStreams([
        sse(text_chunk("我先起一卦"), *tool_chunks(0, "c1", "cast_now", json.dumps({"question": "面试能成吗"}))),
        sse(text_chunk("东南取财。")),                                    # skips the gate: taken back
        sse(*tool_chunks(0, "c2", "validate_reading", record)),
        sse(text_chunk("能成，"), text_chunk("早点到。")),
    ])
    agent = XiaoguaAgent(client=client, model="m", thinking=False, effort=None)
    shown = []

    def on_text(delta):
        shown.append(delta)

    def on_discard():
        shown.clear()

    reply = agent.ask("说说面试", on_text=on_text, on_discard=on_discard)
    assert reply.validated is True and reply.text == "能成，早点到。"
    assert "".join(shown) == reply.text                  # what is left on screen is the answer


def test_anthropic_sdk_streaming_path():
    class Events:
        def __init__(self, parts, final):
            self.text_stream, self._final = iter(parts), final

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return self._final

    class Messages:
        def __init__(self):
            self.calls = []

        def stream(self, **kwargs):
            self.calls.append(kwargs)
            return Events(["小瓜", "在呢"], NS(content=[text("小瓜在呢")], stop_reason="end_turn"))

    client = NS(messages=Messages())
    seen = []
    reply = XiaoguaAgent(client=client).ask("在吗", on_text=seen.append)
    assert seen == ["小瓜", "在呢"] and reply.text == "小瓜在呢"
    assert client.messages.calls[0]["thinking"] == {"type": "adaptive"}


def test_without_a_callback_nothing_streams():
    client = ScriptedClient([[text("在的")]])                 # no stream methods at all
    assert XiaoguaAgent(client=client).ask("你好").text == "在的"


# ------------------------------------------------------------ voice

def test_voice_rules_put_the_verdict_first_in_plain_words():
    voice = SYSTEM_PROMPT[SYSTEM_PROMPT.index("## 说话方式"):]
    assert "第一句直接给结论" in voice and "60～150 字" in voice and "去掉 AI 味" in voice
    example = voice[voice.index("示例"):]
    for jargon in ("体用", "比和", "· ", "——"):                      # the example itself must not show them
        assert jargon not in example, jargon


@pytest.mark.parametrize("style", ["直白", "平衡", "玄一点"])
def test_voice_style_is_sent_in_the_dynamic_block(style):
    client = ScriptedClient([[text("在的")]])
    XiaoguaAgent(client=client, voice_style=style).ask("你好")
    system = client.requests[0]["system"]
    assert system[0]["text"] == SYSTEM_PROMPT and "cache_control" in system[0]   # the cached part never changes
    assert VOICE_STYLES[style] in system[1]["text"]


# ------------------------------------------------------------ the chat window

@pytest.fixture
def chat(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion.chat import ChatPanel
    return ChatPanel(None, "Ctrl+Alt+X")


def test_streamed_text_becomes_the_final_bubble(chat):
    chat.add_mine("今天宜什么")
    chat.start_thinking()
    chat.stream_text("今天适合")
    chat.stream_text("理发。")
    chat._flush_draft()
    assert chat.typing is None and chat.draft.body.text() == "今天适合理发。"
    chat.add_reply("今天适合理发。", "（只当参考）")
    kinds = [kind for kind, _ in chat.transcript()]
    assert kinds == ["mine", "xiaogua"]                      # one bubble, not a draft plus a reply
    assert "只当参考" in chat.transcript()[-1][1] and chat.draft is None


def test_discarded_text_brings_the_progress_back(chat):
    chat.start_thinking()
    chat.stream_text("我先翻翻黄历")
    chat.step("almanac_day")                                 # the model went on to a tool
    assert chat.draft is None and chat.typing is not None and "翻黄历" in chat.typing.body.text()
    assert [kind for kind, _ in chat.transcript()] == ["typing"]


def test_an_error_mid_stream_leaves_no_half_answer(chat):
    chat.start_thinking()
    chat.stream_text("今天适合")
    chat.add_error("连不上模型厂商")
    assert [kind for kind, _ in chat.transcript()] == ["error"]


def test_voice_style_setting_reaches_the_agent(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    from meihua.companion import app as companion
    from meihua.companion import config
    monkeypatch.setattr(companion, "start_hotkey", lambda combo, bridge, voice=None: NS(stop=lambda: None))
    agent = XiaoguaAgent(client=ScriptedClient([]))
    app = companion.Companion(config.Config.load(), agent=agent)
    app.settings.style_box.setCurrentText("直白")
    assert app.pet.agent.voice_style == "直白" and config.Config.load().voice_style == "直白"
