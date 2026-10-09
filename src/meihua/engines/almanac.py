#!/usr/bin/env python3
"""黄历: one day's 宜忌, 冲煞, 值神 and 时辰, and how the day sits with a 属相.

The calendar facts come from lunar_python (6tail's 寿星万年历, MIT; 宜忌 per
《协纪辨方书》). This module only selects, translates and relates them, so the
model never works out a 干支, a 冲 or a 宜忌 itself.

Relations between the user's 属相 and the day (or year) branch are the standard
地支 tables: 六冲, 六合, 三合, 相刑, 六害. They describe how the day "sits" with the
person; they are folk tradition, not a forecast.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta

from lunar_python import Solar

BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
WEEKDAYS = "一二三四五六日"
MAX_SPAN_DAYS = 120

SIX_HARMONY = {frozenset(p) for p in ("子丑", "寅亥", "卯戌", "辰酉", "巳申", "午未")}
THREE_HARMONY = ("申子辰", "亥卯未", "寅午戌", "巳酉丑")
PUNISH = {frozenset(p) for p in ("子卯", "寅巳", "巳申", "寅申", "丑戌", "戌未", "丑未")}
SELF_PUNISH = set("辰午酉亥")
HARM = {frozenset(p) for p in ("子未", "丑午", "寅巳", "卯辰", "申亥", "酉戌")}
TAI_SUI = {"本命": "值太岁（本命年）", "冲": "冲太岁", "刑": "刑太岁", "害": "害太岁"}

# Traditional 宜忌 terms in everyday words. Terms not listed are shown as they are.
PLAIN = {
    "祭祀": "祭拜祖先", "祈福": "求神许愿", "求嗣": "求子", "开光": "开光", "塑绘": "塑像画像",
    "齐醮": "做法事", "斋醮": "做法事", "沐浴": "洗澡放松", "酬神": "还愿", "焚香": "烧香",
    "嫁娶": "结婚办喜事", "订婚": "订婚", "纳采": "提亲送彩礼", "问名": "提亲合八字", "纳婿": "招女婿",
    "归宁": "回娘家", "安床": "换床摆床", "合帐": "布置婚房", "冠笄": "成人礼", "订盟": "定下约定",
    "进人口": "添人进口", "裁衣": "做衣服买衣服", "挽面": "修面", "开容": "修面美容",
    "修坟": "修坟", "启钻": "迁坟", "破土": "破土（丧葬）", "安葬": "下葬", "立碑": "立碑",
    "成服": "穿孝服", "除服": "脱孝服", "开生坟": "建生坟", "合寿木": "做寿材", "入殓": "入殓",
    "移柩": "移灵", "行丧": "办丧事", "普渡": "普渡",
    "入宅": "搬进新家", "移徙": "搬家", "分居": "分家", "安香": "安神位", "安门": "装门", "修门": "修门",
    "修造": "装修", "起基": "打地基", "动土": "动土开工", "起基动土": "动土开工", "上梁": "上梁",
    "竖柱": "立柱", "造屋": "盖房", "盖屋": "盖房", "盖屋合脊": "封顶", "合脊": "封顶", "作梁": "做房梁",
    "拆卸": "拆旧", "破屋": "拆房", "坏垣": "拆墙", "破屋坏垣": "拆房拆墙", "补垣": "补墙",
    "修饰垣墙": "粉刷墙面", "作灶": "装灶台", "解除": "打扫清理", "扫舍": "大扫除",
    "平治道涂": "修路", "开井开池": "挖井挖池", "开厕": "修厕所", "作厕": "修厕所",
    "开市": "开张开工", "挂匾": "挂招牌", "纳财": "收钱进账", "求财": "求财", "开仓": "开仓出货",
    "出货财": "出货", "买车": "买车", "置产": "买房置业", "雇佣": "招人雇人",
    "立券": "签合同", "交易": "做买卖", "立券交易": "签合同做买卖",
    "安机械": "装机器设备", "安机": "装机器设备", "栽种": "种花种树", "牧养": "养宠物牲畜",
    "纳畜": "买宠物牲畜", "习艺": "学手艺", "入学": "入学报班", "理发": "理发", "剃头": "理发",
    "整手足甲": "修指甲", "探病": "探望病人", "见贵": "见领导贵人", "出行": "出门远行",
    "乘船": "坐船", "渡水": "过河下水", "针灸": "针灸", "求医": "看病", "治病": "治病",
    "求医疗病": "看病治病", "会亲友": "见亲友聚会", "会友": "见朋友", "赴任": "入职上任",
    "词讼": "打官司", "捕捉": "灭虫除害", "畋猎": "打猎", "断蚁": "除白蚁", "取渔": "捕鱼",
    "结网": "织网", "诸事不宜": "什么都别做", "馀事勿取": "其余的事别做",
}

# Everyday activities -> the 宜忌 terms that decide them (for picking a day).
ACTIVITIES = {
    "搬家": ("入宅", "移徙"), "入住": ("入宅",), "结婚": ("嫁娶",), "领证": ("嫁娶",),
    "订婚": ("订婚", "纳采", "订盟"), "提亲": ("纳采", "问名"),
    "开业": ("开市",), "开张": ("开市",), "开工": ("开市",), "上线": ("开市",),
    "签约": ("立券", "交易", "立券交易"), "签合同": ("立券", "交易", "立券交易"), "做买卖": ("交易", "立券交易"),
    "买房": ("置产",), "买车": ("买车",), "提车": ("买车",),
    "装修": ("修造", "动土", "起基动土"), "动工": ("动土", "修造"),
    "出行": ("出行",), "旅行": ("出行",), "出差": ("出行",),
    "理发": ("理发", "剃头"), "剪头发": ("理发", "剃头"),
    "入职": ("赴任",), "上任": ("赴任",), "见领导": ("见贵",), "面试": ("见贵",),
    "聚会": ("会亲友", "会友"), "见朋友": ("会亲友", "会友"), "相亲": ("会亲友",),
    "看病": ("求医", "治病", "求医疗病"), "求财": ("求财", "纳财"), "收账": ("纳财",),
    "学习": ("入学", "习艺"), "报班": ("入学",), "大扫除": ("扫舍", "解除"),
    "祭拜": ("祭祀",), "祈福": ("祈福",), "换床": ("安床",), "种花": ("栽种",),
    "养宠物": ("纳畜", "牧养"), "做衣服": ("裁衣",), "招人": ("雇佣",), "打官司": ("词讼",),
}
APPROXIMATE = {"面试": "见贵", "上线": "开市", "相亲": "会亲友"}   # no traditional term of its own


def zodiac_branch(zodiac: str) -> str:
    zodiac = zodiac.strip().removeprefix("属")
    if len(zodiac) != 1 or zodiac not in ZODIAC:
        raise ValueError(f"属相只能是 {ZODIAC} 之一：{zodiac!r}")
    return BRANCHES[ZODIAC.index(zodiac)]


def relations(mine: str, other: str) -> list[str]:
    """How branch `other` (a day, hour or year) meets the person's branch `mine`."""
    pair = frozenset((mine, other))
    found = ["本命"] if mine == other else []
    if BRANCHES.index(other) == (BRANCHES.index(mine) + 6) % 12:
        found.append("冲")
    if pair in SIX_HARMONY:
        found.append("六合")
    if mine != other and any(mine in group and other in group for group in THREE_HARMONY):
        found.append("三合")
    if pair in PUNISH or (mine == other and mine in SELF_PUNISH):
        found.append("刑")
    if pair in HARM:
        found.append("害")
    return found


def tone(found: list[str]) -> str:
    """One word for the day as a whole: 冲 / 不顺 / 平 / 顺 / 合中带刑."""
    if "冲" in found:
        return "冲"
    good = {"六合", "三合"} & set(found)
    bad = {"刑", "害"} & set(found)
    if good and bad:
        return "合中带刑" if "刑" in bad else "合中带害"
    if bad:
        return "不顺"
    if good:
        return "顺"
    return "平"


FUNERAL = {"修坟", "启钻", "破土", "安葬", "立碑", "成服", "除服", "开生坟", "合寿木", "入殓", "移柩", "行丧", "普渡"}


def _plain(terms: list[str]) -> list[dict]:
    return [{"term": t, "plain": PLAIN.get(t, t), **({"funeral": True} if t in FUNERAL else {})}
            for t in terms if t != "无"]


def plain_text(items: list[dict]) -> str:
    """「洗澡放松、灭虫除害、丧葬事」: everyday words, the funeral terms folded into one."""
    words, funeral = [], False
    for item in items:
        if item.get("funeral"):
            funeral = True
        elif item["plain"] not in words:
            words.append(item["plain"])
    if funeral:
        words.append("丧葬事")
    return "、".join(words) or "无"


def _lunar(day: date):
    return Solar.fromYmdHms(day.year, day.month, day.day, 12, 0, 0).getLunar()


def day_almanac(day: date, zodiac: str | None = None) -> dict:
    """The 黄历 page for `day`; with a 属相, how the day and its hours sit with it."""
    lunar = _lunar(day)
    yi, ji = lunar.getDayYi(), lunar.getDayJi()
    out = {
        "status": "OK",
        "date": day.isoformat(),
        "weekday": "星期" + WEEKDAYS[day.weekday()],
        "lunar": f"{lunar.getYearInGanZhiByLiChun()}年 {lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
        "ganzhi": {"year": lunar.getYearInGanZhiByLiChun(), "month": lunar.getMonthInGanZhiExact(),
                   "day": lunar.getDayInGanZhi()},
        "solar_term": lunar.getJieQi() or None,
        "after_term": lunar.getPrevJieQi().getName(),
        "yi": _plain(yi),
        "ji": _plain(ji),
        "clash": {"zodiac": lunar.getDayChongShengXiao(), "desc": f"冲{lunar.getDayChongShengXiao()}",
                  "sha_direction": lunar.getDaySha()},
        "officer": lunar.getZhiXing() + "日",                                 # 建除十二值
        "day_god": {"name": lunar.getDayTianShen(), "kind": lunar.getDayTianShenType(),
                    "luck": lunar.getDayTianShenLuck()},                     # 黄道 / 黑道
        "lucky_gods": lunar.getDayJiShen(),
        "bad_stars": lunar.getDayXiongSha(),
        "directions": {"喜神": lunar.getDayPositionXiDesc(), "财神": lunar.getDayPositionCaiDesc(),
                       "福神": lunar.getDayPositionFuDesc()},
        "pengzu": [lunar.getPengZuGan(), lunar.getPengZuZhi()],
        "hours": [],
        "note": "黄历是传统民俗的择日规矩，只作参考。",
    }
    for hour in lunar.getTimes():
        start = hour.getMinHm()
        if start == "23:00":
            continue                                   # 晚子时 belongs to the next day's count
        out["hours"].append({"branch": hour.getZhi() + "时", "range": f"{start}-{hour.getMaxHm()}",
                             "luck": hour.getTianShenLuck(), "god": hour.getTianShen(),
                             "clash": hour.getChongShengXiao()})
    if zodiac:
        mine = zodiac_branch(zodiac)
        animal = ZODIAC[BRANCHES.index(mine)]
        day_rel = relations(mine, lunar.getDayZhi())
        year_rel = relations(mine, lunar.getYearZhiByLiChun())
        good_hours = [h for h in out["hours"] if h["luck"] == "吉" and h["clash"] != animal]
        out["for_you"] = {
            "zodiac": animal,
            "day_relations": day_rel,
            "day_tone": tone(day_rel),
            "clashed_today": "冲" in day_rel,
            "year_relations": year_rel,
            "tai_sui": [TAI_SUI[r] for r in year_rel if r in TAI_SUI],   # this 立春 year
            "good_hours": [f"{h['branch']} {h['range']}" for h in good_hours],
        }
    return out


def pick_days(activity: str, start: date, days: int = 30, zodiac: str | None = None) -> dict:
    """Days in [start, start+days) whose 宜 covers `activity` and whose 忌 does not."""
    activity = activity.strip()
    terms = ACTIVITIES.get(activity) or ((activity,) if activity in PLAIN else None)
    if terms is None:
        return {"status": "UNKNOWN_ACTIVITY", "activity": activity,
                "known": sorted(ACTIVITIES), "note": "换成列表里最接近的说法再查"}
    days = max(1, min(int(days), MAX_SPAN_DAYS))
    mine = zodiac_branch(zodiac) if zodiac else None
    found, skipped_clash = [], []
    for offset in range(days):
        day = start + timedelta(days=offset)
        lunar = _lunar(day)
        yi, ji = set(lunar.getDayYi()), set(lunar.getDayJi())
        if not (yi & set(terms)) or (ji & set(terms)) or "诸事不宜" in yi:
            continue
        entry = {"date": day.isoformat(), "weekday": "星期" + WEEKDAYS[day.weekday()],
                 "lunar": f"{lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
                 "day_god_luck": lunar.getDayTianShenLuck(), "clash": "冲" + lunar.getDayChongShengXiao()}
        if mine:
            rel = relations(mine, lunar.getDayZhi())
            entry["for_you"] = tone(rel)
            if "冲" in rel:
                skipped_clash.append(day.isoformat())
                continue
        found.append(entry)
    found.sort(key=lambda e: (e.get("for_you") not in ("顺",), e["day_god_luck"] != "吉", e["date"]))
    out = {"status": "OK", "activity": activity, "terms": list(terms), "from": start.isoformat(),
           "days": days, "matches": found[:12], "match_count": len(found)}
    if activity in APPROXIMATE:
        out["approximate"] = f"老黄历没有「{activity}」这一项，按「{APPROXIMATE[activity]}」看"
    if skipped_clash:
        out["skipped_clash_days"] = skipped_clash
    return out


def main(argv: list[str]) -> int:
    args = dict(zip(argv[::2], argv[1::2]))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    day = date.fromisoformat(args.get("--date", date.today().isoformat()))
    if "--activity" in args:
        result = pick_days(args["--activity"], day, int(args.get("--days", 30)), args.get("--zodiac"))
    else:
        result = day_almanac(day, args.get("--zodiac"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
