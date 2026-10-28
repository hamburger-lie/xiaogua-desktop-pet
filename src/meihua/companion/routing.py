"""Which reading a question gets: decided by code, before the model is asked.

The project's routing policy (router/method-routing.md) has been code all along (router/route.py, with
its golden cases). Here every question gets a Route, and the agent offers the model that one
reading tool and no other (the 黄历 and memory tools stay). Three layers:

  code      what code can tell for certain (_by_code), in order:
              named      a method he names (harness.asked_systems, which leaves out 「八字准不准」 and
                         「不用八字」): its tool; 奇门 with 「几点、哪个时辰」 is qimen_pick. Two named: ask
                         which. Only 六爻 or 飞星排盘 named: no tool, he is told it cannot.
              a short follow-up (「为啥」「那周末呢」) within 30 minutes: the last turn's tool;
              「起一课」: 小六壬; a greeting or an errand (「提醒我…」): chat;
              户型、采光: space_check; 出生信息 + 长期问题: 八字; 黄历、宜忌、吉日: the 黄历.
  form      everything else, when a reader is given (the agent's understand.read): the model fills a
            fixed form from his plain words, code checks it, and from_form maps it by the policy —
            a matter, a choice, a lost thing -> 梅花 (快速 -> 小六壬; 出生 + 长远 -> 八字); which day,
            what time -> 黄历; a room -> 风水（空间观察）; his 命、性格、哪行 -> 八字 (asks for the
            birth when it is missing, XG-NATAL); 倾诉、闲聊、事务 -> chat; 手相、塔罗… -> not done.
  keywords  no reader (offline, tests) or the form failed: the word lists below and route.route().

紫微、奇门 are never chosen by themselves (admitted for named requests only). Each case is in
tests/companion/routing.jsonl and plain.jsonl (tests/test_routing_companion.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

import meihua  # noqa: F401 — router on sys.path

from route import route as project_route  # type: ignore[import-not-found]

import almanac  # type: ignore[import-not-found]

from . import harness

METHOD_TOOLS = {"meihua": "daily_reading", "xiaoliu-ren": "xiaoliu_chart", "bazi": "bazi_chart",
                "ziwei": "ziwei_chart", "qimen": "qimen_chart", "space-observation": "space_check"}
SYSTEM_METHODS = {"紫微斗数": "ziwei", "奇门遁甲": "qimen", "八字": "bazi", "小六壬": "xiaoliu-ren",
                  "风水": "space-observation"}
METHOD_NAMES = {"meihua": "梅花易数", "xiaoliu-ren": "小六壬", "bazi": "八字", "ziwei": "紫微斗数",
                "qimen": "奇门遁甲", "space-observation": "风水（空间观察）", "almanac": "黄历"}
READING_TOOLS = {"daily_reading", "cast_now", "lookup_hexagrams", "validate_reading", "ziwei_chart", "qimen_chart",
                 "qimen_pick", "bazi_chart", "xiaoliu_chart", "space_check"}
FOLLOW_UP_WINDOW = timedelta(minutes=30)
SHORT_FOLLOW_UP = 8        # 「那周末呢」 code alone; a longer one is read with the last question beside it
KEPT_ON_FOLLOW_UP = ("daily_reading", "qimen_chart", "xiaoliu_chart")   # drawn from the moment: a follow-up keeps it

PICK_HOURS = re.compile(r"几点|哪个时辰|什么时辰|哪个时候|什么时候去|挑(?:个|一个)?时辰|择时|选(?:个|一个)?时辰")
XIAOLIU_CUE = re.compile(r"起(?:一|个)?课|算(?:一|个)?课|六宫")   # 「起一课」 is 六壬's word, not 梅花's
MEIHUA_NAMED = re.compile(r"梅花(?:易数)?|起(?:一|个)?卦|算(?:一|个)?卦|卜(?:一|个)?卦|占(?:一|个)?卦")
FOLLOW_UP = re.compile(r"^(?:那|那么|那要|还有|再|然后|另外|为什么|为啥|怎么说|具体|详细)|[呢吧][？?]?$")
GREETING = re.compile(r"^(?:你好|您好|hi|hello|嗨|哈喽|在吗|在不在|早安?|早上好|午安|下午好|晚安|晚上好|"
                      r"谢谢\S{0,4}|多谢|辛苦了|拜拜|再见|收到|知道了|明白了?|[嗯哦噢啊哈呵好行的吧呀啦了耶嘿]+|ok)"
                      r"[!！。.~～,，\s]*$", re.I)
ERRAND = re.compile(r"提醒我|提醒一下|记一下|记住|帮我记|别忘了提醒|闹钟")
ALMANAC_SURE = re.compile(r"黄历|皇历|宜忌|宜什么|忌什么|宜不宜|黄道|吉日|好日子|日子好|择日|冲什么|冲哪|犯冲")
SPACE_SURE = re.compile(r"户型|采光|通风|动线")
# The keyword layer (no reader, or the form failed).
SPACE = re.compile(r"户型|采光|通风|动线|(?:房子|房间|屋子|卧室|客厅|书房|厨房|办公室|工位).{0,6}(?:潮|暗|吵|闷|霉|挤|乱)|"
                   r"床头|书桌朝|怎么摆|摆放|布局")
ALMANAC = re.compile(r"黄历|皇历|宜忌|宜什么|忌什么|宜不宜|黄道|吉日|好日子|日子好|冲什么|冲哪|犯冲|"
                     r"哪天(?:适合|好|宜|能)|哪一天(?:适合|好)|挑(?:个|一个)?日子|择日|"
                     r"几点(?:出门|出发|动身)|什么时辰(?:出门|出发|好)|好时辰")
DAY_WHAT = re.compile(r"适合(?:干|做)(?:什么|啥|嘛)|宜(?:干|做)(?:什么|啥|嘛)")   # with a day: 「今天适合干嘛」
DAY = re.compile(r"今天|明天|后天|大后天|周[一二三四五六日天末]|星期[一二三四五六日天]|这周|下周|\d{1,2}[月号日]|初[一二三四五六七八九十]")
SUITS = re.compile(r"适合|宜|合适")                 # suitability: the 黄历. 能不能、行吗: the matter itself, a reading
OUTCOME = re.compile(r"能成|成不成|成吗|会不会|顺不顺|顺利吗|结果|能过|过不过|有戏|稳吗|靠谱吗|怎么样|能拿下|能谈成|签得成")
READING = re.compile(r"能成|成不成|成吗|会不会|顺不顺|顺利吗|结果|走向|前景|发展|有戏|能过|能拿下|能谈成|"
                     r"要不要|该不该|值不值|选哪|哪个好|好不好|行不行|能不能|可不可以|靠谱吗|稳吗|"
                     r"找不到|丢了|落在哪|放哪了|在哪儿?找|帮我(?:看看|算算|测测)|运势|运气")
ABOUT_XIAOGUA = re.compile(r"^(?:你|小瓜)(?!帮|给|替|看|算)")


@dataclass
class Route:
    kind: str                  # named / follow-up / space / almanac / routed / chat / confirm / declined
    tool: str | None           # the one reading tool offered this turn (None: none)
    method: str | None         # meihua, bazi, … or "almanac"
    rule: str                  # router rule id, or the companion's own (XG-…)
    hint: str = ""             # said to the model with the question
    at: datetime | None = None
    by: str = "代码"           # 代码 / 听懂 (the form) / 关键词 (the form failed)
    question: str = ""         # what he asked: a later follow-up is read beside it
    form: dict | None = None   # the checked form, when by 听懂
    notes: list[str] = field(default_factory=list)   # what code changed in the form, or why it failed

    @property
    def label(self) -> str:
        said = {"听懂": "·听懂", "关键词": "·关键词"}.get(self.by, "")
        return f"{METHOD_NAMES.get(self.method, self.kind)}·{self.rule}{said}"

    def offered(self, name: str) -> bool:
        """Is this tool offered this turn? Reading tools only when routed; everything else always."""
        if name not in READING_TOOLS:
            return True
        if self.tool == "daily_reading":
            return name in ("daily_reading", "cast_now", "lookup_hexagrams", "validate_reading")
        return name == self.tool


Reader = Callable[[str, "str | None"], "tuple[dict | None, list[str]]"]


def _tool_for(method: str, text: str) -> str:
    return "qimen_pick" if method == "qimen" and PICK_HOURS.search(text) else METHOD_TOOLS[method]


def _say(method: str, tool: str, named: bool) -> str:
    why = "" if named else "（这是程序按问题选的，不用跟他解释为什么用这一门）"
    extra = {"bazi_chart": "缺公历出生日期和几点几分就先问；他给的是四柱就照四柱排。",
             "ziwei_chart": "缺公历出生日期、几点几分或性别就先问。",
             "space_check": "缺哪个房间、窗朝哪、主要问题就先问，能先说的照说。",
             "qimen_pick": "时间段按他说的换算。"}.get(tool, "")
    return f"（系统）这题用{METHOD_NAMES[method]}：调 {tool}。{extra}{why}"


def _routed(method: str, rule: str, now: datetime) -> Route:
    tool = METHOD_TOOLS[method]
    kind = "space" if method == "space-observation" else "routed"
    return Route(kind, tool, method, rule, _say(method, tool, named=False), now)


def _follow(last: Route, now: datetime) -> Route:
    again = "，沿用上一卦（局、课），讲清楚就好" if last.tool in KEPT_ON_FOLLOW_UP else ""
    return Route("follow-up", last.tool, last.method, "XG-FOLLOW",
                 f"（系统）这句接着上一题，还用{METHOD_NAMES.get(last.method, '')}：调 {last.tool}{again}。", now)


def _almanac(now: datetime) -> Route:
    return Route("almanac", None, "almanac", "XG-ALMANAC",
                 "（系统）这题看黄历：今天的在【今天】里，别的日子调 almanac_day，挑日子调 almanac_pick_days，不起卦。", now)


def _about(now: datetime) -> Route:
    return Route("chat", None, None, "XG-ABOUT", "（系统）他问的是这门术数本身，照实答就好，不起卦。", now)


def pick(question: str, last: Route | None = None, now: datetime | None = None, read: Reader | None = None) -> Route:
    """The route for one question. read(question, last question or None) -> (form, notes): understand.read."""
    text = (question or "").strip()
    now = now or datetime.now().astimezone()
    fresh = last if last is not None and last.tool and last.at and now - last.at <= FOLLOW_UP_WINDOW else None
    route = _by_code(text, fresh, now)
    if route is None and read is not None:
        form, notes = read(text, (fresh.question or None) if fresh else None)
        if form is not None:
            route = from_form(form, fresh, now)
        else:
            route = _by_keywords(text, fresh, now)
            route.by = "关键词"
        route.notes = notes
    if route is None:
        route = _by_keywords(text, fresh, now)
    route.question = text
    return route


def _by_code(text: str, fresh: Route | None, now: datetime) -> Route | None:
    systems = harness.asked_systems(text)
    drawable = [s for s in systems if s in harness.DRAWN_BY]
    if len(drawable) > 1:
        return Route("confirm", None, None, "ROUTE-CONFLICT",
                     f"（系统）他点了{'、'.join(drawable)}，一题只用一门：先问他用哪一门，这轮不排。", now)
    if drawable:
        method = SYSTEM_METHODS[drawable[0]]
        tool = _tool_for(method, text)
        hint = _say(method, tool, named=True)
        if len(systems) > len(drawable):                       # 「用飞星看看我家风水」: say what it cannot
            hint += harness.ask_hint([s for s in systems if s not in drawable]).removeprefix("（系统）")
        return Route("named", tool, method, "ROUTE-EXPLICIT", hint, now)
    if systems:                                                 # 六爻、飞星 only
        return Route("declined", None, None, "ROUTE-ADMISSION", harness.ask_hint(systems), now)
    if harness._CURIOUS.search(text) and (harness._system_hits(text, harness.OTHER_SYSTEMS) or MEIHUA_NAMED.search(text)):
        return _about(now)
    if MEIHUA_NAMED.search(text):
        return Route("named", "daily_reading", "meihua", "ROUTE-EXPLICIT", _say("meihua", "daily_reading", True), now)
    if GREETING.search(text):
        return Route("chat", None, None, "XG-CHAT", "", now)
    if fresh is not None and len(text) <= SHORT_FOLLOW_UP and FOLLOW_UP.search(text):
        return _follow(fresh, now)
    if XIAOLIU_CUE.search(text):
        return _routed("xiaoliu-ren", "ROUTE-SHORT", now)
    if ERRAND.search(text) and not (READING.search(text) or harness.YES_NO.search(text)):
        return Route("chat", None, None, "XG-CHAT", "", now)
    if SPACE_SURE.search(text):
        return _routed("space-observation", "ROUTE-SPACE", now)
    routed = project_route({"question": text})
    if routed.get("method") == "bazi" and routed["rule_id"] == "ROUTE-BIRTH":     # 出生信息 + 长期问题
        return _routed("bazi", "ROUTE-BIRTH", now)
    if ALMANAC_SURE.search(text):
        return _almanac(now)
    if routed["status"] == "COMPARE":
        return Route("chat", None, None, "ROUTE-COMPARE", "（系统）他问的是方法的区别：只比较方法，不起卦。", now)
    return None


def from_form(form: dict, fresh: Route | None, now: datetime) -> Route:
    """The reading for a checked form (understand.check), by the project's policy."""
    route = _from_form(form, fresh, now)
    route.by, route.form = "听懂", form
    return route


def _from_form(form: dict, fresh: Route | None, now: datetime) -> Route:
    kind = form["类"]
    if form.get("接上句") and fresh is not None:
        return _follow(fresh, now)
    if kind == "别的算法":
        what = form.get("算法") or "这种方法"
        return Route("declined", None, None, "ROUTE-ADMISSION",
                     f"（系统）他要的{what}小瓜不会：照实说一句，再问他想看的那件事要不要用梅花起一卦。这轮不起卦。", now)
    if kind == "知识":
        return _about(now)
    if kind in ("倾诉", "闲聊", "事务"):
        hint = "（系统）他在说心事：先接住他，不起卦；他像是想看看的话，问一句要不要帮他起一卦。" if kind == "倾诉" else ""
        return Route("chat", None, None, "XG-CHAT", hint, now)
    if kind == "房间":
        return _routed("space-observation", "ROUTE-SPACE", now)
    if kind == "日子":
        return _almanac(now)
    if kind == "命":                                       # his own 命: 八字, asking for the birth when it is missing
        return _routed("bazi", "ROUTE-BIRTH" if form.get("出生") else "XG-NATAL", now)
    if form.get("出生") and form.get("长远"):              # a matter: 八字 only with a birth and a long view
        return _routed("bazi", "ROUTE-BIRTH", now)
    if kind == "找东西":
        return _routed("meihua", "ROUTE-DEPTH", now)
    if form.get("快"):
        return _routed("xiaoliu-ren", "ROUTE-SHORT", now)
    return _routed("meihua", "ROUTE-DEPTH" if form.get("长远") else "ROUTE-DEFAULT", now)


def _by_keywords(text: str, fresh: Route | None, now: datetime) -> Route:
    if fresh is not None and FOLLOW_UP.search(text):
        return _follow(fresh, now)
    if SPACE.search(text):
        return _routed("space-observation", "ROUTE-SPACE", now)
    activity = any(word in text for word in almanac.ACTIVITIES)
    day = DAY.search(text)
    if ALMANAC.search(text) or (day and DAY_WHAT.search(text)) \
            or (day and SUITS.search(text) and activity and not OUTCOME.search(text)):
        return _almanac(now)
    routed = project_route({"question": text})
    method = routed.get("method")
    if method in ("bazi", "xiaoliu-ren", "space-observation"):
        return _routed(method, routed["rule_id"], now)
    asked = READING.search(text) or harness.YES_NO.search(text)
    if method == "meihua" and (routed["rule_id"] == "ROUTE-DEPTH" or asked) and not ABOUT_XIAOGUA.search(text):
        return _routed("meihua", routed["rule_id"], now)
    return Route("chat", None, None, "XG-CHAT", "", now)
