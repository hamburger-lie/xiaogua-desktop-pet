"""Long-term memory: what 小瓜 remembers about the user across days.

Owned by code (the model reads them, it does not keep them): facts the user told 小瓜: 称呼, 偏好, 计划 (with a date), 其他. Added through the
  remember_fact tool when the user says something worth keeping, listed and
  deletable in 设置 → 记忆. Stored in memory.json next to config.json, text only.

A plan with a date is followed up by code: on the day the morning greeting
mentions it; after the day 小瓜 asks once how it went (Session.greeting).
A plan with a time as well is a reminder: at that minute 小瓜 waves and says it
(Pet.check_reminders), whatever 主动说话 is set to, since the user asked for it.
The 属相 lives in the config (settings field), not here.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

KINDS = ("称呼", "偏好", "计划", "其他")
_REMIND_WORDS = re.compile(r"^(?:到点|记得)?(?:提醒|叫)(?:我|他)?(?:一下|一声)?[，,：:]?")
MAX_FACTS = 80                # oldest finished plans go first when full
MAX_TEXT = 60
PLAN_AHEAD_DAYS = 60          # plans shown to the model: this far ahead …
PLAN_BEHIND_DAYS = 14         # … and this far back (until they have an outcome)
WEEKDAY = "一二三四五六日"
# A plan's day lives in `date`; a day repeated in its text (「10月11日周日搬家」) is cut off.
_LEADING_DAY = re.compile(r"^(?:\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}[日号]?|(?:下下|下|这|本)?(?:周|星期|礼拜)[一二三四五六日天]"
                          r"|今天|明天|后天|大后天|[，,、 ])+")


@dataclass
class Fact:
    id: str
    kind: str
    text: str
    created: str                  # ISO date it was learnt
    date: str | None = None       # 计划: the day it happens
    outcome: str | None = None    # 计划: how it went, once the user said
    asked: bool = False           # 计划: the follow-up question was asked
    source: str = "对话"
    time: str | None = None       # 计划: 「15:00」, remind at that minute
    reminded: bool = False        # 计划: the reminder was given

    def day(self) -> date | None:
        return date.fromisoformat(self.date) if self.date else None

    def label(self, today: date) -> str:
        """「计划 10月11日（周日，4天后）：搬家」, as the model and the settings list show it."""
        if self.kind != "计划" or not self.date:
            return f"{self.kind}：{self.text}"
        day = self.day()
        delta = (day - today).days
        when = ("今天" if delta == 0 else "明天" if delta == 1 else "昨天" if delta == -1
                else f"{delta}天后" if delta > 0 else f"{-delta}天前")
        line = f"计划 {day.month}月{day.day}日（周{WEEKDAY[day.weekday()]}，{when}）"
        if self.time:
            line += f"{self.time} {'已提醒' if self.reminded else '到点提醒'}"
        line += f"：{self.text}"
        if self.outcome:
            line += f"（结果：{self.outcome}）"
        elif delta < 0:
            line += "（问过结果，等他回答）" if self.asked else "（已过，还不知道结果）"
        return line


class Memory:
    """memory.json: the facts, read and written whole (a few KB at most)."""

    def __init__(self, path: Path | None = None):
        self.path = path                      # None: in memory only (tests)
        self.facts: list[Fact] = []
        self.trash = None                     # companion.trash.Trash: forgotten facts wait there 30 days
        self._lock = threading.Lock()         # tools run on the worker thread, deletes on the UI thread
        if path and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.facts = [Fact(**f) for f in data.get("facts", [])]
            except (OSError, ValueError, TypeError):
                self.facts = []

    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        data = {"schema": "xiaogua-memory-v1", "facts": [asdict(f) for f in self.facts]}
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(self.path)

    def _next_id(self) -> str:
        used = {int(f.id[1:]) for f in self.facts if f.id[1:].isdigit()}
        return f"m{max(used, default=0) + 1}"

    def find(self, fact_id: str) -> Fact | None:
        return next((f for f in self.facts if f.id == str(fact_id).strip("[] ")), None)

    # -- changes ------------------------------------------------------------
    def add(self, kind: str, text: str, when: str | None = None, today: date | None = None,
            source: str = "对话", at: str | None = None, now: datetime | None = None) -> dict:
        today = today or date.today()
        text = " ".join(str(text or "").split())
        if kind not in KINDS:
            return {"status": "INVALID_INPUT", "error": f"kind 只能是 {list(KINDS)}"}
        if not text or len(text) > MAX_TEXT:
            return {"status": "INVALID_INPUT", "error": f"text 要是一句 {MAX_TEXT} 字以内的短句"}
        if at and kind != "计划":
            return {"status": "INVALID_INPUT", "error": "到点提醒用 kind=计划，带 time"}
        at = clock(at) if at else None
        if at == "":
            return {"status": "INVALID_INPUT", "error": "time 要是 24 小时制的 HH:MM，如 15:00"}
        if kind == "计划":
            when = when or (today.isoformat() if at else None)     # 「三点提醒我」: today
            try:
                day = date.fromisoformat(when or "")
            except ValueError:
                return {"status": "INVALID_INPUT", "error": "计划要带 date（YYYY-MM-DD），按【今天】换算"}
            if at and now is not None and (day, at) < (now.date(), f"{now:%H:%M}"):
                return {"status": "INVALID_INPUT",
                        "error": f"{day.isoformat()} {at} 已经过了（现在 {now:%m-%d %H:%M}），按【现在】重新换算"}
            text = _LEADING_DAY.sub("", text) or text
            if at:
                text = _REMIND_WORDS.sub("", text) or text      # 「提醒我喝水」: the reminder says 「到点啦：喝水」
        else:
            when = None
        with self._lock:
            same = next((f for f in self.facts if f.kind == kind and f.text == text and f.date == when
                         and f.time == at), None)
            if same:
                return {"status": "ALREADY_KNOWN", "fact": same.label(today), "id": same.id}
            if kind == "称呼":                       # one name at a time: the newest wins
                self.facts = [f for f in self.facts if f.kind != "称呼"]
            fact = Fact(self._next_id(), kind, text, today.isoformat(), when, source=source, time=at)
            self.facts.append(fact)
            self._trim()
            self.save()
        out = {"status": "OK", "id": fact.id, "fact": fact.label(today)}
        if at:
            day = fact.day()
            out["remind_at"] = f"{'今天' if day == today else f'{day.month}月{day.day}日'} {at}"
            out["note"] = "回答里说一句几点提醒他（如「好，15:00 叫你」），他好核对。"
        return out

    def _trim(self) -> None:
        while len(self.facts) > MAX_FACTS:
            finished = [f for f in self.facts if f.kind == "计划" and f.outcome]
            self.facts.remove(finished[0] if finished else self.facts[0])

    def forget(self, fact_id: str) -> dict:
        with self._lock:
            fact = self.find(fact_id)
            if fact is None:
                return {"status": "NOT_FOUND", "id": fact_id}
            self.facts.remove(fact)
            self.save()
        self._to_trash([fact])
        return {"status": "OK", "forgot": fact.text}

    def _to_trash(self, facts: list[Fact]) -> None:
        if self.trash is not None:
            for fact in facts:
                self.trash.put("记忆", fact.label(date.today()), asdict(fact))

    def restore(self, data: dict) -> dict:
        """A fact back from the trash (under a new id if its old one was given out since)."""
        try:
            fact = Fact(**{k: v for k, v in data.items() if k in Fact.__dataclass_fields__})
        except TypeError:
            return {"status": "INVALID_INPUT"}
        with self._lock:
            if self.find(fact.id) is not None:
                fact.id = self._next_id()
            self.facts.append(fact)
            self._trim()
            self.save()
        return {"status": "OK", "id": fact.id, "fact": fact.label(date.today())}

    def close(self, fact_id: str, outcome: str) -> dict:
        outcome = " ".join(str(outcome or "").split())[:MAX_TEXT]
        with self._lock:
            fact = self.find(fact_id)
            if fact is None or fact.kind != "计划":
                return {"status": "NOT_FOUND", "id": fact_id, "note": "只有计划能记结果"}
            if not outcome:
                return {"status": "INVALID_INPUT", "error": "outcome 不能为空"}
            fact.outcome = outcome
            self.save()
        return {"status": "OK", "fact": fact.text, "outcome": outcome}

    def clear(self) -> int:
        with self._lock:
            gone, self.facts = self.facts, []
            self.save()
        self._to_trash(gone)
        return len(gone)

    def due_reminders(self, now: datetime) -> list[Fact]:
        """Today's reminders whose minute has come and that were not given yet."""
        today, minute = now.date(), f"{now:%H:%M}"
        return [f for f in self.facts if f.kind == "计划" and f.time and not f.reminded and not f.outcome
                and f.day() == today and f.time <= minute]

    def mark_reminded(self, facts: list[Fact]) -> None:
        with self._lock:
            for fact in facts:
                fact.reminded = True
            self.save()

    def mark_asked(self, facts: list[Fact]) -> None:
        with self._lock:
            for fact in facts:
                fact.asked = True
            self.save()

    # -- reading ------------------------------------------------------------
    def due(self, today: date) -> list[Fact]:
        """Plans for today, not yet done."""
        return [f for f in self.facts if f.kind == "计划" and f.day() == today and not f.outcome]

    def to_follow_up(self, today: date) -> list[Fact]:
        """Past plans whose outcome is unknown and that were never asked about."""
        return [f for f in self.facts if f.kind == "计划" and f.day() and not f.outcome and not f.asked
                and 0 < (today - f.day()).days <= PLAN_BEHIND_DAYS]

    def shown(self, today: date) -> list[Fact]:
        """What the model is given: every non-plan fact, and plans near today."""
        out = []
        for fact in self.facts:
            if fact.kind != "计划":
                out.append(fact)
                continue
            delta = (fact.day() - today).days
            if -PLAN_BEHIND_DAYS <= delta <= PLAN_AHEAD_DAYS and not (delta < 0 and fact.outcome):
                out.append(fact)
        return sorted(out, key=lambda f: (f.kind == "计划", f.date or "", f.id))

    def context_text(self, today: date) -> str:
        facts = self.shown(today)
        if not facts:
            return "【小瓜记得的你】还没有。他说了以后还用得上的事（称呼、偏好、带日期的计划），调 remember_fact 记下。"
        return "【小瓜记得的你】\n" + "\n".join(f"[{f.id}] {f.label(today)}" for f in facts)

    def tool(self, name: str, arguments: dict, today: date | None = None, now: datetime | None = None) -> dict:
        today = today or (now.date() if now else date.today())
        if name == "remember_fact":
            return self.add(arguments.get("kind", ""), arguments.get("text", ""), arguments.get("date"), today,
                            at=arguments.get("time"), now=now)
        if name == "forget_fact":
            return self.forget(arguments.get("id", ""))
        if name == "close_fact":
            return self.close(arguments.get("id", ""), arguments.get("outcome", ""))
        return {"status": "UNKNOWN_TOOL", "tool": name}


MEMORY_TOOLS = ("remember_fact", "forget_fact", "close_fact")


def memory_tool_schemas() -> list[dict[str, Any]]:
    _str = {"type": "string"}
    return [
        {"name": "remember_fact",
         "description": "用户说了以后还用得上的事时调用：称呼（「叫我老王」）、偏好（「我一般打绝密」「说话直接点」）、"
                        "带日期的计划（「周五面试」「11号搬家」，date 按【今天】换算成 YYYY-MM-DD）。"
                        "text 只写事、不写日期（「面试」「搬家」，日期放 date）。一次性的问题、病情、具体金额、别人的隐私不记，除非他明说「记住」。"
                        "要小瓜到点提醒的（「三点提醒我交报告」「十分钟后叫我」「到好时辰叫我」）：kind=计划，带 time，"
                        "小瓜到那一分钟会招手提醒他。"
                        "属相用 remember_zodiac。",
         "input_schema": {"type": "object", "properties": {
             "kind": {"type": "string", "enum": list(KINDS)}, "text": _str,
             "date": {"type": "string", "description": "计划发生的公历日期 YYYY-MM-DD；不是计划就不传"},
             "time": {"type": "string", "description": "到点提醒的钟点，24 小时制 HH:MM。只在他要提醒、或计划有具体钟点时传；"
                                                       "「X 分钟后」按【现在】换算；只给 time 不给 date 就是今天"}},
             "required": ["kind", "text"]}},
        {"name": "forget_fact",
         "description": "【小瓜记得的你】里某条不对了、取消了、他说别记了，按编号删掉（如 m3）。",
         "input_schema": {"type": "object", "properties": {"id": _str}, "required": ["id"]}},
        {"name": "close_fact",
         "description": "带日期的计划有结果了（「搬完了，挺顺」「面试没过」），按编号记下结果，一句话。",
         "input_schema": {"type": "object", "properties": {"id": _str, "outcome": _str},
                          "required": ["id", "outcome"]}},
    ]


def clock(text: str | None) -> str:
    """「15:00」「9:5」「15：00」 -> 「15:00」 / 「09:05」; "" when it is not a time of day."""
    match = re.fullmatch(r"\s*(\d{1,2})[:：](\d{1,2})\s*", str(text or ""))
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return ""
    return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
