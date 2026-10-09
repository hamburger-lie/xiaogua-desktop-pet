"""小瓜 companion agent: a question in, a 小瓜-voiced answer out.

A manual tool-use loop over the Messages API. The loop, not the prompt, enforces
the rule the prompt alone kept losing: if a hexagram was cast this turn, no answer
leaves until a reading_record has passed the evidence gate. Then harness.py checks
the answer itself (wording, 时辰, made-up hexagrams, shape) before it is shown.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from . import harness
from .config import DEFAULT_MODEL as _CONFIG_DEFAULT
from .fast import FAST_TOOLS
from .session import answer_facts, daily_context_text, daily_tool_schemas
from .tools import DAILY_TOOL_SCHEMAS, run_tool

DEFAULT_MODEL = os.environ.get("MEIHUA_MODEL", _CONFIG_DEFAULT)
_log = logging.getLogger("xiaogua.harness")

MAX_ROUNDS = 12          # model calls per question, tool rounds included
MAX_GATE_NUDGES = 2      # times an ungated answer is sent back before giving up
MAX_REDOS = 1            # times an answer with a wrong fact (harness.py) is sent back before code fixes it
# With a session the one-call tool casts (daily_reading): the bare casting tools are not offered,
# so a passing question is not answered with a hexagram cast on the side.
SESSION_HIDDEN = {"cast_now", "lookup_hexagrams"}
HISTORY_TURNS = 6        # earlier user/assistant text pairs kept without a session

SYSTEM_PROMPT = """你是「小瓜」，每日一瓜的日常小参谋：一只浅绿色的小西瓜，温和、安静、清醒、直接，有一点轻松和玄味，但不装神弄鬼。用户跟你聊生活里的事，最常问的是今天黄历宜什么、按他的属相今天适合干嘛、哪天适合办某件事，也会问一件具体的事能不能成。

## 事实从哪来
- 系统消息里的【今天】【用户】是程序算好的（寿星万年历，宜忌按《协纪辨方书》）。问今天，直接用，不用再查。
- 问别的日子（明天、周六、下个月初三），调 almanac_day，日期按【今天】自己换算成公历 YYYY-MM-DD。
- 问「哪天适合搬家 / 结婚 / 签合同」，调 almanac_pick_days。返回 UNKNOWN_ACTIVITY 时换成列表里最接近的说法再查；返回 approximate 时说一句老黄历没这一项、是按哪项看的。
- 用户说了自己的属相（「我属虎」）或改口，调 remember_zodiac。不知道属相时，等问到跟他本人有关的事再问一句属什么，别一上来就问。
- 【小瓜记得的你】是他以前让小瓜记下的事。他说了以后还用得上的事（称呼、偏好、带日期的计划，比如挑定了「那就周日搬」），调 remember_fact，日期按【今天】换算；某条不对了或取消了，调 forget_fact；计划有了结果（「搬完了，挺顺」），调 close_fact。他要你到点提醒（「下午三点提醒我交报告」「到好时辰叫我」），remember_fact 带上 time（HH:MM，按【今天】的钟点换算），回答里说一句几点叫他。标着「问过结果，等他回答」的，他接下来说的多半就是那件事的结果。记下了不用特意宣布。
- 宜忌、冲煞、干支、时辰吉凶全以【今天】和工具结果为准，不凭记忆编，不自己推干支。

## 属相跟日子怎么看
day_tone：冲＝这天冲他，签约、搬家、动土、结婚这类大事往后挪，日常照常；不顺（刑、害）＝容易有小摩擦，说话办事留一手；合中带刑、合中带害＝有助力也有小别扭；顺（六合、三合）＝这天跟他合，适合往前推；平＝就按黄历本身的宜忌来。
tai_sui 是今年跟太岁的关系，只在他问今年运势或本命年时提一句，不吓人，不劝人花钱化解。
宜忌里的老词用 plain 的白话说。丧葬类（安葬、入殓、破土、启钻、成服除服）一般人用不上，除非他问，别拿来当「今天适合干的事」。「其余的事别做」（馀事勿取）＝没列出来的事别做。宜里没有、忌里也没有的事，就说黄历没专门讲，照常就行。
时辰挑一两个还没过的顺口说，别全列；照【今天】给的整段说（「傍晚五点到七点」），不说「几点前 / 几点后」。财神、喜神方位最多一句带过，不编具体地点。

## 要不要起卦
黄历看的是日子，不是算一件具体的事。他问一件具体的事「要不要 / 能不能 / 成不成」（「今天去面试能成吗」「这单签不签」）时起一卦：**只调一次 daily_reading**（question 传原话，topic 选 事业 / 合作 / 钱财 / 感情 / 其他），它一次做完起卦、查卦义和依据核对，你不用再调 cast_now、lookup_hexagrams、validate_reading。一件事只起一卦，不为挑结果重起。闲聊和纯黄历问题不起卦。
下面的 reading_record 格式只在 daily_reading 的 gate 不是 PASS、或你用了旧工具时才需要：
reading_record 照这个格式，字段名一个都不能改（claims 和 actions 里都用 text）：
{"schema_version":"daily-yigua-reading-v1","method":"meihua","calculation_confidence":"A",
 "claims":[{"text":"…","evidence_ids":["MH-01"],"strength":1,"conditions":["限这次面试"],"reality_checks":["面试官的反馈"]}],
 "actions":[{"text":"…","evidence_ids":["MH-02","WORK-01"],"reality_anchor":"先跟 HR 书面确认时间地点","reversible":true,"risk_level":"low"}],
 "uncertainties":["…"],"prohibited_topics":[]}
strength 用 1；用 2 要至少两个证据编号，并且 conditions 是非空的字符串列表。证据编号用 MH-01 本互变、MH-02 体用、MH-03 旺衰、MH-05 场景分类、TIME-01 时机出行，再加对应的协议：WORK-01 事业跳槽、COOP-01 合作、MONEY-01 钱财、REL-01～REL-05 感情关系、GUARD-01～GUARD-06 安全边界。actions 要可逆、低风险，reality_anchor 写现实里能核对的一步。
回答时卦名可以说，体用、五行、比和这些词不说，翻成人话（「你跟这事气场顺」「对方压你一头」）。

## 边界
看病吃药、怀孕、打官司、投资炒股、借钱担保：黄历和卦都替代不了医生、律师和他自己的判断，最多说说日子好不好，具体怎么办让他找专业的人。不说「必然、注定、一定、大凶、血光之灾」，不制造焦虑，不推销开光、化解、转运的东西。
他闲聊就陪他聊两句，短一点；查资料、写东西、算账这类大活小瓜不在行，直说就好，再问问他今天想看点什么。

## 说话方式
像熟人随口聊天：口语、短句、直接。
情绪标签：每条回答的最后另起一行，写一个情绪标签，只能是〔开心〕〔加油〕〔担心〕〔犹豫〕〔平静〕之一，按这条回答的口气选：报好消息、顺的选开心；鼓劲、要冲的选加油；劝他别去、有风险的选担心；两说、拿不准、要他补信息的选犹豫；其余选平静。标签不会显示给他，也不要在正文里提到它。
1. 第一句直接给结论：「今天适合理发、见朋友，别签合同。」「周六日子不错，能搬。」
2. 再一两句说为什么，用人话：「今天是黄道日」「今天冲猴，你属猴，大事往后放放」。干支、建除、神煞的名字能不提就不提，要提就顺手翻成人话。
3. 需要时补一句时辰或方位。
长度：一般 60～150 字；挑日子可以给两三个日子，每个一句。
去掉 AI 味：不用小标题、表格、加粗、清单符号、破折号「——」；不说「首先其次」「总之」「建议你」「值得注意的是」「小瓜觉得」；不堆比喻，不写对仗。每次的说法都换，不套模板。
黄历是老规矩，只当参考：这层意思偶尔带一句就行，别每句都挂免责。
示例（只示意口气和长短，不要照抄）：
「今天适合收拾屋子、理个发，日子跟你也合，办事顺手。签合同、搬家就别赶今天了，黄历忌开市入宅。下午一点到三点是好时辰。」"""

VOICE_STYLES = {
    "直白": "说话风格：直白。第一句结论，再一句为什么，整条不超过 60 字。",
    "平衡": "说话风格：平衡。按「说话方式」来。",
    "玄一点": "说话风格：玄一点。可以多一分老黄历的味道和比喻，但第一句照样直接给结论。",
}


@dataclass
class Reply:
    text: str
    validated: bool
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    mood: str | None = None      # 开心 / 加油 / 担心 / 犹豫 / 平静: the answer's own tag, for 小瓜's motion
    checks: list[str] = field(default_factory=list)   # what the harness found and fixed (harness.py)


MOODS = ("开心", "加油", "担心", "犹豫", "平静")
_MOOD_TAG = re.compile(r"\s*[〔\[【(（]\s*(?:情绪[:：]\s*)?(" + "|".join(MOODS) + r")\s*[〕\]】)）]\s*$")


def split_mood(answer: str) -> tuple[str, str | None]:
    """「能成，早点到。\n〔开心〕」 -> ("能成，早点到。", "开心"). The tag never reaches the user or the history."""
    match = _MOOD_TAG.search(answer or "")
    if not match:
        return (answer or "").strip(), None
    return answer[:match.start()].rstrip(), match.group(1)


@dataclass
class XiaoguaAgent:
    client: Any
    model: str = DEFAULT_MODEL
    thinking: bool = True
    effort: str | None = "medium"
    history: list[dict[str, Any]] = field(default_factory=list)
    session: Any = None          # companion.session.Session: the conversation, today's 黄历, the memory
    voice_style: str = "平衡"    # 直白 / 平衡 / 玄一点 (settings)

    def _request(self, messages: list[dict[str, Any]], on_text=None) -> Any:
        # Layer 1 (fixed, cached) then layer 2 (style + today + what 小瓜 remembers, from code).
        tools = DAILY_TOOL_SCHEMAS + daily_tool_schemas()
        if self.session is not None:
            tools = [t for t in tools if t["name"] not in SESSION_HIDDEN]
        dynamic = [VOICE_STYLES.get(self.voice_style, VOICE_STYLES["平衡"]),
                   self.session.daily_context_text() if self.session is not None else daily_context_text(None)]
        system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
                  {"type": "text", "text": "\n\n".join(dynamic)}]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": system,
            "tools": tools,
            "messages": messages,
        }
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        try:
            return self._call(kwargs, on_text)
        except Exception as error:  # noqa: BLE001 — SDK-agnostic fallback below
            # A model that rejects adaptive thinking or effort still gets an answer.
            if (self.thinking or self.effort) and getattr(error, "status_code", None) == 400:
                self.thinking, self.effort = False, None
                kwargs.pop("thinking", None)
                kwargs.pop("output_config", None)
                return self._call(kwargs, on_text)
            raise

    def _call(self, kwargs: dict[str, Any], on_text) -> Any:
        """One model call; streams text deltas to on_text when the client can stream."""
        if on_text is not None and hasattr(self.client, "stream_create"):       # OpenAI-compatible
            return self.client.stream_create(on_text=on_text, **kwargs)
        stream = getattr(getattr(self.client, "messages", None), "stream", None)
        if on_text is not None and stream is not None:                           # Anthropic SDK
            with stream(**kwargs) as events:
                for text in events.text_stream:
                    on_text(text)
                return events.get_final_message()
        return self.client.messages.create(**kwargs)

    def _run_tool(self, name: str, arguments: dict) -> dict:
        if self.session is not None:
            return self.session.run_daily_tool(name, arguments)
        return run_tool(name, arguments)

    def ask(self, text: str, on_step=None, on_text=None, on_discard=None, cancel=None) -> Reply:
        """Progress callbacks, all optional:
        on_step(tool_name)  before each tool runs;
        on_text(delta)      streamed answer text as it arrives;
        on_discard()        the text streamed so far was not the answer (the model went on
                            to call a tool, or a check sent it back): take it down.
        cancel              a threading.Event: once set (the user pressed stop or took the
                            question back), no further call is made and nothing is remembered.
        """
        if self.session is not None:
            earlier = self.session.recent_daily_messages()     # this conversation, within a budget
        else:
            earlier = self.history[-2 * HISTORY_TURNS:]
        messages = earlier + [{"role": "user", "content": [{"type": "text", "text": text}]}]

        calls: list[dict[str, Any]] = []
        cast_done = gate_passed = False
        nudges = redos = 0
        checks: list[str] = []
        reminders: list[str] = []          # 「今天 15:00」: set this turn, to be said back
        # What the answer is checked against: today's good 时辰, plus any day looked up this turn.
        facts = answer_facts(self.session.zodiac if self.session is not None else None)
        facts.question = text or ""
        facts.max_chars = harness.DAILY_MAX_CHARS
        # Hexagrams the answer may name: whatever was said earlier in the conversation (a follow-up).
        for message in earlier:
            if isinstance(message.get("content"), str):
                facts.hexagrams |= set(harness.named_hexagrams(message["content"]))
        for _ in range(MAX_ROUNDS):
            if cancel is not None and cancel.is_set():
                return Reply("", False, calls, "cancelled")
            response = self._request(messages, on_text)
            messages.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
            if tool_uses:
                if on_discard is not None:
                    on_discard()                 # any text before a tool call was only a preamble
                results = []
                for block in tool_uses:
                    arguments = block.input if isinstance(block.input, dict) else json.loads(block.input)
                    if on_step is not None:
                        on_step(block.name)
                    output = self._run_tool(block.name, arguments)
                    calls.append({"tool": block.name, "status": output.get("status")})
                    if block.name == "cast_now" and output.get("status") == "OK":
                        cast_done = True
                    if block.name in FAST_TOOLS and output.get("status") == "OK":
                        cast_done = True                  # a reading, checked by code in the same call
                        gate_passed = gate_passed or output.get("gate") == "PASS"
                    if block.name == "validate_reading" and output.get("status") == "PASS":
                        gate_passed = True
                    facts.hexagrams |= harness.cast_names(output)
                    if block.name == "almanac_day":
                        facts.add_page(output)
                    if block.name == "remember_fact" and output.get("remind_at"):
                        reminders.append(output["remind_at"])
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(output, ensure_ascii=False)})
                messages.append({"role": "user", "content": results})
                continue

            answer, mood = split_mood("".join(getattr(b, "text", "") for b in response.content
                                              if getattr(b, "type", None) == "text").strip())
            # A reading needs the gate: no answer from a cast leaves before its record passed.
            if cast_done and not gate_passed and nudges < MAX_GATE_NUDGES:
                nudges += 1
                if on_discard is not None:
                    on_discard()                 # an ungated reading is never left on screen
                messages.append({"role": "user", "content": [{"type": "text", "text":
                    "（系统）本轮起了卦，但解读还没有通过 validate_reading。先组装 reading_record 过闸门，PASS 后再回答。"}]})
                continue
            validated = gate_passed or not cast_done
            # The harness: wording fixed by code; a wrong 时辰, a made-up hexagram, a verdict left for
            # later or a runaway length goes back once (one send-back in all); after that code says the
            # 时辰 itself, takes made-up hexagrams out and lets the rest through. A fault in the harness
            # never stops an answer.
            try:
                checked = harness.review(answer, facts)
            except Exception:  # noqa: BLE001
                _log.exception("回答检查出错，原样放行")
                checked = harness.Review(answer)
            if checked.problems and redos < MAX_REDOS:
                redos += 1
                checks += checked.sent_back()                     # what it was for, kept for the log
                if on_discard is not None:
                    on_discard()
                messages.append({"role": "user", "content": [{"type": "text",
                                                              "text": harness.redo_message(checked, facts)}]})
                continue
            if checked.wrong_hours or checked.invented:
                checked = harness.settle(checked, facts)
            answer, said_back = harness.say_reminders(checked.text, reminders)
            checks += checked.fixes + checked.let_through() + said_back + ([] if mood else ["漏情绪标签"])
            if checks:
                _log.info("回答检查：%s", "；".join(checks))
            if cancel is not None and cancel.is_set():
                return Reply("", False, calls, "cancelled")
            self._remember(text, answer)
            return Reply(answer, validated, calls,
                         None if validated else "解读未通过证据闸门，已停止追问", mood, checks)
        return Reply("小瓜这次想得太久了，换个问法再试一次？", False, calls, "达到最大轮次")

    def _remember(self, question: str, answer: str) -> None:
        if self.session is not None:
            self.session.record_daily_turn(question, answer)
            return
        self.history += [{"role": "user", "content": question},
                         {"role": "assistant", "content": answer}]
        self.history = self.history[-2 * HISTORY_TURNS:]


def make_agent(model: str | None = None, api_key: str | None = None, provider: str = "anthropic",
               base_url: str | None = None, deep_thinking: bool = False) -> XiaoguaAgent:
    """Build an agent for any provider (see providers.py).

    Anthropic goes through its SDK with adaptive thinking; every other vendor
    through the OpenAI-compatible adapter, where thinking/effort do not apply.
    Without a key the Anthropic SDK falls back to ANTHROPIC_API_KEY.
    """
    from . import providers

    preset = providers.get(provider)
    if preset.kind == "anthropic":
        import anthropic

        return XiaoguaAgent(client=anthropic.Anthropic(api_key=api_key), model=model or DEFAULT_MODEL)
    from .openai_compat import OpenAICompatClient

    # Fast by default: a vendor's think-first mode is switched off unless 深度思考 is on in the settings.
    client = OpenAICompatClient(base_url or preset.base_url, api_key, vision=preset.vision,
                                token_param=preset.token_param, extra=None if deep_thinking else preset.extra)
    return XiaoguaAgent(client=client, model=model or (preset.models[0] if preset.models else ""),
                        thinking=False, effort=None)


def check_connection(api_key: str | None, model: str, provider: str = "anthropic",
                     base_url: str | None = None) -> tuple[bool, str, list[str]]:
    """(ok, message, model ids the key can use). Uses the free model-list endpoints where they exist."""
    from . import providers

    preset = providers.get(provider)
    if preset.kind != "anthropic":
        from .openai_compat import check_connection as compat_check
        return compat_check(base_url or preset.base_url, api_key, model)
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=15)
    try:
        available = [m.id for m in client.models.list(limit=100)]
    except anthropic.AuthenticationError:
        return False, "密钥无效，Anthropic 拒绝了它", []
    except anthropic.APIConnectionError:
        return False, "连不上 Anthropic，检查一下网络或代理", []
    except anthropic.APIError as error:
        return False, f"出错了：{error}", []
    if model not in available:
        return False, f"密钥可用，但这个密钥用不了 {model}", available
    return True, f"连上了，{model} 可用", available
