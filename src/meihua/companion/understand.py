"""What a plain sentence asks for: the model reads it into a fixed form, code checks the form.

People say 「换工作好还是留下来好」「床放在窗户下面好不好」「帮我算算命」, not 梅花、风水、八字, and no
word list keeps up with how they say it. So routing.pick, when code alone cannot tell, has the model
fill this form — one short call, no tools, no reading — and decides the reading itself from the form
by the project's policy (routing.from_form). The model never picks the method.

check() keeps the form honest before it is used:
  类     one of KINDS, or the form is dropped
  出生   copied from his sentence (it must be there, with a number in it), else empty
  日子   needs a word for a time in the sentence, else it is a choice (梅花)
  房间   needs a word for a place or a thing in it, else it is a matter (梅花)
  接上句 only when there was a last question
Any failure (no answer, not JSON, timeout): None, and routing falls back to its keywords.
"""

from __future__ import annotations

import json
import re
from typing import Any

KINDS = {
    "结果": "问一件具体的事会怎样：能不能成、会不会发生、顺不顺、某人会不会怎么做、考得怎么样",
    "选择": "在几个做法里挑一个，或者问要不要、该不该、值不值、买不买、接不接",
    "找东西": "东西或宠物丢了、找不到、不知道放哪了",
    "日子": "重点是挑时间：哪天、几点、什么时候做某事好，或某一天适不适合做某事（搬家、剪头发、开业、领证、出行这类看日子的事），某天宜什么忌什么",
    "房间": "家里、办公室、宿舍的布置和环境：摆放、朝向、门窗床镜、采光、潮湿、住着不舒服、风水",
    "命": "问一个人自己的命：算命、看命、性格、天赋、适合干什么行业、一辈子的大方向",
    "倾诉": "说自己的心情或遭遇，没有在问结果",
    "闲聊": "打招呼、聊天、问小瓜自己、问天气新闻常识、让小瓜推荐吃的玩的",
    "事务": "让小瓜记住什么、提醒什么、改设置",
    "知识": "问某种算命方法是什么、准不准、迷不迷信、有什么区别",
    "别的算法": "要手相、面相、塔罗、星座、测字、抽签、解梦这类小瓜没有的方法",
}
EXAMPLES = [
    ("下周的复试能过吗", {"类": "结果"}),
    ("去北京还是留在成都", {"类": "选择"}),
    ("戒指不见了", {"类": "找东西"}),
    ("这周哪天去拔牙好", {"类": "日子"}),
    ("沙发靠窗放行不行", {"类": "房间"}),
    ("我1988年3月5日晚上9点生的，适合干什么", {"类": "命", "出生": "1988年3月5日晚上9点生的", "长远": True}),
    ("我是86年的，明年财运怎么样", {"类": "结果", "出生": "86年", "长远": True}),
    ("快速看一下现在去找他顺不顺", {"类": "结果", "快": True}),
    ("今天又被客户放鸽子了，好烦", {"类": "倾诉"}),
    ("梅花易数和六爻有什么不同", {"类": "知识"}),
    ("给我看看面相", {"类": "别的算法", "算法": "面相"}),
]
EMPTY = {"类": "", "出生": "", "长远": False, "快": False, "接上句": False, "算法": ""}


def _example(question: str, form: dict) -> str:
    return f"「{question}」→ " + json.dumps({**EMPTY, **form}, ensure_ascii=False)


PROMPT = (
    "你只做一件事：读懂用户这句话想要什么，填一张表。不回答他，不解释，不加别的字。\n"
    "只输出一个 JSON 对象，键是：类、出生、长远、快、接上句、算法。\n\n"
    "类（只能选一个）：\n" + "\n".join(f"- {name}：{say}" for name, say in KINDS.items()) + "\n\n"
    "出生：原话里说他（或他问的那个人）出生年月日时的那一段，一字不改照抄；没有就空字符串。\n"
    "长远：问的是一辈子、性格、这几年、今年明年整体、以后这种长远的事就 true，眼前一件事就 false。\n"
    "快：他说要快速、简单、随手、速算看一下就 true。\n"
    "接上句：给了上一句、而这一句离开上一句就看不懂（「那周末呢」「为啥」），就 true。\n"
    "算法：类是「别的算法」时写他要的那种，否则空字符串。\n\n"
    "例子：\n" + "\n".join(_example(q, f) for q, f in EXAMPLES)
)

_TIME_WORD = re.compile(r"今天|明天|后天|大后天|昨天|周[一二三四五六日天末]|星期|礼拜|这周|下周|本周|这个月|下个月|月底|月初|"
                        r"年底|过年|\d{1,2}\s*[月号日点]|[一二三四五六七八九十]{1,3}[月号日点]|初[一二三四五六七八九十]|"
                        r"哪天|哪一天|几号|几点|什么时候|啥时候|时辰|日子|早上|上午|中午|下午|晚上|今晚|明晚|现在")
_HOME_WORD = re.compile(r"家|房|屋|室|厅|厨|卫|厕|门|窗|床|桌|椅|镜|柜|沙发|阳台|墙|灯|摆|放|布置|装修|朝|风水|住|"
                        r"宿舍|办公|工位|鱼缸|植|花|楼|院|车位")
_BIRTH_LIKE = re.compile(r"[\d〇零一二三四五六七八九十]")
_JSON = re.compile(r"\{.*\}", re.S)


def parse(answer: str) -> dict | None:
    """The first JSON object in the model's answer (a ```json fence or a stray word around it is fine)."""
    match = _JSON.search(answer or "")
    if not match:
        return None
    try:
        form = json.loads(match.group(0))
    except ValueError:
        return None
    return form if isinstance(form, dict) else None


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("true", "是", "1")


def check(form: dict | None, question: str, has_last: bool) -> tuple[dict | None, list[str]]:
    """The form as code accepts it, and what code changed (for the log)."""
    if not isinstance(form, dict):
        return None, ["没填表"]
    kind = str(form.get("类") or "").strip()
    if kind not in KINDS:
        return None, [f"类不对：{kind or '空'}"]
    notes: list[str] = []
    said = re.sub(r"\s", "", question or "")
    birth = re.sub(r"\s", "", str(form.get("出生") or ""))
    if birth and (birth not in said or not _BIRTH_LIKE.search(birth)):
        notes.append(f"出生「{birth}」原话里没有，不用")
        birth = ""
    if kind == "日子" and not _TIME_WORD.search(said):
        notes.append("日子：话里没有时间，按选择")
        kind = "选择"
    if kind == "房间" and not _HOME_WORD.search(said):
        notes.append("房间：话里没有地方或物件，按结果")
        kind = "结果"
    follows = _flag(form.get("接上句")) and has_last
    return {"类": kind, "出生": birth, "长远": _flag(form.get("长远")), "快": _flag(form.get("快")),
            "接上句": follows, "算法": str(form.get("算法") or "").strip() if kind == "别的算法" else ""}, notes


def read(client: Any, model: str, question: str, last_question: str | None = None,
         timeout: float = 10.0) -> tuple[dict | None, list[str]]:
    """One short call: (the checked form, notes). (None, why) when the model cannot be used for it."""
    said = f"上一句：{last_question}\n这一句：{question}" if last_question else f"这一句：{question}"
    try:
        response = client.messages.create(model=model, max_tokens=300, system=PROMPT, timeout=timeout,
                                          messages=[{"role": "user", "content": said}])
    except Exception as error:  # noqa: BLE001 — any failure: routing uses its keywords
        return None, [f"没听成：{type(error).__name__}"]
    answer = "".join(getattr(b, "text", "") for b in getattr(response, "content", []) if getattr(b, "type", "") == "text")
    return check(parse(answer), question, last_question is not None)
