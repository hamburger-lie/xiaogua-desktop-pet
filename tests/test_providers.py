"""Multi-vendor support: provider presets, the OpenAI-compatible adapter, settings.

No network: the adapter takes injectable HTTP functions, scripted here.
"""

from __future__ import annotations

import json
import os
import sys

import httpx
import pytest

from meihua.companion import config, providers
from meihua.companion.agent import XiaoguaAgent, make_agent
from meihua.companion.openai_compat import (NO_VISION_NOTE, OpenAICompatClient, ProviderError,
                                            check_connection, translate_messages, translate_response)

from test_companion_agent import PASSING_RECORD  # noqa: E402  (same passing reading record)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    for preset in providers.PROVIDERS:
        if preset.env:
            monkeypatch.delenv(preset.env, raising=False)
    monkeypatch.setattr(config, "CREDENTIAL_PREFIX", "meihua-xiaogua-pytest-" + tmp_path.name)
    yield
    for preset in providers.PROVIDERS:
        config.delete_api_key(preset.id)


def response(status=200, body=None):
    return httpx.Response(status, json=body if body is not None else {},
                          request=httpx.Request("POST", "https://example.test"))


def chat(content=None, tool_calls=None):
    return {"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tool_calls}}]}


def call(name, arguments, call_id="call_1"):
    return {"id": call_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


# ------------------------------------------------------------ presets

def test_presets_cover_the_major_vendors_and_are_well_formed():
    ids = [p.id for p in providers.PROVIDERS]
    assert len(ids) == len(set(ids)) >= 20
    for wanted in ("anthropic", "openai", "gemini", "deepseek", "qwen", "doubao", "zhipu", "moonshot",
                   "qianfan", "hunyuan", "minimax", "stepfun", "openrouter", "siliconflow", "ollama", "custom"):
        assert wanted in providers.BY_ID, wanted
    for preset in providers.PROVIDERS:
        assert preset.group in providers.GROUPS and preset.kind in ("anthropic", "openai")
        if preset.kind == "openai" and preset.id != "custom":
            local = preset.group == "本地"
            assert preset.base_url.startswith("http://localhost" if local else "https://"), preset.id
            assert not preset.base_url.endswith(("/", "/chat/completions")), preset.id
            assert preset.needs_key == (not local)
    assert providers.get("no-such-vendor").id == "doubao"


# ------------------------------------------------------------ translation

def test_messages_translate_to_chat_completions():
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    messages = [
        {"role": "user", "content": [image, {"type": "text", "text": "今天宜什么"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "先起卦"},
                                          {"type": "tool_use", "id": "t1", "name": "cast_now",
                                           "input": {"question": "今天宜什么"}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "{\"status\":\"OK\"}"}]},
        {"role": "user", "content": [{"type": "text", "text": "（系统）先过闸门"}]},
    ]
    out = translate_messages([{"type": "text", "text": "你是小瓜", "cache_control": {}}], messages, vision=True)
    assert out[0] == {"role": "system", "content": "你是小瓜"}
    assert out[1]["content"][0] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}
    assert out[2]["tool_calls"][0]["function"] == {"name": "cast_now", "arguments": '{"question": "今天宜什么"}'}
    assert out[3] == {"role": "tool", "tool_call_id": "t1", "content": "{\"status\":\"OK\"}"}
    assert out[4] == {"role": "user", "content": "（系统）先过闸门"}          # text only -> plain string


def test_without_vision_the_screenshot_is_replaced_by_a_note():
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}
    out = translate_messages(None, [{"role": "user", "content": [image, {"type": "text", "text": "看看"}]}],
                             vision=False)
    assert out == [{"role": "user", "content": NO_VISION_NOTE + "\n\n看看"}]
    assert "QUJD" not in json.dumps(out)


def test_responses_translate_back_including_broken_tool_arguments():
    parsed = translate_response(chat("好", [call("cast_now", {"question": "面试"}),
                                             {"id": "c2", "function": {"name": "map_points", "arguments": "{oops"}}]))
    kinds = [b.type for b in parsed.content]
    assert kinds == ["text", "tool_use", "tool_use"] and parsed.stop_reason == "tool_use"
    assert parsed.content[1].input == {"question": "面试"}
    assert parsed.content[2].input == {"_unparsed_arguments": "{oops"}


# ------------------------------------------------------------ the agent loop through the adapter

def test_the_evidence_gate_holds_on_an_openai_compatible_vendor():
    turns = [chat(tool_calls=[call("cast_now", {"question": "说说明天的面试"}, "c1")]),
             chat("顺着来。"),                                                # tries to skip the gate
             chat(tool_calls=[call("validate_reading", {"reading_record": PASSING_RECORD}, "c2")]),
             chat("小瓜看过了：顺着来。")]
    sent = []

    def post(url, headers, json, timeout):
        sent.append((url, headers, json))
        return response(200, turns.pop(0))

    client = OpenAICompatClient("https://api.deepseek.com/v1/", "sk-test", vision=False, post=post)
    agent = XiaoguaAgent(client=client, model="deepseek-chat", thinking=False, effort=None)
    reply = agent.ask("说说明天的面试")
    assert reply.validated is True and reply.text == "小瓜看过了：顺着来。"
    url, headers, first = sent[0]
    assert url == "https://api.deepseek.com/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-test"
    assert "thinking" not in first and "output_config" not in first
    assert first["max_tokens"] <= 4096 and first["tools"][0]["type"] == "function"
    assert any(m["role"] == "tool" for m in sent[1][2]["messages"])            # tool result went back
    assert "validate_reading" in json.dumps(sent[2][2]["messages"][-1], ensure_ascii=False)  # the nudge


def test_openai_uses_max_completion_tokens_and_errors_carry_the_vendor_message():
    seen = {}

    def post(url, headers, json, timeout):
        seen.update(json)
        return response(401, {"error": {"message": "Incorrect API key provided"}})

    client = OpenAICompatClient("https://api.openai.com/v1", "bad", token_param="max_completion_tokens", post=post)
    with pytest.raises(ProviderError) as caught:
        client.messages.create(model="gpt-5", messages=[{"role": "user", "content": "hi"}], max_tokens=16000)
    assert caught.value.status_code == 401 and "Incorrect API key" in str(caught.value)
    assert seen["max_completion_tokens"] == 4096 and "max_tokens" not in seen


def test_make_agent_picks_the_right_client():
    deepseek = make_agent("deepseek-chat", "sk-x", "deepseek")
    assert isinstance(deepseek.client, OpenAICompatClient) and deepseek.thinking is False
    assert deepseek.client.base_url == "https://api.deepseek.com/v1" and deepseek.client.vision is False
    custom = make_agent("my-model", "k", "custom", "http://10.0.0.5:8000/v1/")
    assert custom.client.base_url == "http://10.0.0.5:8000/v1"
    anthropic_agent = make_agent(None, "sk-ant-x", "anthropic")
    assert not isinstance(anthropic_agent.client, OpenAICompatClient) and anthropic_agent.thinking


# ------------------------------------------------------------ connection check

def test_connection_check_lists_models_and_then_really_calls_the_chosen_one():
    listing = response(200, {"data": [{"id": "qwen-vl-max-latest"}, {"id": "qwen-plus"}]})
    ok, message, models = check_connection("https://x/v1", "k", "qwen-plus", get=lambda *a, **k: listing,
                                           post=lambda *a, **k: response(200, chat("h")))
    assert ok and "能用" in message and models == ["qwen-vl-max-latest", "qwen-plus"]
    ok, message, _ = check_connection("https://x/v1", "bad", "m",
                                      get=lambda *a, **k: response(401, {"error": {"message": "invalid key"}}))
    assert not ok and "密钥" in message


def test_a_listed_but_not_activated_model_does_not_pass():
    """火山方舟 lists models the account has not activated; only a real call tells."""
    listing = response(200, {"data": [{"id": "doubao-seed-2-1-lite-260915"}]})
    refused = response(404, {"error": {"code": "ModelNotOpen", "message":
                       "Your account 123 has not activated the model doubao-seed-2-1-lite-260915. "
                       "Please activate the model service in the Ark Console."}})
    ok, message, models = check_connection("https://ark/api/v3", "k", "doubao-seed-2-1-lite-260915",
                                           get=lambda *a, **k: listing, post=lambda *a, **k: refused)
    assert not ok and "还没开通" in message and models == ["doubao-seed-2-1-lite-260915"]


def test_vendor_errors_are_explained_in_plain_chinese(tmp_path):
    from meihua.companion.openai_compat import explain
    assert "还没开通" in explain(404, "has not activated the model x")
    assert "余额" in explain(400, "Insufficient Balance")
    assert "密钥" in explain(401, "Incorrect API key provided")
    assert "限流" in explain(429, "")
    assert "没有这个模型" in explain(404, "The model `gpt-9` does not exist")
    assert "服务出错" in explain(503, "")


def test_connection_check_falls_back_to_one_token_when_there_is_no_list():
    posted = {}

    def post(url, headers, json, timeout):
        posted.update(json)
        return response(200, chat("h"))
    ok, message, _ = check_connection("https://ark/api/v3", "k", "ep-123", get=lambda *a, **k: response(404),
                                      post=post)
    assert ok and posted["max_tokens"] == 1 and posted["model"] == "ep-123"


def test_connection_check_explains_a_local_server_that_is_not_running():
    def refuse(*a, **k):
        raise httpx.ConnectError("refused")
    ok, message, _ = check_connection("http://localhost:11434/v1", None, "qwen2.5vl:7b", get=refuse)
    assert not ok and "本机" in message


# ------------------------------------------------------------ config

def test_old_single_model_config_migrates_and_each_vendor_keeps_its_own_choice():
    (config.home() / "config.json").write_text(json.dumps({"provider": "anthropic", "model": "claude-sonnet-5"}),
                                               encoding="utf-8")
    cfg = config.Config.load()
    assert cfg.provider == "anthropic" and cfg.model == "claude-sonnet-5" and "model" not in cfg.extra
    cfg.provider = "qwen"
    assert cfg.model == "qwen-vl-max-latest"                                 # the preset's first
    cfg.model = "qwen-plus"
    cfg.base_urls["qwen"] = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    cfg.save()
    again = config.Config.load()
    assert again.model == "qwen-plus" and again.base_url.startswith("https://dashscope-intl")
    again.provider = "anthropic"
    assert again.model == "claude-sonnet-5" and again.base_url == ""


@pytest.mark.skipif(sys.platform != "win32", reason="Credential Manager is Windows-only")
def test_keys_are_stored_per_vendor_and_each_env_var_wins(monkeypatch):
    config.store_api_key("sk-deepseek-1234567890", "deepseek")
    assert config.api_key("deepseek")[0] == "sk-deepseek-1234567890"
    assert config.api_key("anthropic")[0] is None                            # not shared
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    assert config.api_key("deepseek") == ("sk-env", "环境变量 DEEPSEEK_API_KEY")
    assert config.api_key("ollama") == (None, "本机服务，不需要密钥")


# ------------------------------------------------------------ app + settings window (headless Qt)

@pytest.fixture
def qt(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from meihua.companion import app as companion
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(companion, "start_hotkey", lambda combo, bridge, voice=None: type("L", (), {"stop": lambda s: None})())
    return companion


def test_local_vendors_need_no_key(qt):
    cfg = config.Config.load()
    cfg.provider = "ollama"
    agent, notice = qt.build_agent(cfg)
    assert isinstance(agent, XiaoguaAgent) and notice is None                # no key needed
    cfg.provider = "deepseek"
    agent, notice = qt.build_agent(cfg)
    assert isinstance(agent, qt.OfflineAgent) and "DeepSeek" in notice      # key missing
    if sys.platform == "win32":
        config.store_api_key("sk-deepseek-1234567890", "deepseek")
        agent, notice = qt.build_agent(cfg)
        assert isinstance(agent, XiaoguaAgent) and notice is None              # no pictures here: no warning


def test_settings_window_switches_vendor(qt):
    from PySide6.QtCore import Qt

    from meihua.companion.settings_window import SettingsWindow
    window = SettingsWindow(config.Config.load())
    box = window.provider_box
    headers = [i for i in range(box.count()) if not box.itemData(i, Qt.UserRole)]
    assert len(headers) == len(providers.GROUPS)                             # group headings
    assert not box.model().item(headers[0]).isEnabled()
    index = next(i for i in range(box.count()) if box.itemData(i, Qt.UserRole) == "zhipu")
    box.setCurrentIndex(index)
    assert window.config.provider == "zhipu" and config.Config.load().provider == "zhipu"
    assert window.base_url_edit.text() == "https://open.bigmodel.cn/api/paas/v4"
    assert window.model_box.currentText() == "glm-4.5v"
    assert "申请密钥" in window.provider_info.text()
    window.base_url_edit.setText("https://open.bigmodel.cn/api/coding/paas/v4")
    window.base_url_edit.editingFinished.emit()
    assert config.Config.load().base_urls == {"zhipu": "https://open.bigmodel.cn/api/coding/paas/v4"}
    window._reset_base_url()
    assert config.Config.load().base_urls == {}
    index = next(i for i in range(box.count()) if box.itemData(i, Qt.UserRole) == "ollama")
    box.setCurrentIndex(index)
    assert window.key_row.isHidden() and "不需要密钥" in window.key_source.text()


def test_fetched_models_fill_the_list(qt):
    from meihua.companion.settings_window import SettingsWindow
    cfg = config.Config.load()
    cfg.provider = "siliconflow"
    window = SettingsWindow(cfg)
    window._show_check(True, "连上了", ["siliconflow", "Qwen/QVQ-72B-Preview", "deepseek-ai/DeepSeek-V3"])
    items = [window.model_box.itemText(i) for i in range(window.model_box.count())]
    assert "Qwen/QVQ-72B-Preview" in items and window.check_result.text() == "连上了"


def test_the_bubble_explains_a_vendor_error_first(qt):
    error = ProviderError(404, "Your account 1 has not activated the model doubao-seed-2-1-lite-260915.")
    text = qt.explain_error(error)
    assert text.index("还没开通") < text.index("厂商原话")
    pet = qt.Pet(qt.OfflineAgent(), "Ctrl+Alt+X")
    pet._on_reply(error)
    kind, shown = pet.chat.transcript()[-1]
    assert kind == "error" and "还没开通" in shown
