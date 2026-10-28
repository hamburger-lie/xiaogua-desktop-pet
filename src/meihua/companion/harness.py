"""The harness around 小瓜's answers: what the prompt asks for, code makes sure of.

A prompt is a request the model may ignore, and when it does, nothing notices.
Every rule here is one the model was seen breaking, turned into code at the one
place every answer passes (agent.ask, after the evidence gate):

  repairs  wording rules code can fix itself without changing what is said: 破折号,
           markdown, stock phrases, words that say too much (必然、注定), evidence ids.
           Applied silently, no extra wait. The chat window applies them to the
           streamed draft too, so a dash never flashes on screen.
  facts    claims code can check against what it worked out itself. Now: 好时辰, and
           「今天是 / 明天是」 a festival or 节气. A wrong one is sent back to the model
           once, with the right facts; if it is still wrong, code takes the sentence
           out (and says the hours itself).
  casts    a hexagram named in the answer must be one that was cast: this turn's tools or the
           talk so far. One the model made up goes back once; still there, the
           sentences with it are taken out.
  systems  小瓜 does 梅花 and the 黄历, and draws 紫微、奇门、八字 and 小六壬 when named (charts.py).
           Asked for 六爻 or 风水排盘, the model is told so with the question, and an answer
           that never says it cannot gets code's honest line first. Chart words of a system
           no engine drew this turn (命宫、值符、世爻、日主…) are made up; what an answer says
           of a drawn chart (命宫在巳、巨门坐命、值使落震、日主癸、落小吉…) must be on it, and on
           every candidate chart unless both are said; the lines a system is not read for
           (寿命、婚姻成败、用神旺衰、betting, 往东南走…) are not crossed. Each is sent back once,
           then taken out. The old 「小瓜不会紫微」 is sent back once too. 风水 is space
           observation (SPACE-01): the real room comes first (no practical line at all: code
           puts the items in front), no 病灾, no dangerous renovation, no 化煞 trinkets;
           飞星排盘 is still declined.
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

_IDS = r"(?:MH|WORK|COOP|MONEY|REL|GUARD|TIME|FIND|SPACE|ZW|QM)-\d{2}"

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
    occasions: dict[str, list[str]] = field(default_factory=dict)        # 「今天」 -> its festivals and 节气
    occasion_words: dict[str, tuple[str, ...]] = field(default_factory=dict)   # 「中秋」 -> (「中秋节」,)
    charts: dict[str, list[list[dict]]] = field(default_factory=dict)  # 紫微 / 奇门 drawn this turn: each draw's charts
    gists: dict[str, list[str]] = field(default_factory=dict)          # … and its 「要点」, said back when it goes wrong
    can_draw: list[str] = field(default_factory=list)                  # named this turn and drawable (DRAWN_BY)

    @property
    def drawn(self) -> set[str]:
        return set(self.charts)

    def add_chart(self, output: dict) -> None:
        """A chart tool's result (charts.py): what an answer may say of 紫微 or 奇门 this turn."""
        if not isinstance(output, dict) or output.get("system") not in CHART_READERS \
                or output.get("status") not in ("OK", "REUSED"):
            return
        self.gists.setdefault(output["system"], []).append(output.get("要点", ""))
        if output.get("kind") == "挑时辰":
            # Each 时辰 is a chart of its own; the best ones may be recommended as hours, like the 黄历's.
            rows = output["时辰"]
            self.charts.setdefault(output["system"], []).extend([_picked_facts(row)] for row in rows)
            best =[row["时辰"][0] for row in rows if row["等级"] != "有门无奇"] or [row["时辰"][0] for row in rows]
            self.days.append(DayHours("奇门挑出的时辰", best, best))
            return
        self.charts.setdefault(output["system"], []).append(chart_facts(output))

    def chart_listing(self) -> str:
        return "；".join(gist for gists in self.gists.values() for gist in gists if gist)

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

    def occasion_listing(self) -> str:
        """「今天：没有；明天：万圣夜；后天：没有」"""
        return "；".join(f"{label}：{'、'.join(names) or '没有'}" for label, names in self.occasions.items())


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
_CHART_MOMENT = re.compile(r"出生|生于|起局|起的局|这一局|排盘|排的盘")   # 「子时出生」: a chart's hour, not advice
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
        if not body or _NEGATIVE.search(body) or not _CLAIM.search(body) or _CHART_MOMENT.search(body):
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
                     r"|有戏|没戏|够呛|难成|好成|把握|不如预期|顺利|不顺|不会")       # 「会…吗」: 不会
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


# --- festivals ------------------------------------------------------------------

OCCASION_DAYS = ("今天", "明天", "后天")
_DAY_WORDS = {"今天": "今天", "今儿": "今天", "今日": "今天", "今晚": "今天", "今夜": "今天",
              "明天": "明天", "明儿": "明天", "明日": "明天", "明晚": "明天", "后天": "后天"}
_IS = r"(?:就是|正好是|恰好是|刚好是|正是|又是|是|正逢|逢|赶上|过|交)?"
# Not about that very day: 「今天是中秋前一天」「明天国庆假期」「今天是春节后第一天」「今天小年夜」.
# 节 is here too: 「中秋节前」 must not be read as 「中秋」 + 「节前」.
_NOT_THE_DAY = r"(?![前后假期间第那左右附近当节夜])"


@lru_cache(maxsize=4)
def _occasion_said(words: tuple[str, ...]) -> re.Pattern:
    name = "|".join(map(re.escape, sorted(words, key=len, reverse=True)))
    return re.compile(rf"(?<![大前])(?P<day>{'|'.join(_DAY_WORDS)}){_IS}(?P<name>{name}){_NOT_THE_DAY}")


def wrong_occasions(text: str, facts: Facts) -> list[str]:
    """「今天是重阳节」「明天就是冬至」 said of a day whose festivals and 节气 code knows, when they are
    not that day's. Only the plain claim is checked; talk about a festival's date is left to the model."""
    if not facts.occasions or not facts.occasion_words:
        return []
    found = []
    for match in _occasion_said(tuple(facts.occasion_words)).finditer(text or ""):
        known = facts.occasions.get(_DAY_WORDS[match.group("day")])
        if known is not None and not set(facts.occasion_words[match.group("name")]) & set(known):
            found.append(match.group(0))
    return list(dict.fromkeys(found))


# --- other systems --------------------------------------------------------------
# 小瓜 does 梅花易数 and the 黄历. It also draws 紫微斗数 and 奇门遁甲 (since 2026-10-27), 八字 and 小六壬
# (10-28) when the user names one (charts.py; the evidence packs of each). Asked to work out 六爻 or
# 风水排盘, it says it cannot; the words of a chart no engine drew this turn can only be made up.

OTHER_SYSTEMS = {
    "紫微斗数": r"紫微(?:斗数)?",
    "奇门遁甲": r"奇门(?:遁甲)?",
    "六爻": r"六爻|纳甲",
    "风水排盘": r"九宫飞星|玄空飞星|飞星|宅盘|玄空|风水盘",          # 飞星: not admitted
    "风水": r"风水(?!轮流转|宝地|盘)",                                # space observation (SPACE-01)
    "八字": r"生辰八字|八字|四柱",
    "小六壬": r"[小大]?六壬",
}
# Words only a chart of that system has. Everyday words that happen to match (开门、大运、比肩、
# 坐山、动爻 — 梅花 has 动爻 too) are left out, so an honest 梅花 or 黄历 answer never trips them.
CHART_WORDS = {
    "紫微斗数": r"命宫|身宫|十四主星|主星|化禄|化权|化科|化忌|紫微星|天府星|紫微命盘",
    "奇门遁甲": r"奇门局|值符|值使|天盘|[阴阳]遁[一二三四五六七八九]局|八门|九星落",
    "六爻": r"世爻|应爻|纳甲|伏神|飞神|(?:官鬼|妻财|子孙|父母|兄弟)爻",
    "风水排盘": r"飞星盘|宅盘|替星|山星|向星|[一二三四五六七八九]运宅|玄空",
    "八字": r"日主|十神|喜用神|用神|忌神|伤官|七杀|劫财|偏印|命局|八字命盘|四柱命盘",
    "小六壬": r"(?:大安|留连|速喜|赤口|小吉|空亡)落?宫|落(?:在)?(?:大安|留连|速喜|赤口|小吉|空亡)",
}
DRAWN_BY = {"紫微斗数": "ziwei_chart", "奇门遁甲": "qimen_chart",      # drawn by charts.py
            "八字": "bazi_chart", "小六壬": "xiaoliu_chart", "风水": "space_check"}
_CURIOUS = re.compile(r"是什么|是啥|什么是|啥是|区别|不同|哪个准|准不准|准吗|靠谱|怎么来的|历史|原理|听说")
_NOT_THIS = re.compile(r"(?:不要|不用|别|不想|不是)用?$")
DECLINE = re.compile(r"不会|没学|不懂|做不了|排不了|算不了|看不了|不能[排算看]|只会|没排|不排")
REFUSE = re.compile(r"不会|没学|不懂|只会梅花|只会黄历|只会看黄历")     # the old 「小瓜不会紫微」, untrue now


def _system_hits(text: str, table: dict[str, str]) -> list[str]:
    found = []
    for name, pattern in table.items():
        for match in re.finditer(pattern, text or ""):
            if not _NOT_THIS.search(text[max(0, match.start() - 4):match.start()]):
                found.append(name)
                break
    return found


def asked_systems(question: str) -> list[str]:
    """The systems the user wants worked out (「用紫微斗数看看我」「帮我排个八字」「你会奇门吗」), not
    the ones only asked about (「紫微斗数是什么」「八字准不准」)."""
    named = _system_hits(question, OTHER_SYSTEMS)
    return [] if not named or _CURIOUS.search(question or "") else named


def _split(systems: list[str]) -> tuple[list[str], list[str]]:
    """(drawn here, not done at all)."""
    return [s for s in systems if s in DRAWN_BY], [s for s in systems if s not in DRAWN_BY]


def decline_line(systems: list[str]) -> str:
    return (f"{'、'.join(systems) or '别的术数'}小瓜不会，我只会梅花易数起卦和看黄历，点名的话也能排紫微、奇门、八字、小六壬，看房间风水。"
            "你想问的事，我可以起一卦或者翻翻黄历帮你看。")


def draw_first_line(systems: list[str]) -> str:
    lines = {"紫微斗数": "紫微斗数得先排出盘才能说：告诉我公历出生日期、几点几分和性别。",
             "奇门遁甲": "奇门遁甲得先起出局才能说，你再问我一次这件事。",
             "八字": "八字得先排出四柱才能说：告诉我公历出生日期和几点几分。",
             "小六壬": "小六壬得先起出课才能说，你再问我一次这件事。",
             "风水": "风水得先知道是哪个房间、窗朝哪、主要哪儿不舒服，跟我说说？"}
    return "".join(lines[s] for s in systems)


def honest_line(systems: list[str]) -> str:
    """What code says when every sentence of the answer had to go."""
    here, never = _split(systems)
    return (decline_line(never) if never else "") + (draw_first_line(here) if here else "")


def ask_hint(systems: list[str]) -> str:
    """Said to the model with the question, this turn only: what it draws and what it does not do."""
    here, never = _split(systems)
    parts = []
    if here:
        tools = "、".join(f"{s}调 {DRAWN_BY[s]}" + ("（问挑哪个时辰办事就调 qimen_pick）" if s == "奇门遁甲" else "")
                         for s in here)
        parts.append(f"他要的是{'、'.join(here)}，这个能排：{tools}。缺出生信息就先问，不猜；只照工具给的「盘」和「象义」说，"
                     "不凭记忆，工具没给的（星曜庙旺、格局吉凶、旺衰用神、流年流月）不说。")
    if never:
        parts.append(f"他要的是{'、'.join(never)}。小瓜只会梅花易数、{'、'.join(DRAWN_BY)}和黄历：先如实说不会，"
                     "不编这些体系的盘面和术语；他想问的事，能用梅花起卦或翻黄历的就用它们答。")
    return "（系统）" + "".join(parts)


def made_up_charts(text: str, question: str = "", drawn=()) -> list[str]:
    """Sentences with the chart words of a system no engine drew this turn. A sentence saying it cannot is
    honest, not made up; a question only asking what a system is lets that system's words through."""
    curious = set(_system_hits(question, OTHER_SYSTEMS)) if _CURIOUS.search(question or "") else set()
    table = {name: words for name, words in CHART_WORDS.items() if name not in curious and name not in drawn}
    own = "|".join(OWN_WORDS[name] for name in drawn if name in OWN_WORDS)    # 七杀 is a 紫微 star too
    return [s.strip() for s in _SENTENCE.findall(text or "") if s.strip() and not DECLINE.search(s)
            and _system_hits(re.sub(own, "□", s) if own else s, table)]


def say_cannot(text: str, systems: list[str]) -> tuple[str, list[str]]:
    """Asked for a system 小瓜 does not do and the answer never said so: code says it, first."""
    _here, never = _split(systems)
    if not never or DECLINE.search(text or ""):
        return text, []
    line = decline_line(never)
    return (f"{line}\n{text}" if text else line), ["补:不会" + "、".join(never)]


def refused_to_draw(text: str, can: list[str], drawn) -> list[str]:
    """Asked for a system it draws, nothing drawn, and the answer says 小瓜 cannot (the old line)."""
    sentences = _SENTENCE.findall(text or "")
    return [s for s in can if s not in drawn
            and any(REFUSE.search(x) and re.search(OTHER_SYSTEMS[s], x) for x in sentences)]


# What a chart is not read for (GUARD-07, references/bazi.md, XL-01), and what 奇门 is not drawn for.
_LIFE_EVENTS = {"寿命": r"寿命|寿元|短命|长寿|夭折|活不过|活多久|活到\d+", "疾病": r"疾病|得病|生病|重病|癌",
                "生育": r"不孕|生不出|生育|怀孕|生孩子|生男|生女", "子女好坏": r"子女.{0,3}(?:不孝|不好|没出息)",
                "婚姻成败": r"离婚|二婚|克夫|克妻|婚姻.{0,3}(?:失败|不成|不顺|破裂)|会不会离"}
OFF_LIMITS = {
    "紫微斗数": _LIFE_EVENTS,
    "八字": {**_LIFE_EVENTS, "伴侣忠诚": r"出轨|外遇|不忠|忠不忠", "投资收益": r"炒股|股票|基金|投资收益|稳赚|发大财",
             "旺衰用神": r"喜用神|用神|忌神|身强|身弱|旺衰|日主(?:偏|太|很|比较)?(?:强|弱|旺|衰)",
             "缺什么补什么": r"五行缺|缺[金木水火土]|补[金木水火土]"},
    "小六壬": {"指认别人": r"偷|贼"},
    "风水": {"病灾": r"生病|得病|招病|灾祸|血光|破财|招鬼|招阴|凶宅|犯煞|煞气|冲煞|不吉利",
             "危险改造": r"承重墙|拆(?:掉)?墙|改燃气|动燃气|挪燃气|改电路|私拉电线|挡(?:住)?消防|堵(?:住)?(?:消防|安全出口)",
             "推销摆件": r"开光|化煞|转运|貔貅|五帝钱|八卦镜|招财猫|风水摆件|风水球"},
    "奇门遁甲": {"赌博下注": r"赌博|赌钱|赌球|赌场|下注|押注|博彩|彩票|买球",
                 "伤人": r"报复|整人|害人|伤人|打人|弄死", "对抗执法": r"躲警察|抗法|袭警|对付警察|拒捕",
                 "逃避法律责任": r"逃避(?:法律|追查|抓捕|责任)|销毁证据"},
}
_COMPASS = re.compile(r"往[东南西北]|朝[东南西北]|向[东南西北](?:走|去|出发|坐|找)|坐[东南西北]|"
                      r"[东南西北]{1,2}(?:方|边|面|方向)(?:去|走|出发|坐|找|跑)")
_HOLDS_BACK = re.compile(r"不看|不谈|不说|不碰|不管|不算|不能|不该|别拿|不拿|不用来|不排|不起局|看不了|算不了|不取|不判|不定|"
                         r"别拆|别动|别改|别买|不要拆|不要动|不要改|不要买|千万别|不建议|不用买|不必买|不需要|"
                         r"不会[看算排]|小瓜不会|我不会|医生|医院|律师|专业的人")    # not DECLINE: 「寿命不会太长」


def off_limits(system: str, text: str) -> list[str]:
    return [name for name, pattern in OFF_LIMITS.get(system, {}).items() if re.search(pattern, text or "")]


def crossed_lines(text: str, drawn) -> list[str]:
    """Sentences of a drawn chart's answer that go where it may not: 寿命、疾病、生育、婚姻成败 from a 紫微 or
    八字 chart, and 旺衰用神 or 缺什么补什么 from 八字; betting, harm or the law, or a real-world direction
    (往东南走) from the 奇门 board; a thief named from a 小六壬 课."""
    found = []
    for sentence in _SENTENCE.findall(text or ""):
        body = sentence.strip()
        if not body or _HOLDS_BACK.search(body):
            continue
        if any(off_limits(system, body) for system in drawn) or ("奇门遁甲" in drawn and _COMPASS.search(body)):
            found.append(body)
    return found


# What the answer says of a drawn chart, read back against the chart (charts.py's 「盘」).
_ZW_STAR = ("紫微|天机|太阳|武曲|天同|廉贞|天府|太阴|贪狼|巨门|天相|天梁|七杀|破军|"
            "文昌|文曲|左辅|右弼|天魁|天钺|禄存|天马|擎羊|陀罗|火星|铃星|地空|地劫")
_ZW_PALACE = r"(命宫|兄弟宫|夫妻宫|子女宫|财帛宫?|疾厄宫?|迁移宫?|仆役宫?|交友宫|奴仆宫?|官禄宫?|事业宫|田宅宫?|福德宫?|父母宫)"
_PALACE_ALIASES = {"交友": "仆役", "奴仆": "仆役", "事业": "官禄"}
_AT = r"(?:坐落在|坐落于|坐在|坐守|落在|落入|落于|位于|坐|守|落|在|入|进|居)"
_END = r"(?:宫|位|(?=[，。,.；;、！!？?\s（()）]|$))"
_ZW_IN = re.compile(rf"({_ZW_STAR})星?{_AT}(?:你的?|了)?{_ZW_PALACE}")
_ZW_HAS = re.compile(rf"{_ZW_PALACE}(?:里|中|内|里面)?(?:的主星是|主星是|主星为|坐的是|坐着|住着|有|是|坐|为)(?:一颗|颗)?"
                     rf"((?:{_ZW_STAR})(?:(?:、|和|与|跟)(?:{_ZW_STAR}))*)")
_ZW_SITS = re.compile(rf"({_ZW_STAR})星?(?:坐命|守命|入命)")
_ZW_TRANSFORM = re.compile(rf"({_ZW_STAR})?化(禄|权|科|忌)星?(?:{_AT}(?:你的?|了)?{_ZW_PALACE})?")
_ZW_BRANCH = re.compile(rf"(命宫|身宫)(?:在|落在|落于|落|位于|是|为|安在)[甲乙丙丁戊己庚辛壬癸]?([子丑寅卯辰巳午未申酉戌亥]){_END}")
_ZW_BODY = re.compile(rf"身宫(?:在|落在|落于|落|位于|是|为|安在)(?:你的?)?{_ZW_PALACE}")
_ZW_BUREAU = re.compile(r"([水木金土火][二三四五六])局")
_ZW_MASTER = re.compile(rf"(命主|身主)星?(?:是|为)?({_ZW_STAR})")
_QM_PALACE = rf"([坎坤震巽中乾兑艮离]){_END}"
_QM_THING = r"([休生伤杜景死惊开]门|天[蓬任冲辅禽英芮柱心]|螣蛇|腾蛇|太阴|六合|白虎|玄武|九地|九天)"
_QM_TO = r"(?:落在|落于|落入|加在|落|在|临|到|居|加)了?"
_QM_JU = re.compile(r"([阴阳])遁([一二三四五六七八九])局")
_QM_FU = re.compile(r"值符星?(?:是|为)?(天[蓬任冲辅禽英芮柱心])")
_QM_FU_AT = re.compile(rf"值符星?(?:天[蓬任冲辅禽英芮柱心])?{_QM_TO}{_QM_PALACE}")
_QM_SHI = re.compile(r"值使门?(?:是|为)?([休生伤杜景死惊开]门)")
_QM_SHI_AT = re.compile(rf"值使(?:[休生伤杜景死惊开]门)?{_QM_TO}{_QM_PALACE}")
_QM_AT = re.compile(rf"{_QM_THING}星?{_QM_TO}{_QM_PALACE}")
_STEM = "[甲乙丙丁戊己庚辛壬癸]"
_BRANCH_CH = "[子丑寅卯辰巳午未申酉戌亥]"
_GODS = "比肩|劫财|食神|伤官|正财|偏财|正官|七杀|偏官|正印|偏印|枭神"
_GOD_ALIASES = {"偏官": "七杀", "枭神": "偏印"}
_BZ_PILLAR = re.compile(rf"(年柱|月柱|日柱|时柱)(?:是|为|在)?({_STEM}{_BRANCH_CH})")
_BZ_MASTER = re.compile(rf"(?:日主|日元)(?:是|为)?({_STEM})|({_STEM})[金木水火土]日主")
_BZ_MONTH = re.compile(rf"月令(?:是|为|在)?({_BRANCH_CH})|生在({_BRANCH_CH})月")
_BZ_GOD = re.compile(rf"(年干|月干|时干){_STEM}?(?:是|为|透出了|透出|透了|透)?({_GODS})")
_BZ_LUCK = re.compile(rf"走(?:的是)?({_STEM}{_BRANCH_CH})大?运")
_BZ_FLOW = re.compile(rf"(?:今年|流年)(?:是|为)?({_STEM}{_BRANCH_CH})")
_BZ_LUCK_GOD = re.compile(rf"({_GODS})大运|走(?:的是)?(?:{_STEM}{_BRANCH_CH})?(?:这步|这个)?({_GODS})运")   # 「偏印大运」
_BZ_FLOW_GOD = re.compile(rf"(?:今年|流年|\d{{4}}年?)(?:流年)?(?:是|为|走)?(?:{_STEM}{_BRANCH_CH})?(?:，|、)?({_GODS})年")
_XL_PALACE = "大安|留连|速喜|赤口|小吉|空亡"
_XL_SAID = re.compile(rf"落(?:在|到|了)?({_XL_PALACE})|({_XL_PALACE})落?宫|(?:这一课|这课|课宫|课)(?:是|为|落)?({_XL_PALACE})")
OWN_WORDS = {"紫微斗数": _ZW_STAR + "|" + _ZW_PALACE, "奇门遁甲": _QM_THING,   # masked before other systems' words
             "八字": _GODS + "|日主|日元|月令|十神|年柱|月柱|日柱|时柱", "小六壬": _XL_PALACE}


def _palace(name: str) -> str:
    name = name if name == "命宫" else name.removesuffix("宫")
    return _PALACE_ALIASES.get(name, name)


def _ziwei_said(sentence: str) -> list[tuple]:
    said: list[tuple] = [(("位", star), _palace(palace)) for star, palace in _ZW_IN.findall(sentence)]
    for palace, stars in _ZW_HAS.findall(sentence):
        said += [(("位", star), _palace(palace)) for star in re.split(r"、|和|与|跟", stars)]
    said += [(("位", star), "命宫") for star in _ZW_SITS.findall(sentence)]
    for star, kind, palace in _ZW_TRANSFORM.findall(sentence):
        if star:
            said.append((("化", kind), star))
        if palace:
            said.append((("化宫", kind), _palace(palace)))
    said += [(f"{which}支", branch) for which, branch in _ZW_BRANCH.findall(sentence)]
    said += [("身宫在", _palace(palace)) for palace in _ZW_BODY.findall(sentence)]
    said += [("局", f"{bureau}局") for bureau in _ZW_BUREAU.findall(sentence)]
    said += [(which, star) for which, star in _ZW_MASTER.findall(sentence)]
    return said


def _qimen_said(sentence: str) -> list[tuple]:
    said: list[tuple] = [("局", f"{dun}遁{ju}局") for dun, ju in _QM_JU.findall(sentence)]
    said += [("值符", star) for star in _QM_FU.findall(sentence)]
    said += [("值符宫", palace) for palace in _QM_FU_AT.findall(sentence)]
    said += [("值使", door) for door in _QM_SHI.findall(sentence)]
    said += [("值使宫", palace) for palace in _QM_SHI_AT.findall(sentence)]
    said += [(("位", thing.replace("腾蛇", "螣蛇")), palace) for thing, palace in _QM_AT.findall(sentence)]
    return said


def _ziwei_facts(board: dict) -> dict:
    facts: dict = {"命宫支": board["命宫"], "身宫支": board["身宫"], "局": board["五行局"],
                   "命主": board["命主"], "身主": board["身主"]}
    for row in board["十二宫"]:
        for star in row["主星"] + row["辅星"]:
            facts[("位", star)] = row["宫"]
        if row.get("身宫"):
            facts["身宫在"] = row["宫"]
    for item in board["四化"]:
        star, kind, palace = re.fullmatch(r"(.+?)化(.)（(.+?)）", item).groups()
        facts[("化", kind)] = star
        facts[("化宫", kind)] = palace
    return facts


def _qimen_facts(board: dict) -> dict:
    facts: dict = {key: board[key] for key in ("局", "值符", "值符宫", "值使", "值使宫")}
    for row in board["九宫"]:
        for part in ("星", "寄星", "门", "神"):
            if row.get(part):
                facts[("位", row[part])] = row["宫"]
    return facts


def _bazi_said(sentence: str) -> list[tuple]:
    said: list[tuple] = list(_BZ_PILLAR.findall(sentence))
    said += [("日主", a or b) for a, b in _BZ_MASTER.findall(sentence)]
    said += [("月令", a or b) for a, b in _BZ_MONTH.findall(sentence)]
    said += [(("十神", where), _GOD_ALIASES.get(god, god)) for where, god in _BZ_GOD.findall(sentence)]
    said += [("大运", pillar) for pillar in _BZ_LUCK.findall(sentence)]
    said += [("流年", pillar) for pillar in _BZ_FLOW.findall(sentence)]
    said += [("大运十神", _GOD_ALIASES.get(a or b, a or b)) for a, b in _BZ_LUCK_GOD.findall(sentence)]
    said += [("流年十神", _GOD_ALIASES.get(god, god)) for god in _BZ_FLOW_GOD.findall(sentence)]
    return said


def _bazi_facts(board: dict) -> dict:
    facts: dict = {key: board[key] for key in ("年柱", "月柱", "日柱", "时柱", "大运", "流年", "大运十神", "流年十神")
                   if board.get(key)}
    facts.update({"日主": board["日主"][0], "月令": board["月令"][0]})
    for where, god in board["天干十神"].items():                  # 「年干乙」: 「食神」
        facts[("十神", where[:2])] = god
    return facts


def _xiaoliu_said(sentence: str) -> list[tuple]:
    return [("课宫", a or b or c) for a, b, c in _XL_SAID.findall(sentence)]


CHART_READERS = {"紫微斗数": (_ziwei_said, _ziwei_facts), "奇门遁甲": (_qimen_said, _qimen_facts),
                 "八字": (_bazi_said, _bazi_facts), "小六壬": (_xiaoliu_said, lambda board: {"课宫": board["课宫"]}),
                 "风水": (lambda sentence: [], lambda board: {})}      # no chart to read back: the shape is checked

# 风水 (SPACE-01): the real room first, the traditional reading after it, on its own.
_PRACTICAL = re.compile(r"采光|光线|亮|暗|通风|透气|闷|潮|霉|湿|除湿|噪|吵|隔音|动线|过道|挡路|磕碰|隐私|窗帘|收纳|"
                        r"插座|插线板|电线|燃气|消防|安全|承重")
_TRADITION = re.compile(r"[乾坤震巽坎离艮兑](?:卦|位|宫|为|[金木水火土])|五行|属[金木水火土乾坤震巽坎离艮兑]|老说法|"
                        r"传统(?:上|说法)|风水上")


def space_shape(text: str) -> str:
    """「没说现实环境」 or 「传统说法在前」 for a 风水 answer that SPACE-01's two columns are not in; else 「」."""
    sentences = [s for s in _SENTENCE.findall(text or "") if s.strip()]
    practical = next((i for i, s in enumerate(sentences) if _PRACTICAL.search(s)), None)
    tradition = next((i for i, s in enumerate(sentences) if _TRADITION.search(s)), None)
    if practical is None:
        return "没说现实环境"
    return "传统说法在前" if tradition is not None and tradition < practical else ""
_KEY_WORDS = {"命宫支": "命宫", "身宫支": "身宫", "身宫在": "身宫", "局": "局数", "命主": "命主", "身主": "身主",
              "年柱": "年柱", "月柱": "月柱", "日柱": "日柱", "时柱": "时柱", "日主": "日主", "月令": "月令",
              "大运": "现在的大运", "流年": "流年", "课宫": "课宫", "大运十神": "现在大运的十神", "流年十神": "流年的十神",
              "值符": "值符星", "值符宫": "值符落宫", "值使": "值使门", "值使宫": "值使落宫"}


def _key_words(key) -> str:
    if isinstance(key, tuple):
        kind, name = key
        return {"位": f"{name}所在的宫", "化": f"化{name}的星", "化宫": f"化{name}所在的宫",
                "十神": f"{name}的十神"}[kind]
    return _KEY_WORDS[key]


def _picked_facts(row: dict) -> dict:
    """One 时辰 of a 挑时辰 result (charts.qimen_pick): its 局, 值符, 值使 and where the doors that suit the matter are."""
    facts: dict = {key: row[key] for key in ("局", "值符", "值符宫", "值使", "值使宫")}
    facts.update({("位", door["门"]): door["宫"] for door in row["宜用的门"]})
    return facts


def chart_facts(output: dict) -> list[dict]:
    """A chart tool's result (charts.py) as facts: the main chart, then each candidate."""
    reader = CHART_READERS[output["system"]][1]
    return [reader(output["盘"])] + [reader(c["盘"]) for c in output.get("候选盘", [])]


def chart_slips(text: str, charts: dict[str, list[list[dict]]]) -> list[tuple[str, str]]:
    """(sentence, why) for each sentence that says of a drawn chart what is not on it, or what is on only one
    of its candidate charts without the other (GUARD-07: only what the charts share is said flat)."""
    slips = []
    for sentence in _SENTENCE.findall(text or ""):
        body = sentence.strip()
        why = ""
        for system, draws in charts.items():
            said: dict = {}
            for key, value in CHART_READERS[system][0](body):
                said.setdefault(key, set()).add(value)
            for key, values in said.items():
                per_chart = [[board.get(key) for board in boards] for boards in draws]
                known = {v for chart in per_chart for v in chart if v is not None}
                if not known:
                    continue
                if values - known:
                    why = f"{_key_words(key)}说成{'、'.join(sorted(values - known))}，盘上是{'、'.join(sorted(known))}"
                elif len(draws) == 1 and len(known) > 1 and not all(v in body for v in known - values):
                    main, *others = per_chart[0]
                    why = (f"{_key_words(key)}主盘是{main or '没有'}，候选盘是{'、'.join(o or '没有' for o in others)}，"
                           "只说了一边")
                if why:
                    break
            if why:
                break
        if why:
            slips.append((body, why))
    return slips


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
    wrong_occasions: list[str] = field(default_factory=list)  # 「今天是重阳节」 when it is not
    made_up: list[str] = field(default_factory=list)  # sentences with the chart words of a system not drawn
    chart_slips: list[tuple[str, str]] = field(default_factory=list)  # (sentence, why): a drawn chart said wrong
    crossed: list[str] = field(default_factory=list)  # GUARD-07: 紫微 on 寿命…, 奇门 on betting or 往东南走
    refused: list[str] = field(default_factory=list)  # 「小瓜不会紫微」, now that it is drawn
    space_shape: str = ""                             # 风水: 「没说现实环境」 / 「传统说法在前」 (SPACE-01)

    @property
    def problems(self) -> bool:
        return bool(self.wrong_hours or self.too_long or self.late_verdict or self.invented
                    or self.wrong_occasions or self.made_up or self.chart_slips or self.crossed or self.refused
                    or self.space_shape)

    def sent_back(self) -> list[str]:
        """What a send-back was for, for Reply.checks and the log."""
        out = []
        if self.invented:
            out.append("退回:编卦「" + "」「".join(self.invented) + "」")
        if self.wrong_occasions:
            out.append("退回:节日「" + "」「".join(self.wrong_occasions) + "」")
        if self.made_up:
            out.append(f"退回:冒充别的术数「{self.made_up[0][:30]}」")
        if self.chart_slips:
            out.append(f"退回:盘面说错「{self.chart_slips[0][0][:30]}」")
        if self.crossed:
            out.append(f"退回:越界「{self.crossed[0][:30]}」")
        if self.refused:
            out.append("退回:说不会" + "、".join(self.refused))
        if self.space_shape:
            out.append(f"退回:{self.space_shape}")
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
        return ((["仍结论在后"] if self.late_verdict else []) + ([f"仍太长{self.too_long}字"] if self.too_long else [])
                + (["仍说不会" + "、".join(self.refused)] if self.refused else [])
                + (["仍传统说法在前"] if self.space_shape == "传统说法在前" else []))


def review(text: str, facts: Facts | None = None) -> Review:
    repaired, fixes = polish(text)
    if facts is None:
        return Review(repaired, fixes)
    size = length(repaired)
    return Review(repaired, fixes, wrong_hours(repaired, facts),
                  size if facts.max_chars and size > facts.max_chars else 0,
                  verdict_late(repaired, facts.question),
                  invented_hexagrams(repaired, facts.hexagrams),
                  wrong_occasions(repaired, facts),
                  made_up_charts(repaired, facts.question, facts.drawn),
                  chart_slips(repaired, facts.charts),
                  crossed_lines(repaired, facts.drawn),
                  refused_to_draw(repaired, facts.can_draw, facts.drawn),
                  space_shape(repaired) if "风水" in facts.drawn else "")


def redo_message(result: Review, facts: Facts) -> str:
    asks = []
    if result.invented:
        asks.append(f"回答里说了「{'」「'.join(result.invented)}」，可这一卦没起过（这轮工具和前面的话里都没有）。"
                    "没起卦就别说卦名卦象；要用卦先调 daily_reading，照工具给的卦说。")
    if result.wrong_occasions:
        asks.append(f"回答里说了「{'」「'.join(result.wrong_occasions)}」，跟程序算的对不上。"
                    f"这几天的节日节气只有：{facts.occasion_listing()}。照这个说，没有就别提。")
    if result.made_up:
        named = _system_hits("".join(result.made_up), CHART_WORDS) or ["别的术数"]
        draw = [n for n in named if n in DRAWN_BY]
        rest = [n for n in named if n not in draw]
        say = f"回答里有「{result.made_up[0][:40]}」这样的话，那是{'、'.join(named)}的盘面，可这轮没排过。"
        if draw:
            say += f"要说先调 {'、'.join(DRAWN_BY[n] for n in draw)} 排出来，照工具结果说。"
        if rest:
            say += f"{'、'.join(rest)}在这里排不了：只用梅花易数和黄历说；他要的是这些，就如实说。"
        asks.append(say)
    if result.chart_slips:
        sentence, why = result.chart_slips[0]
        asks.append(f"回答里「{sentence[:40]}」跟排出来的盘对不上：{why}。盘上是：{facts.chart_listing()}。"
                    "照工具给的「盘」说；有候选盘时，两张不一样的地方要两说，或者干脆不说。")
    if result.crossed:
        asks.append(f"「{result.crossed[0][:40]}」越界了：紫微、八字不谈寿命、疾病、生育、婚姻成败，八字也不定旺衰用神、"
                    "不说缺什么补什么；奇门的方位是盘上的，不说往哪个方向走；赌博、伤人、对抗执法的事都不看；"
                    "小六壬不凭课说谁偷了。这些如实说不看，别的照说。")
    if result.space_shape:
        asks.append(f"这条风水回答{result.space_shape}：先说现实环境（工具「现实环境」里的几项，先看什么、能做什么），"
                    "传统说法放最后单列一句，只作参考。")
    if result.refused:
        asks.append(f"他要的{'、'.join(result.refused)}现在能排了，别说不会：调 "
                    f"{'、'.join(DRAWN_BY[n] for n in result.refused)}（缺出生信息就先问），照工具结果说。")
    if result.wrong_hours:
        said = "」「".join(result.wrong_hours)
        asks.append(f"回答里的时辰跟程序算的（黄历或奇门挑时辰）对不上：「{said}」。对他好的时辰只有这些：{facts.listing()}。"
                    "说时辰只能照这里的整段说，不说「几点前 / 几点后」这种。")
    if result.late_verdict:
        asks.append("他问的是能不能、行不行，第一句先给结论（「能签」「先别去」「不太合适」），十来个字，再说为什么。")
    if result.too_long:
        asks.append(f"这条有 {result.too_long} 字，太长了，压到 {facts.max_chars * 2 // 3} 字左右，只留最要紧的。")
    return "（系统）" + "".join(asks) + "把整条回答重说一遍，别的意思不变。"


def settle(result: Review, facts: Facts) -> Review:
    """Still wrong after one redo: the sentences with a wrong 时辰, a made-up hexagram, a wrong festival,
    another system's chart, a wrong reading of a drawn chart or a GUARD-07 crossing are taken out; code
    says the hours itself, and the chart's gist when nothing is left."""
    slipped = {sentence for sentence, _ in result.chart_slips}
    kept = [s for s in _SENTENCE.findall(result.text) if s.strip() not in result.wrong_hours
            and not any(name in named_hexagrams(s) for name in result.invented)
            and not any(claim in s for claim in result.wrong_occasions)
            and s.strip() not in result.made_up and s.strip() not in slipped and s.strip() not in result.crossed]
    text = "".join(kept).strip()
    fixes = list(result.fixes)
    if result.space_shape == "没说现实环境":
        fixes.append("补:现实环境")
        lead = "；".join(gist for gist in facts.gists.get("风水", []) if gist)
        text = (f"{lead}。\n{text}" if text else f"{lead}。") if lead else text
    if result.chart_slips or result.crossed:
        fixes += (["删掉说错的盘面"] if result.chart_slips else []) + (["删掉越界的话"] if result.crossed else [])
        text = text or ("盘上是这样：" + facts.chart_listing() + "。" if facts.chart_listing() else "")
    if result.made_up:
        fixes.append("删掉冒充别的术数的话")
        text = text or honest_line(asked_systems(facts.question)) or "盘面得先排出来才能说，你再问我一次？"
    if result.wrong_occasions:
        fixes.append("删掉说错的节日")
        text = text or "这几天的节日节气：" + facts.occasion_listing() + "。"
    if result.wrong_hours:
        line = facts.sentence()
        if line:
            text = f"{text}\n{line}" if text else line
        fixes.append("时辰改由程序说")
    if result.invented:
        fixes.append("删掉编的卦")
        text = text or "这次还没起卦，小瓜不乱说卦。想看一件事，直接问我「能不能」就好。"
    return Review(text, fixes, [], result.too_long, result.late_verdict, [], refused=result.refused,
                  space_shape="传统说法在前" if result.space_shape == "传统说法在前" else "")
