"""The harness around 小瓜's answers: what the prompt asks for, code makes sure of.

A prompt is a request the model may ignore, and when it does, nothing notices.
Every rule here is one the model was seen breaking, turned into code at the one
place every answer passes (agent.ask, after the evidence gate):

  repairs  wording rules code can fix itself without changing what is said: 破折号,
           markdown, stock phrases, words that say too much (必然、注定), evidence ids.
           Applied silently, no extra wait. The chat window applies them to the
           streamed draft too, so a dash never flashes on screen.
  facts    claims code can check against what it worked out itself. Now: 好时辰.
           A wrong one is sent back to the model once, with the right hours; if it
           is still wrong, code takes the sentence out and says the hours itself.
  casts    a hexagram named in the answer must be one that was cast: this turn's tools or the
           talk so far. One the model made up goes back once; still there, the
           sentences with it are taken out.
  shape    how an answer is built: a 能不能 question answered with the verdict first,
           and no answer far longer than asked for. Sent back once; if the second try
           still misses, it goes out as it is (code cannot rewrite the model's thought).
           One send-back per answer in all, whatever the reasons.

Each answer's findings go into Reply.checks and the log, so how often the model
slips stays measurable (tools/eval_answers.py runs a fixed question set live).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache

# --- repairs ------------------------------------------------------------------

_IDS = r"(?:MH|WORK|COOP|MONEY|REL|GUARD|TIME|FIND|SPACE)-\d{2}"

REPAIRS: list[tuple[str, re.Pattern, str]] = [(name, re.compile(pattern), repl) for name, pattern, repl in (
    ("破折号", r"[ \t]*(?:——|—|－－|--)+[ \t]*", "，"),
    ("加粗", r"\*\*(.+?)\*\*", r"\1"),
    ("小标题", r"(?m)^[ \t]{0,3}#{1,6}[ \t]*", ""),
    ("清单符号", r"(?m)^[ \t]*(?:[-*•·][ \t]+|\d{1,2}[.)][ \t]+|\d{1,2}、)", ""),
    ("证据编号", rf"[（(][ \t]*{_IDS}(?:[ \t]*[、,，/][ \t]*{_IDS})*[ \t]*[)）]|{_IDS}", ""),
    ("套话", r"(?:值得注意的是|一句话总结|总而言之|综上所述|总之|首先)[，,：:]?", ""),
    ("套话", r"其次[，,]?", "然后"),
    ("套话", r"小瓜觉得[，,]?", ""),
    ("套话", r"不建议你", "最好别"),
    ("套话", r"我?建议你", "你"),
    ("说死", r"天机不可泄露[，,。！!]?", ""),
    ("说死", r"一定成功", "多半能成"),
    ("说死", r"必然|注定", "多半"),
    ("说死", r"百分之百|百分百", "八成"),
    ("说死", r"逃不过", "躲不太开"),
    ("说死", r"大凶", "不太好"),
    ("说死", r"血光之灾", "磕碰"),
)]

_TIDY = [(re.compile(p), r) for p, r in (
    (r"[，,]{2,}", "，"),
    (r"[，,]([。！？!?；;：:])", r"\1"),
    (r"([。！？!?；;：:（(])[，,]", r"\1"),
    (r"(?m)^[ \t]*[，,][ \t]*", ""),
    (r"[，,][ \t]*$", "。"),
    (r"(?m)[，,][ \t]*\n", "。\n"),
    (r"\n{3,}", "\n\n"),
)]


def polish(text: str) -> tuple[str, list[str]]:
    """Apply the wording repairs. Returns the text and one entry per kind fixed, e.g. 「破折号×2」."""
    counts: dict[str, int] = {}
    for name, pattern, repl in REPAIRS:
        text, n = pattern.subn(repl, text)
        if n:
            counts[name] = counts.get(name, 0) + n
    if counts:
        for pattern, repl in _TIDY:
            text = pattern.sub(repl, text)
    return text.strip(), [f"{name}×{n}" for name, n in counts.items()]


# --- 时辰 -----------------------------------------------------------------------

BRANCH_HOURS = {"子": (0, 1), "丑": (1, 3), "寅": (3, 5), "卯": (5, 7), "辰": (7, 9), "巳": (9, 11),
                "午": (11, 13), "未": (13, 15), "申": (15, 17), "酉": (17, 19), "戌": (19, 21), "亥": (21, 23)}
_CN = "零一二三四五六七八九"
_HOUR_WORDS = ["十二", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一"]


def _period(hour: int) -> str:
    for end, word in ((1, "半夜"), (5, "凌晨"), (8, "早上"), (11, "上午"), (13, "中午"),
                      (17, "下午"), (19, "傍晚"), (23, "晚上")):
        if hour < end:
            return word
    return "深夜"


def clock_words(start: int, end: int) -> str:
    """17, 19 -> 「傍晚五点到七点」: the way a person says a 时辰."""
    return f"{_period(start)}{_HOUR_WORDS[start % 12]}点到{_HOUR_WORDS[end % 12]}点"


def hour_words(entry: str) -> str:
    """「酉时 17:00-18:59」 -> 「酉时（傍晚五点到七点）」."""
    branch = entry[0]
    start, end = BRANCH_HOURS.get(branch, (None, None))
    return f"{branch}时（{clock_words(start, end)}）" if start is not None else entry


@dataclass
class DayHours:
    label: str                       # 「今天」 or 「10月9日」
    branches: list[str]              # good 时辰 for the user, in order: 「酉」…
    ahead: list[str] = field(default_factory=list)    # today's not yet passed

    def spans(self) -> list[tuple[float, float]]:
        return [BRANCH_HOURS[b] for b in self.branches]

    def words(self, which: list[str] | None = None) -> str:
        return "、".join(f"{b}时（{clock_words(*BRANCH_HOURS[b])}）" for b in (which or self.branches))


@dataclass
class Facts:
    """What code worked out this turn that an answer may be checked against."""
    today: date | None = None
    now: datetime | None = None
    days: list[DayHours] = field(default_factory=list)
    question: str = ""                 # the user's words: is it a 能不能 question?
    max_chars: int = 0                 # longest answer sent out as is (0: no limit)
    hexagrams: set[str] = field(default_factory=set)   # cast this turn, on the card, or said earlier

    def add_page(self, page: dict) -> None:
        """A 黄历 page (engines/almanac.day_almanac or the almanac_day tool): its good hours for the user,
        or every 吉 hour when the 属相 is unknown."""
        if not isinstance(page, dict) or page.get("status") != "OK" or not page.get("hours"):
            return
        you = page.get("for_you")
        entries = you["good_hours"] if you else [f"{h['branch']} {h['range']}" for h in page["hours"]
                                                 if h.get("luck") == "吉"]
        branches = [e[0] for e in entries if e[0] in BRANCH_HOURS]
        day = date.fromisoformat(page["date"])
        label = "今天" if day == self.today else f"{day.month}月{day.day}日"
        if any(d.label == label for d in self.days):
            return
        ahead = []
        if day == self.today and self.now is not None:
            ahead = [b for b in branches if BRANCH_HOURS[b][1] > self.now.hour + self.now.minute / 60]
        self.days.append(DayHours(label, branches, ahead))

    def allowed(self) -> tuple[set[str], list[tuple[float, float]]]:
        branches = {b for d in self.days for b in d.branches}
        spans = sorted(BRANCH_HOURS[b] for b in branches)
        merged: list[list[float]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return branches, [(s, e) for s, e in merged]

    def sentence(self) -> str:
        """What code says in place of a wrong 时辰 sentence."""
        parts = []
        for day in self.days[:2]:
            if day.label == "今天":
                if day.ahead:
                    parts.append(f"今天还没过的好时辰是{day.words(day.ahead[:2])}")
                else:
                    parts.append("今天的好时辰都过了")
            elif day.branches:
                parts.append(f"{day.label}的好时辰是{day.words(day.branches[:3])}")
        return ("，".join(parts) + "。") if parts else ""

    def listing(self) -> str:
        lines = []
        for day in self.days:
            shown = day.ahead if day.label == "今天" and day.ahead else day.branches
            lines.append(f"{day.label}：{day.words(shown) if shown else '没有'}")
        return "；".join(lines)


_NUM = r"(?:[零〇一二两三四五六七八九十]{1,3}|\d{1,2})"
_PERIOD = r"(?:凌晨|半夜|深夜|早上|早晨|清早|一早|今早|上午|中午|正午|午后|下午|傍晚|黄昏|晚上|夜里|夜间|晚间|今晚)"
_UNIT = r"(?:点|时(?![辰候间期代光机常段]))"
_MIN = r"(?:[:：](?P<{0}>\d{{2}})|(?P<{1}>半))?"
_RANGE = re.compile(rf"(?P<p1>{_PERIOD})?(?P<a>{_NUM})(?:{_UNIT}|(?=[:：]))?{_MIN.format('am', 'ah')}[ \t]*"
                    rf"(?:到|至|~|～|-|－|–|—)[ \t]*(?P<p2>{_PERIOD})?(?P<b>{_NUM})"
                    rf"(?:{_UNIT}{_MIN.format('bm', 'bh')}|[:：](?P<bm2>\d{{2}}))")
_POINT = re.compile(rf"(?P<p>{_PERIOD})?(?P<n>{_NUM})(?:{_UNIT}{_MIN.format('m', 'h')}|[:：](?P<m2>\d{{2}}))"
                    rf"(?![儿个])(?P<open>以前|之前|前|以后|之后|往后|过后|后)?")
# A 时辰 by name; the look-arounds keep 孩子时、上午时间、尚未时、重申时、良辰时 out.
_BRANCH = re.compile(r"(?<![孩儿日样面君弟男女妻父分种鸭帽房车本句圈脑上下尚从并还仍重延引良生诞小])"
                     r"([子丑寅卯辰巳午未申酉戌亥])时(?![候间期代光机常段])")
_NEGATIVE = re.compile(r"别|不要|避开|避一避|躲开|躲一躲|不好|不宜|不太好|不合适|凶|忌|冲你|犯冲")
_CLAIM = re.compile(r"时辰|吉时|好时|时候|时段|钟点|出门|动身|最好|合适|适合|不错|吉")
_SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]*\n?|\n")


def _number(text: str) -> int | None:
    """「十一」 -> 11, 「17」 -> 17; None for what is not one number (「五六」 is two)."""
    if text.isdigit():
        return int(text)
    text = text.replace("两", "二").replace("〇", "零")
    try:
        if "十" not in text:
            return _CN.index(text) if len(text) == 1 else None
        tens, _, ones = text.partition("十")
        if len(tens) > 1 or len(ones) > 1:
            return None
        return (_CN.index(tens) if tens else 1) * 10 + (_CN.index(ones) if ones else 0)
    except ValueError:
        return None


def _pair(text: str) -> tuple[int, int] | None:
    """「五六」 -> (5, 6), the way people say 「五六点」 for about five to seven."""
    if len(text) == 2 and "十" not in text:
        a, b = _number(text[0]), _number(text[1])
        if a is not None and b == a + 1:
            return a, b
    return None


def _hours(period: str | None, n: int) -> list[int]:
    """The 24-hour readings of 「<period> n 点」: one with a period word, both when it is left out."""
    if n > 12 or (n == 0 and period is None):
        return [n]
    if period is None:
        return [n] if n == 12 else [n, n + 12]
    if period in ("凌晨",):
        return [0 if n == 12 else n]
    if period == "半夜":
        return [0 if n == 12 else (n if n <= 6 else n + 12)]
    if period == "深夜":
        return [n + 12 if 9 <= n < 12 else (0 if n == 12 else n)]
    if period in ("早上", "早晨", "清早", "一早", "今早", "上午"):
        return [n]
    if period in ("中午", "正午"):
        return [n + 12 if n <= 3 else n]
    return [n + 12 if n < 12 else n]                     # 下午、傍晚、晚上…


def _minutes(match: re.Match, digits: tuple[str, ...], half: str | None) -> float:
    for name in digits:
        if match.group(name):
            return int(match.group(name)) / 60
    return 0.5 if half and match.group(half) else 0.0


@dataclass
class TimeClaim:
    sentence: str
    branches: list[str] = field(default_factory=list)            # 「酉时」 said by name
    spans: list[list[tuple[float, float]]] = field(default_factory=list)   # each mention: its readings
    open_ended: list[str] = field(default_factory=list)           # 「五点前」: not a 时辰 at all


def time_claims(text: str) -> list[TimeClaim]:
    """Sentences that recommend a time of day, and the times they name."""
    claims = []
    for sentence in _SENTENCE.findall(text):
        body = sentence.strip()
        if not body or _NEGATIVE.search(body) or not _CLAIM.search(body):
            continue
        claim = TimeClaim(body)
        masked = body
        for m in _RANGE.finditer(body):
            a_n, b_n = _number(m.group("a")), _number(m.group("b"))
            if a_n is None or b_n is None:
                continue
            starts = [h + _minutes(m, ("am",), "ah") for h in _hours(m.group("p1"), a_n)]
            ends = [h + _minutes(m, ("bm", "bm2"), "bh") for h in _hours(m.group("p2") or m.group("p1"), b_n)]
            readings = []
            for a in starts:
                for b in ends:
                    while b <= a:
                        b += 12
                    if b - a <= 12:
                        readings.append((a, b))
            claim.spans.append(readings)
            masked = masked[:m.start()] + "□" * (m.end() - m.start()) + masked[m.end():]
        for m in _POINT.finditer(masked):
            if m.group("p") is None and m.group("n") in ("一", "两", "二"):
                continue                              # 早一点、这两点: not a clock time without 下午 etc.
            if m.group("open"):
                claim.open_ended.append(m.group(0))
                continue
            pair, n = _pair(m.group("n")), _number(m.group("n"))
            if pair:                                  # 「傍晚五六点」: five to seven
                claim.spans.append([(h, h + 2) for h in _hours(m.group("p"), pair[0])])
            elif n is not None:
                claim.spans.append([(h + _minutes(m, ("m", "m2"), "h"),) * 2 for h in _hours(m.group("p"), n)])
        claim.branches = [m.group(1) for m in _BRANCH.finditer(masked)]
        if claim.branches or claim.spans or claim.open_ended:
            claims.append(claim)
    return claims


def wrong_hours(text: str, facts: Facts) -> list[str]:
    """The sentences that name a time outside the good 时辰 code worked out (empty when nothing to check)."""
    if not facts.days:
        return []
    branches, spans = facts.allowed()

    def inside(reading: tuple[float, float]) -> bool:
        a, b = reading
        if a == b:
            return any(s <= a < e for s, e in spans)
        return any(s <= a and b <= e + 0.02 for s, e in spans)

    wrong = []
    for claim in time_claims(text):
        bad = bool(claim.open_ended) or any(b not in branches for b in claim.branches) \
            or any(not any(inside(r) for r in readings) for readings in claim.spans)
        if bad:
            wrong.append(claim.sentence)
    return wrong


# --- shape ----------------------------------------------------------------------

DAILY_MAX_CHARS = 220          # asked for 60-150

YES_NO = re.compile(r"(.)不\1|能.{0,10}吗|行吗|可以吗|适合.{0,8}吗|合适吗|好吗|成吗|顺吗|会.{0,8}吗|[能可]否|要不要|该不该")
VERDICT = re.compile(r"能成|能行|能签|能去|能搬|能办|能过|可以|适合|合适|不太|不宜|不建议|别|不要|不行|不能|不成|成不了"
                     r"|没问题|稳|悬|缓|挪|往后放|值得|不值|去吧|签吧|^[行成能]|行[，。！,!]|成[，。！,!]"
                     r"|有戏|没戏|够呛|难成|好成|把握|不如预期|顺利|不顺")
HEDGE = re.compile(r"不好说|说不准|难说|看情况|不一定|两说")
_A_NOT_A = re.compile(r"(.)不\1")              # 成不成、行不行: the question said back, not an answer
FIRST_CHARS = 20


def length(text: str) -> int:
    return len(re.sub(r"\s", "", text))


def verdict_late(text: str, question: str) -> bool:
    """A 能不能 / 行不行 question whose answer does not open with the verdict (within the first 20
    characters, and not after a 「不好说」)."""
    if not question or not YES_NO.search(question):
        return False
    opening = _A_NOT_A.sub("", re.sub(r"\s", "", text))[:FIRST_CHARS]
    verdict, hedge = VERDICT.search(opening), HEDGE.search(opening)
    return verdict is None or (hedge is not None and hedge.start() < verdict.start())


# --- hexagrams ------------------------------------------------------------------

@lru_cache(maxsize=1)
def _hexagram_names() -> tuple[str, ...]:
    import meihua
    table = meihua.data_path("references", "hexagrams.md").read_text(encoding="utf-8")
    names = [m.group(1) for m in re.finditer(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|", table, re.M)]
    return tuple(sorted(names, key=len, reverse=True))


@lru_cache(maxsize=1)
def _hexagram_said() -> re.Pattern:
    """Where a name is a hexagram for sure: 「丰变震」「「鼎」」「鼎卦」「本卦是丰」. A bare 比、师、旅 is just a word."""
    name = "|".join(map(re.escape, _hexagram_names()))
    return re.compile(rf"(?P<a>{name})变(?P<b>{name})|「(?P<c>{name})」|(?P<d>{name})卦"
                      rf"|[本互变]卦(?:是|为)?「?(?P<e>{name})")


TRIGRAMS = set("乾坤震巽坎离艮兑")


def named_hexagrams(text: str) -> list[str]:
    """Hexagram names said as hexagrams. 「乾卦」「「离」」 are as often the 体 / 用 trigram: those count only
    in 「X变Y」 and 「本卦是X」."""
    found = []
    for match in _hexagram_said().finditer(text or ""):
        groups = match.groupdict()
        found += [groups[k] for k in ("a", "b", "e") if groups[k]]
        found += [groups[k] for k in ("c", "d") if groups[k] and groups[k] not in TRIGRAMS]
    return list(dict.fromkeys(found))


def cast_names(output: dict) -> set[str]:
    """The hexagrams in a tool's output: a cast (cast_now) or a cast brief (daily_reading)."""
    names = set()
    if not isinstance(output, dict):
        return names
    for key in ("primary", "mutual", "changed", "body", "use"):
        if isinstance(output.get(key), dict) and output[key].get("name"):
            names.add(output[key]["name"])
    brief = output.get("cast")
    if isinstance(brief, dict):
        names |= {brief[k] for k in ("本卦", "互卦", "变卦") if brief.get(k)}
        names |= {brief[k][:-1] for k in ("体", "用") if brief.get(k)}         # 「乾金」 -> 乾
        names |= cast_names(brief)
    return names


def invented_hexagrams(text: str, known: set[str]) -> list[str]:
    return [name for name in named_hexagrams(text) if name not in known]


# --- reminders ------------------------------------------------------------------

def _mentions(text: str, hhmm: str) -> bool:
    hour, minute = int(hhmm[:2]), int(hhmm[3:])
    flat = re.sub(r"\s", "", text).replace("：", ":")
    if f"{hour}:{minute:02d}" in flat or hhmm in flat:
        return True
    tens, ones = divmod(hour, 10)
    spoken = ("" if tens < 2 else _CN[tens]) + ("十" if tens else "") + (_CN[ones] if ones or not tens else "")
    words = {str(hour), str(hour % 12 or 12), _HOUR_WORDS[hour % 12], spoken}      # 15, 3, 三, 十五
    if hour % 12 == 2:
        words.add("两")                                                             # 两点
    return any(re.search(rf"(?<![\d零一二两三四五六七八九十]){w}点", flat) for w in words)


def say_reminders(text: str, reminders: list[str]) -> tuple[str, list[str]]:
    """A reminder set this turn (「今天 15:00」) the answer did not say back: code says it, so a wrong
    conversion (十分钟后 worked out wrong) is there to be seen."""
    missing = [r for r in reminders if not _mentions(text, r.split()[-1])]
    if not missing:
        return text, []
    line = "、".join(missing) + " 到点提醒你。"
    return (f"{text}\n{line}" if text else line), ["补提醒时间"]


# --- the review -----------------------------------------------------------------

@dataclass
class Review:
    text: str                                       # repaired
    fixes: list[str] = field(default_factory=list)  # 「破折号×1」…
    wrong_hours: list[str] = field(default_factory=list)
    too_long: int = 0                               # its length, when over the limit
    late_verdict: bool = False
    invented: list[str] = field(default_factory=list)  # hexagrams never cast

    @property
    def problems(self) -> bool:
        return bool(self.wrong_hours or self.too_long or self.late_verdict or self.invented)

    def sent_back(self) -> list[str]:
        """What a send-back was for, for Reply.checks and the log."""
        out = []
        if self.invented:
            out.append("退回:编卦「" + "」「".join(self.invented) + "」")
        if self.wrong_hours:
            out.append("退回:时辰「" + "」「".join(self.wrong_hours) + "」")
        if self.late_verdict:
            opening = re.sub(r"\s", "", self.text)[:FIRST_CHARS]
            out.append(f"退回:结论在后「{opening}」")
        if self.too_long:
            out.append(f"退回:太长{self.too_long}字")
        return out

    def let_through(self) -> list[str]:
        """Shape misses still there after the one send-back: the answer goes out anyway."""
        return (["仍结论在后"] if self.late_verdict else []) + ([f"仍太长{self.too_long}字"] if self.too_long else [])


def review(text: str, facts: Facts | None = None) -> Review:
    repaired, fixes = polish(text)
    if facts is None:
        return Review(repaired, fixes)
    size = length(repaired)
    return Review(repaired, fixes, wrong_hours(repaired, facts),
                  size if facts.max_chars and size > facts.max_chars else 0,
                  verdict_late(repaired, facts.question),
                  invented_hexagrams(repaired, facts.hexagrams))


def redo_message(result: Review, facts: Facts) -> str:
    asks = []
    if result.invented:
        asks.append(f"回答里说了「{'」「'.join(result.invented)}」，可这一卦没起过（这轮工具、本局卡、前面的话里都没有）。"
                    "没起卦就别说卦名卦象；要用卦先调 daily_reading，照工具给的卦说。")
    if result.wrong_hours:
        said = "」「".join(result.wrong_hours)
        asks.append(f"回答里的时辰跟程序算的黄历对不上：「{said}」。对他好的时辰只有这些：{facts.listing()}。"
                    "说时辰只能照这里的整段说，不说「几点前 / 几点后」这种。")
    if result.late_verdict:
        asks.append("他问的是能不能、行不行，第一句先给结论（「能签」「先别去」「不太合适」），十来个字，再说为什么。")
    if result.too_long:
        asks.append(f"这条有 {result.too_long} 字，太长了，压到 {facts.max_chars * 2 // 3} 字左右，只留最要紧的。")
    return "（系统）" + "".join(asks) + "把整条回答重说一遍，别的意思不变。"


def settle(result: Review, facts: Facts) -> Review:
    """Still wrong after one redo: the sentences with a wrong 时辰 or a made-up hexagram are taken
    out; code says the hours itself."""
    kept = [s for s in _SENTENCE.findall(result.text) if s.strip() not in result.wrong_hours
            and not any(name in named_hexagrams(s) for name in result.invented)]
    text = "".join(kept).strip()
    fixes = list(result.fixes)
    if result.wrong_hours:
        line = facts.sentence()
        if line:
            text = f"{text}\n{line}" if text else line
        fixes.append("时辰改由程序说")
    if result.invented:
        fixes.append("删掉编的卦")
        text = text or "这把还没起卦，小瓜不乱说卦。要看就跟我说你在哪张图、从哪出生。"
    return Review(text, fixes, [], result.too_long, result.late_verdict, [])
