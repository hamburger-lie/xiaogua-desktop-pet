"""OpenAI-compatible Chat Completions behind the Anthropic-shaped interface.

XiaoguaAgent's tool loop (and its evidence gate) is written against
`client.messages.create(...)` returning `.content` blocks of type "text" /
"tool_use". This client accepts the same call, translates it to
`POST {base_url}/chat/completions`, and translates the answer back, so the loop
runs unchanged against DeepSeek, Qwen, Gemini, a local Ollama and the rest.

Translation, request side:
  system            -> {"role": "system"}
  text/image blocks -> content parts (image as a data: URL; dropped with a note
                       when the model has no vision)
  tool_use blocks   -> assistant "tool_calls"
  tool_result       -> {"role": "tool", "tool_call_id": ...}
  tools             -> {"type": "function", "function": {...}}
Anthropic-only arguments (thinking, output_config, cache_control) are dropped.
A message that is text only is sent as a plain string: some vendors (Qianfan)
reject content arrays that hold no image.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable

import httpx

NO_VISION_NOTE = "（用户附了一张截图，但当前模型不能看图，截图没有发送。请只按文字回答，并提醒用户换一个能看图的模型。）"
MAX_OUTPUT_TOKENS = 4096     # 小瓜's answers are short; some vendors reject larger limits


class ProviderError(Exception):
    """An HTTP error from the vendor, with the vendor's own message."""

    def __init__(self, status_code: int, message: str):
        super().__init__(f"{status_code}: {message}")
        self.status_code = status_code
        self.message = message

    def friendly(self) -> str:
        return explain(self.status_code, self.message)


# (pattern in the vendor's message, lower-cased) -> what to tell the user
_EXPLANATIONS = (
    (("not activated", "未开通", "has not activated"),
     "这个模型在你的账号里还没开通。去厂商控制台的「开通管理 / 模型广场」开通它，或换一个已开通的模型。"),
    (("insufficient", "balance", "余额", "欠费", "quota", "arrearage", "payment"),
     "账号余额或额度不够了，去厂商控制台充值或查看额度。"),
    (("model_not_found", "does not exist", "model not found", "no such model", "invalid model", "模型不存在"),
     "厂商那边没有这个模型名。点设置里的「测试并获取模型列表」挑一个。"),
    (("invalid api key", "incorrect api key", "invalid_api_key", "authentication", "unauthorized",
      "api key not valid", "invalid token", "鉴权"),
     "密钥不对或已失效。去厂商控制台重新复制一份，在设置里保存。"),
    (("rate limit", "rate_limit", "too many requests", "限流", "tpm", "rpm"),
     "请求太频繁，被厂商限流了。稍等一会儿再问。"),
    (("image", "vision", "multimodal", "图片"),
     "这个模型不接受图片。换一个能看图的模型（名字里常带 vl / vision / v）。"),
)


def explain(status_code: int, message: str) -> str:
    """The vendor's error in plain Chinese, with what to do about it."""
    lowered = message.lower()
    for patterns, advice in _EXPLANATIONS:
        if any(p in lowered for p in patterns):
            return advice
    if status_code in (401, 403):
        return "密钥被拒绝了。检查一下密钥，或它有没有这个模型的权限。"
    if status_code == 402:
        return "账号余额或额度不够了，去厂商控制台充值或查看额度。"
    if status_code == 429:
        return "请求太频繁，被厂商限流了。稍等一会儿再问。"
    if status_code >= 500:
        return "厂商那边的服务出错了，过一会儿再试。"
    return "厂商拒绝了这次请求。"


def _get(block: Any, key: str, default=None):
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def _system_text(system) -> str:
    if isinstance(system, str):
        return system
    return "\n\n".join(_get(b, "text", "") for b in system or [])


def translate_messages(system, messages: list, vision: bool) -> list[dict]:
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": _system_text(system)})
    for message in messages:
        role, content = _get(message, "role"), _get(message, "content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "assistant":
            text = "".join(_get(b, "text", "") for b in content if _get(b, "type") == "text")
            calls = [{"id": _get(b, "id"), "type": "function",
                      "function": {"name": _get(b, "name"),
                                   "arguments": json.dumps(_get(b, "input") or {}, ensure_ascii=False)}}
                     for b in content if _get(b, "type") == "tool_use"]
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            continue
        parts, has_image = [], False
        for block in content:
            kind = _get(block, "type")
            if kind == "tool_result":
                result = _get(block, "content")
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False)
                out.append({"role": "tool", "tool_call_id": _get(block, "tool_use_id"), "content": result})
            elif kind == "text":
                parts.append({"type": "text", "text": _get(block, "text", "")})
            elif kind == "image":
                source = _get(block, "source")
                if vision:
                    has_image = True
                    parts.append({"type": "image_url", "image_url": {
                        "url": f"data:{_get(source, 'media_type')};base64,{_get(source, 'data')}"}})
                else:
                    parts.append({"type": "text", "text": NO_VISION_NOTE})
        if parts:
            if has_image:
                out.append({"role": role, "content": parts})
            else:
                out.append({"role": role, "content": "\n\n".join(p["text"] for p in parts)})
    return out


def translate_tools(tools: list[dict] | None) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t["input_schema"]}} for t in tools or []]


def translate_response(data: dict) -> SimpleNamespace:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    blocks = []
    if message.get("content"):
        blocks.append(SimpleNamespace(type="text", text=message["content"]))
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments") or "{}"
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except ValueError:
            parsed = {"_unparsed_arguments": arguments}      # the tool reports it back as an error
        blocks.append(SimpleNamespace(type="tool_use", id=call.get("id") or f"call_{len(blocks)}",
                                      name=function.get("name"), input=parsed))
    stop = "tool_use" if message.get("tool_calls") else "end_turn"
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=data.get("usage"))


class OpenAICompatClient:
    """Duck-types `anthropic.Anthropic` far enough for XiaoguaAgent."""

    def __init__(self, base_url: str, api_key: str | None, vision: bool = True,
                 token_param: str = "max_tokens", timeout: float = 120,
                 post: Callable[..., httpx.Response] | None = None, extra: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or "no-key"          # local servers ignore it but want the header
        self.vision, self.token_param, self.timeout = vision, token_param, timeout
        self.extra = dict(extra or {})              # vendor-only body fields (e.g. Doubao's thinking switch)
        self._post = post or httpx.post
        self.messages = self

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _payload(self, model, messages, system, tools, max_tokens) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": translate_messages(system, messages, self.vision),
            self.token_param: min(max_tokens, MAX_OUTPUT_TOKENS),
        }
        if tools:
            payload["tools"] = translate_tools(tools)
        for key, value in self.extra.items():
            payload.setdefault(key, value)
        return payload

    def create(self, *, model: str, messages: list, system=None, tools=None, max_tokens: int = 1024,
               **_anthropic_only) -> SimpleNamespace:
        payload = self._payload(model, messages, system, tools, max_tokens)
        response = self._post(f"{self.base_url}/chat/completions", headers=self._headers(),
                              json=payload, timeout=self.timeout)
        if response.status_code >= 400:
            raise ProviderError(response.status_code, _error_message(response))
        return translate_response(response.json())

    def stream_create(self, *, model: str, messages: list, system=None, tools=None, max_tokens: int = 1024,
                      on_text=None, **_anthropic_only) -> SimpleNamespace:
        """Same as create, but with "stream": true: text deltas go to on_text as they
        arrive; tool-call fragments are stitched together by index."""
        payload = self._payload(model, messages, system, tools, max_tokens)
        payload["stream"] = True
        text_parts: list[str] = []
        calls: dict[int, dict] = {}
        for data in self._stream(f"{self.base_url}/chat/completions", self._headers(), payload, self.timeout):
            for choice in data.get("choices") or []:
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text_parts.append(delta["content"])
                    if on_text is not None:
                        on_text(delta["content"])
                for fragment in delta.get("tool_calls") or []:
                    call = calls.setdefault(fragment.get("index", len(calls)),
                                            {"id": None, "function": {"name": "", "arguments": ""}})
                    call["id"] = fragment.get("id") or call["id"]
                    function = fragment.get("function") or {}
                    call["function"]["name"] += function.get("name") or ""
                    call["function"]["arguments"] += function.get("arguments") or ""
        message = {"content": "".join(text_parts) or None,
                   "tool_calls": [calls[i] for i in sorted(calls)] or None}
        return translate_response({"choices": [{"message": message}]})

    def _stream(self, url: str, headers: dict, payload: dict, timeout: float):
        """Yield each server-sent event's JSON. Replaced in tests."""
        with httpx.stream("POST", url, headers=headers, json=payload, timeout=timeout) as response:
            if response.status_code >= 400:
                response.read()
                raise ProviderError(response.status_code, _error_message(response))
            yield from parse_sse(response.iter_lines())


def parse_sse(lines):
    """Server-sent events -> JSON objects. Skips comments, keep-alives and [DONE]."""
    for line in lines:
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except ValueError:
            continue


def _error_message(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    error = data.get("error", data)
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(error)[:300]


def check_connection(base_url: str, api_key: str | None, model: str,
                     get: Callable[..., httpx.Response] | None = None,
                     post: Callable[..., httpx.Response] | None = None) -> tuple[bool, str, list[str]]:
    """(ok, message, model ids).

    The model list (free) fills the dropdown, but being listed does not mean the
    account may use a model (火山方舟 lists models the account has not activated).
    So a pass always comes from one real one-token request to the chosen model.
    """
    get, post = get or httpx.get, post or httpx.post
    headers = {"Authorization": f"Bearer {api_key or 'no-key'}"}
    base = base_url.rstrip("/")
    if not base:
        return False, "还没填接口地址", []
    try:
        available: list[str] = []
        response = get(f"{base}/models", headers=headers, timeout=15)
        if response.status_code in (401, 403):
            return False, explain(response.status_code, _error_message(response)), []
        if response.status_code < 400:
            available = [m.get("id") for m in response.json().get("data", []) if m.get("id")]
        if not model:
            return False, f"连上了，这个密钥能看到 {len(available)} 个模型，挑一个再测", available
        response = post(f"{base}/chat/completions", headers={**headers, "Content-Type": "application/json"},
                        json={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1},
                        timeout=30)
        if response.status_code < 400:
            return True, f"连上了，{model} 能用", available
        return False, f"{model} 用不了：{explain(response.status_code, _error_message(response))}", available
    except httpx.ConnectError:
        local = "localhost" in base or "127.0.0.1" in base
        return False, "连不上本机服务，先把它启动起来" if local else "连不上，检查一下网络、代理或接口地址", []
    except httpx.HTTPError as error:
        return False, f"连接出错：{error}", []
