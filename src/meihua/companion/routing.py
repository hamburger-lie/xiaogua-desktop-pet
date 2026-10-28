"""Which reading a question gets: decided by code, before the model is asked.

The project's routing policy (router/method-routing.md) has been code all along (router/route.py, with
its golden cases), but 小瓜 left the choice to the model and only caught a system named outright.
Here every 日常 question gets a Route, and the agent offers the model that one reading tool and no
other (the 黄历 and memory tools stay). In order:

  1  named      a method he names (harness.asked_systems, which leaves out 「八字准不准」 and
                「不用八字」): its tool; 奇门 with 「几点、哪个时辰」 is qimen_pick. Two named: ask which.
                Only 六爻 or 飞星排盘 named: no tool, he is told it cannot.
  2  follow-up  no method words and it hangs on the last turn (「那下午呢」): the last turn's tool,
                same conversation, within 30 minutes.
  3  space      户型、采光、房间潮…: space_check (SPACE-01).
  4  almanac    a day's 宜忌, which day suits what, 几点出门: the 黄历, no reading.
  5  router     route.route(): 出生信息 + 长期问题 -> 八字, 「快速、起一课」 -> 小六壬, a matter he asks
                about -> 梅花; 紫微、奇门 never by themselves (admitted for named requests only).
  6  chat       anything else: no reading.

Each case is in tests/companion/routing.jsonl (tests/test_routing_companion.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

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

PICK_HOURS = re.compile(r"几点|哪个时辰|什么时辰|哪个时候|什么时候去|挑(?:个|一个)?时辰|择时|选(?:个|一个)?时辰")
XIAOLIU_CUE = re.compile(r"起(?:一|个)?课|算(?:一|个)?课|六宫")   # 「起一课」 is 六壬's word, not 梅花's
MEIHUA_NAMED = re.compile(r"梅花(?:易数)?|起(?:一|个)?卦|算(?:一|个)?卦|卜(?:一|个)?卦|占(?:一|个)?卦")
FOLLOW_UP = re.compile(r"^(?:那|那么|那要|还有|再|然后|另外|为什么|为啥|怎么说|具体|详细)|[呢吧][？?]?$")
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

    @property
    def label(self) -> str:
        return f"{METHOD_NAMES.get(self.method, self.kind)}·{self.rule}"

    def offered(self, name: str) -> bool:
        """Is this tool offered this turn? Reading tools only when routed; everything else always."""
        if name not in READING_TOOLS:
            return True
        if self.tool == "daily_reading":
            return name in ("daily_reading", "cast_now", "lookup_hexagrams", "validate_reading")
        return name == self.tool


def _tool_for(method: str, text: str) -> str:
    return "qimen_pick" if method == "qimen" and PICK_HOURS.search(text) else METHOD_TOOLS[method]


def _say(method: str, tool: str, named: bool) -> str:
    why = "" if named else "（这是程序按问题选的，不用跟他解释为什么用这一门）"
    extra = {"bazi_chart": "缺公历出生日期和几点几分就先问；他给的是四柱就照四柱排。",
             "ziwei_chart": "缺公历出生日期、几点几分或性别就先问。",
             "space_check": "缺哪个房间、窗朝哪、主要问题就先问，能先说的照说。",
             "qimen_pick": "时间段按他说的换算。"}.get(tool, "")
    return f"（系统）这题用{METHOD_NAMES[method]}：调 {tool}。{extra}{why}"


def pick(question: str, last: Route | None = None, now: datetime | None = None) -> Route:
    text = (question or "").strip()
    now = now or datetime.now().astimezone()
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
        return Route("chat", None, None, "XG-ABOUT", "（系统）他问的是这门术数本身，照实答就好，不起卦。", now)
    if MEIHUA_NAMED.search(text):
        return Route("named", "daily_reading", "meihua", "ROUTE-EXPLICIT", _say("meihua", "daily_reading", True), now)
    if last is not None and last.tool and last.at and now - last.at <= FOLLOW_UP_WINDOW and FOLLOW_UP.search(text):
        again = "，传 follow_up=true" if last.tool in ("qimen_chart", "xiaoliu_chart") else ""
        return Route("follow-up", last.tool, last.method, "XG-FOLLOW",
                     f"（系统）这句接着上一题，还用{METHOD_NAMES.get(last.method, '')}：调 {last.tool}{again}。", now)
    if XIAOLIU_CUE.search(text):
        return Route("routed", "xiaoliu_chart", "xiaoliu-ren", "ROUTE-SHORT",
                     _say("xiaoliu-ren", "xiaoliu_chart", named=False), now)
    if SPACE.search(text):
        return Route("space", "space_check", "space-observation", "ROUTE-SPACE",
                     _say("space-observation", "space_check", named=False), now)
    routed = project_route({"question": text})
    method = routed.get("method")
    if method == "bazi" and routed["rule_id"] == "ROUTE-BIRTH":         # 出生信息 + 长期问题, before any 黄历 words
        return Route("routed", "bazi_chart", "bazi", "ROUTE-BIRTH", _say("bazi", "bazi_chart", named=False), now)
    activity = any(word in text for word in almanac.ACTIVITIES)
    day = DAY.search(text)
    if ALMANAC.search(text) or (day and DAY_WHAT.search(text)) \
            or (day and SUITS.search(text) and activity and not OUTCOME.search(text)):
        return Route("almanac", None, "almanac", "XG-ALMANAC",
                     "（系统）这题看黄历：今天的在【今天】里，别的日子调 almanac_day，挑日子调 almanac_pick_days，不起卦。", now)
    if routed["status"] == "COMPARE":
        return Route("chat", None, None, "ROUTE-COMPARE", "（系统）他问的是方法的区别：只比较方法，不起卦。", now)
    if method in ("bazi", "xiaoliu-ren", "space-observation"):
        tool = METHOD_TOOLS[method]
        return Route("routed", tool, method, routed["rule_id"], _say(method, tool, named=False), now)
    asked = READING.search(text) or harness.YES_NO.search(text)
    if method == "meihua" and (routed["rule_id"] == "ROUTE-DEPTH" or asked) and not ABOUT_XIAOGUA.search(text):
        return Route("routed", "daily_reading", "meihua", routed["rule_id"],
                     _say("meihua", "daily_reading", named=False), now)
    return Route("chat", None, None, "XG-CHAT", "", now)
