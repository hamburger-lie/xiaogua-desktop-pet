"""Conversation state for 每日一瓜: the open conversation, its Q&A, today's 黄历 for the model.

Principles:
- The code owns the state, not the model. Today's 黄历, the user's 属相 and what 小瓜
  remembers are worked out here and handed to the model; it does not recall them itself.
- Conversations (会话) are separate threads, one file each (chats.py); a new day starts a
  new one. Deleting a conversation sends it to the trash (trash.py) for 30 days.
- A concrete matter gets one cast (daily_reading), checked by the evidence gate in code.
- Stored as JSON, text only.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import fast, harness, tools
from .chats import Chat, ChatStore, new_chat
from .memory import MEMORY_TOOLS, memory_tool_schemas

import almanac  # type: ignore[import-not-found]  # noqa: E402 — on sys.path via tools

RECENT_TURN_CHARS = 4000                 # budget for the conversation's earlier Q&A, newest first
WEEKDAY = "一二三四五六日"


def _now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _weeks(today: date) -> str:
    """「这周」and「下周」as dates: the model counted 7 days from today as 这周."""
    monday = today - timedelta(days=today.weekday())

    def span(start: date) -> str:
        end = start + timedelta(days=6)
        return f"{start.month}月{start.day}日（一）到{end.month}月{end.day}日（日）"

    return f"这周是{span(monday)}，下周是{span(monday + timedelta(days=7))}。"


def daily_context_text(zodiac: str | None, now: datetime | None = None) -> str:
    """【今天】and【用户】: today's 黄历 worked out by code, not by the model."""
    now = now or _now()
    page = almanac.day_almanac(now.date(), zodiac or None)
    god = page["day_god"]
    lines = [f"【今天】{now.date().isoformat()} 星期{WEEKDAY[now.weekday()]} {now:%H:%M}，"
             f"农历{page['lunar']}，{page['ganzhi']['day']}日（{god['name']}{god['kind']}，{page['officer']}）"
             + (f"，今天交{page['solar_term']}" if page["solar_term"] else ""),
             f"宜：{almanac.plain_text(page['yi'])}",
             f"忌：{almanac.plain_text(page['ji'])}",
             f"{page['clash']['desc']}，煞{page['clash']['sha_direction']}。"
             f"财神{page['directions']['财神']}，喜神{page['directions']['喜神']}。",
             _weeks(now.date())]
    you = page.get("for_you")
    if you:
        relation = "、".join(you["day_relations"]) or "无冲无合"
        line = f"【用户】属{you['zodiac']}：今天跟他{relation}（day_tone={you['day_tone']}）"
        if you["tai_sui"]:
            line += f"；今年{'、'.join(you['tai_sui'])}"
        clock = f"{now:%H:%M}"
        ahead = [h for h in you["good_hours"] if h.split("-")[-1] > clock][:3]   # not yet passed
        line += f"；今天还没过的好时辰：{'、'.join(harness.hour_words(h) for h in ahead) or '没有了'}。"
        lines.append(line)
    else:
        lines.append("【用户】属相：还不知道。问到跟他本人有关的（今天适不适合我、我该干嘛）再问一句属什么；"
                     "他说了就调 remember_zodiac 记下。")
    return "\n".join(lines)


def answer_facts(zodiac: str | None, now: datetime | None = None) -> harness.Facts:
    """What an answer is checked against before it is shown: today's good 时辰 for the user."""
    now = now or _now()
    facts = harness.Facts(today=now.date(), now=now)
    facts.add_page(almanac.day_almanac(now.date(), zodiac or None))
    return facts


ZODIAC_SCHEMA = {"name": "remember_zodiac",
                 "description": "用户说了自己的属相（「我属虎」「我是属龙的」）或改口时调用，记下来，之后看黄历都按这个属相。",
                 "input_schema": {"type": "object", "properties": {
                     "zodiac": {"type": "string", "enum": list(almanac.ZODIAC)}}, "required": ["zodiac"]}}

# How a day sits with the user's 属相, in the morning greeting's words.
TONE_WORDS = {"冲": "相冲，大事缓缓", "不顺": "有点别扭，说话办事留一手", "合中带刑": "有助力也有小别扭",
              "合中带害": "有助力也有小别扭", "顺": "相合，适合往前推", "平": "不冲不合"}


def daily_tool_schemas() -> list[dict[str, Any]]:
    """小瓜's own tools besides the 黄历: the one-call reading, the 属相, the long-term memory."""
    return [fast.daily_schema(), ZODIAC_SCHEMA] + memory_tool_schemas()


class Session:
    """The live state of the conversation. One instance per running app."""

    def __init__(self, folder: Path | None = None, now: datetime | None = None):
        self.folder = folder              # None: keep in memory only (history switched off)
        self.zodiac: str | None = None    # the user's 属相, set from the config by the pet
        self.on_zodiac: Callable[[str], None] | None = None    # the user told 小瓜 a new 属相
        self.memory = None                # companion.memory.Memory, set by the pet
        self.trash = None                 # companion.trash.Trash: deleted conversations wait there 30 days
        self.on_memory: Callable[[], None] | None = None       # a fact was added, dropped or closed
        self.first_day: date | None = None                     # the day 小瓜 was first opened (config)
        self.turn_tag: str | None = None  # id of the question being answered; its turn carries it
        self.greeting_kind = "morning"
        now = now or _now()
        self.chats = ChatStore(folder / "chats" if folder else None)
        self.chat = self._resume_chat(now)

    # -- persistence --------------------------------------------------------
    def save_chat(self) -> None:
        self.chats.save(self.chat)

    def set_folder(self, folder: Path | None) -> None:
        """History switched on or off in the settings."""
        self.folder = folder
        self.chats.folder = folder / "chats" if folder else None
        self.save_chat()

    # -- conversations (会话) ----------------------------------------------------
    def _resume_chat(self, now: datetime) -> Chat:
        """Carry on with today's latest conversation; otherwise a fresh one."""
        for entry in self.chats.list():
            if entry["updated"][:10] == now.date().isoformat():
                chat = self.chats.load(entry["id"])
                if chat is not None:
                    return chat
            break
        return new_chat(now)

    def list_chats(self) -> list[dict]:
        """Every conversation, newest first; the open one is included even before it is saved."""
        chats = self.chats.list()
        if not any(c["id"] == self.chat.id for c in chats):
            chats.insert(0, {"id": self.chat.id, "title": self.chat.title or "新对话",
                             "updated": self.chat.updated, "count": len(self.chat.messages)})
        return chats

    def new_chat(self, now: datetime | None = None) -> Chat:
        """新对话: a clean thread; the old one stays in the list."""
        if not self.chat.empty:
            self.chat = new_chat(now or _now())
        return self.chat

    def begin_turn(self, now: datetime | None = None) -> None:
        """Called before each question: a conversation from an earlier day is left as it was,
        and today's talk starts a new one."""
        now = now or _now()
        if not self.chat.empty and self.chat.updated[:10] != now.date().isoformat():
            self.chat = new_chat(now)

    def switch_chat(self, chat_id: str) -> Chat | None:
        if chat_id == self.chat.id:
            return self.chat
        chat = self.chats.load(chat_id)
        if chat is not None:
            self.chat = chat
        return chat

    def delete_chat(self, chat_id: str, now: datetime | None = None) -> None:
        """删除整个对话: into the trash (30 days), out of the list; the model no longer sees it."""
        chat = self.chat if chat_id == self.chat.id else self.chats.load(chat_id)
        if chat is not None and not chat.empty and self.trash is not None and self.chats.folder is not None:
            self.trash.put("对话", chat.title or "（没有标题的对话）", asdict(chat), now)
        self.chats.delete(chat_id)
        if chat_id == self.chat.id:
            self.chat = new_chat(now or _now())

    def restore_chat(self, data: dict) -> str | None:
        """A conversation back from the trash, under a fresh id if the old one is taken. Returns its id."""
        if self.chats.folder is None:
            return None
        fields = asdict(Chat(id=""))
        chat = Chat(**{k: data.get(k, v) for k, v in fields.items()})
        if not chat.id or chat.id == self.chat.id or self.chats.load(chat.id) is not None:
            chat.id = new_chat(_now()).id
        self.chats.save(chat)
        return chat.id

    # -- tools ----------------------------------------------------------------
    def _shared_tool(self, name: str, arguments: dict, now: datetime) -> dict | None:
        """属相 and long-term memory. None: not one of these."""
        if name == "remember_zodiac":
            zodiac = str(arguments.get("zodiac", "")).strip().removeprefix("属")
            try:
                almanac.zodiac_branch(zodiac)
            except ValueError as error:
                return {"status": "INVALID_INPUT", "error": str(error)}
            self.zodiac = zodiac
            if self.on_zodiac is not None:
                self.on_zodiac(zodiac)
            return {"status": "OK", "zodiac": zodiac, "note": "记住了，之后看黄历按这个属相。"}
        if name in MEMORY_TOOLS:
            if self.memory is None:
                return {"status": "UNAVAILABLE", "note": "这次没有长期记忆可用"}
            result = self.memory.tool(name, arguments, now.date(), now)
            if result.get("status") == "OK" and self.on_memory is not None:
                self.on_memory()
            return result
        return None

    def run_daily_tool(self, name: str, arguments: dict, now: datetime | None = None) -> dict:
        shared = self._shared_tool(name, arguments, now or _now())
        if shared is not None:
            return shared
        if name == "daily_reading":
            return self._daily_reading(arguments)
        if name in ("almanac_day", "almanac_pick_days") and not arguments.get("zodiac") and self.zodiac:
            arguments = {**arguments, "zodiac": self.zodiac}
        return tools.run_tool(name, arguments)

    run_tool = run_daily_tool

    def _daily_reading(self, arguments: dict) -> dict:
        """起卦 + 查卦义 + 依据核对 for one concrete matter."""
        question = str(arguments.get("question") or "").strip()
        cast = tools.cast_now(question)
        if cast.get("status") != "OK":
            return cast
        topic = arguments.get("topic") if arguments.get("topic") in fast.TOPIC_EVIDENCE else "其他"
        meanings = tools.lookup_hexagrams(fast.hexagram_names(cast))["hexagrams"]
        gate = fast.check(fast.daily_record(cast, topic, question))
        first = ({"answer_first": "他问的是能不能 / 行不行：第一句先给结论（「能成」「悬」「先别签」），十来个字，卦放后面讲。"}
                 if harness.YES_NO.search(question) else {})
        return {"status": "OK", "gate": gate["status"], **({"gate_errors": gate["errors"]} if gate["errors"] else {}),
                **first, "topic": topic, "cast": fast.cast_brief(cast),
                "meanings": {n: f"{m['pattern']}；{m['hint']}" for n, m in meanings.items()}}

    # -- what the model sees ------------------------------------------------
    def long_term_blocks(self, now: datetime) -> list[str]:
        """【小瓜记得的你】: facts the user told."""
        return [self.memory.context_text(now.date())] if self.memory is not None else []

    def daily_context_text(self, now: datetime | None = None) -> str:
        now = now or _now()
        return "\n\n".join([daily_context_text(self.zodiac, now)] + self.long_term_blocks(now))

    def together_text(self, now: datetime | None = None) -> str | None:
        """「陪你第 15 天 · 聊过 23 段对话」, for the chat's welcome and the memory page."""
        today = (now or _now()).date()
        first = self.first_day or today
        talks = sum(1 for c in self.list_chats() if c.get("count"))
        line = f"陪你第 {(today - first).days + 1} 天"
        return line + (f" · 聊过 {talks} 段对话" if talks else "")

    def greeting(self, now: datetime | None = None, mark: bool = True) -> str:
        """The first thing 小瓜 says on a new day, made by code (no model, no wait).

        A plan for today comes first, then one past plan to ask about (asked once),
        else today's 黄历 for the user's 属相. A 节气 today or tomorrow is mentioned.
        """
        now = now or _now()
        today = now.date()
        page = almanac.day_almanac(today, self.zodiac or None)
        you = page.get("for_you")
        clock = f"{now:%H:%M}"
        hours = you["good_hours"] if you else [f"{h['branch']} {h['range']}" for h in page["hours"]
                                               if h["luck"] == "吉"]
        ahead = [h for h in hours if h.split("-")[-1] > clock]
        hour = harness.hour_words(ahead[0]) if ahead else None
        fit = f"跟你属{you['zodiac']}{TONE_WORDS[you['day_tone']]}" if you else None
        due = self.memory.due(today) if self.memory else []
        follow = self.memory.to_follow_up(today) if self.memory else []
        self.greeting_kind = "plan" if (due or follow) else "morning"
        if due:
            line = f"别忘了今天的事：{'、'.join(f.text for f in due[:2])}。"
            extra = [x for x in (fit and f"日子{fit}", hour and f"{hour}好") if x]
            if extra:
                line += "，".join(extra) + "。"
        elif follow:
            fact = follow[0]
            day = fact.day()
            line = f"{day.month}月{day.day}日的「{fact.text}」怎么样了？跟我说说。"
            if mark:
                self.memory.mark_asked([fact])
        else:
            yi = [i["plain"] for i in page["yi"] if not i.get("funeral")][:3]
            ji = [i["plain"] for i in page["ji"] if not i.get("funeral")][:3]
            line = "今天" + (f"宜{'、'.join(yi)}" if yi else "宜的多是丧葬事，平常照常过")
            line += (f"，忌{'、'.join(ji)}" if ji else "") + "。"
            if fit:
                line += fit + (f"，{hour}好" if hour else "") + "。"
            else:
                line += "告诉我你属什么，帮你看今天跟你合不合。"
        if page["solar_term"]:
            line = f"今天{page['solar_term']}。" + line
        else:
            tomorrow = almanac.day_almanac(today + timedelta(days=1))["solar_term"]
            if tomorrow:
                line += f"明天{tomorrow}。"
        return line

    def recent_daily_messages(self) -> list[dict]:
        """The conversation's earlier Q&A as plain messages, newest kept first within the budget."""
        picked, used = [], 0
        for turn in reversed(self.chat.daily):
            size = len(turn["q"]) + len(turn["a"])
            if picked and used + size > RECENT_TURN_CHARS:
                break
            picked.append(turn)
            used += size
        messages = []
        for turn in reversed(picked):
            messages += [{"role": "user", "content": turn["q"]},
                         {"role": "assistant", "content": turn["a"]}]
        return messages

    def record_daily_turn(self, question: str, answer: str, now: datetime | None = None) -> None:
        now = now or _now()
        self.chat.daily.append({"q": question, "a": answer, "at": now.isoformat(), "id": self.turn_tag})
        self.chat.updated = now.isoformat()
        self.save_chat()

    # -- what the chat shows ------------------------------------------------
    def log_message(self, role: str, text: str, now: datetime | None = None,
                    reply_to: str | None = None) -> str:
        """Keep one chat line; returns its id (an answer points at its question by `reply_to`)."""
        now = now or _now()
        message_id = uuid.uuid4().hex[:10]
        entry = {"id": message_id, "role": role, "text": text, "at": now.isoformat()}
        if reply_to:
            entry["reply_to"] = reply_to
        if role == "mine":
            self.chat.entitle(text)
        self.chat.messages.append(entry)
        self.chat.updated = now.isoformat()
        self.save_chat()
        return message_id

    def message(self, message_id: str) -> dict | None:
        return next((m for m in self.chat.messages if m.get("id") == message_id), None)

    def _drop_turn(self, question_id: str) -> None:
        """The model forgets one exchange."""
        self.chat.daily[:] = [t for t in self.chat.daily if t.get("id") != question_id]

    def forget_exchange(self, question_id: str) -> list[str]:
        """撤回: a question and everything answering it go, from the chat log and the model's context."""
        removed = [m["id"] for m in self.chat.messages
                   if m.get("id") == question_id or m.get("reply_to") == question_id]
        self.chat.messages = [m for m in self.chat.messages if m.get("id") not in removed]
        self._drop_turn(question_id)
        self._save_or_drop_chat()
        return removed

    def _save_or_drop_chat(self) -> None:
        """A conversation whose last message was deleted is gone, not an empty file."""
        if self.chat.empty:
            self.chats.delete(self.chat.id)
        else:
            self.save_chat()

    def forget_message(self, message_id: str) -> list[str]:
        """删除 one message. A question takes its answer with it; an answer alone leaves the question
        on screen but the model forgets that exchange either way. Returns the ids removed."""
        message = self.message(message_id)
        if message is None:
            return []
        if message["role"] == "mine":
            return self.forget_exchange(message_id)
        self.chat.messages = [m for m in self.chat.messages if m.get("id") != message_id]
        if message.get("reply_to"):
            self._drop_turn(message["reply_to"])
        self._save_or_drop_chat()
        return [message_id]

    def reset(self, now: datetime | None = None) -> None:
        """After 删除全部记录: no conversation, nothing in memory from before."""
        self.chat = new_chat(now or _now())


def forget_everything(folder: Path) -> int:
    """Delete every stored conversation. Returns how many files were removed."""
    count = 0
    if folder.is_dir():
        for path in list(folder.glob("*.json")) + list((folder / "chats").glob("*.json")):
            path.unlink()
            count += 1
    return count
