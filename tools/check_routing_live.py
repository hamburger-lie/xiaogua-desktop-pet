"""Live routing check: the real model through the real agent and session, as the app uses them.

For every scenario (one question, or a short conversation for follow-ups) it checks which route code
chose (companion/routing.py), which tools the model then called, and that nothing was refused as
NOT_ROUTED. Costs real API calls: about 22 turns.

    python tools/check_routing_live.py                    # everything
    python tools/check_routing_live.py --only 八字,风水     # scenarios whose first question has one of these
    python tools/check_routing_live.py --out routing.json  # keep the answers

Run it with PYTHONPATH=src: the package name meihua is shared with the game edition, which may be
pip-installed on the same machine.
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sys
import time

import meihua
from meihua.companion import config
from meihua.companion.agent import make_agent
from meihua.companion.memory import Memory
from meihua.companion.session import Session

# (turns, expected per turn: (route kind, the reading tool that must be called, or None))
SCENARIOS = [
    (["今天宜什么"], [("almanac", None)]),
    (["明天适合理发吗"], [("almanac", None)]),
    (["今天下午去面试能成吗"], [("routed", "daily_reading")]),
    (["钥匙找不到了，在家里，帮我看看"], [("routed", "daily_reading")]),
    (["快速看看我今天适不适合联系客户"], [("routed", "xiaoliu_chart")]),
    (["我1995年5月12日上午10点半出生，男，适合做什么工作"], [("routed", "bazi_chart")]),
    (["甲子 乙丑 丙寅 丁卯，看看我的事业方式"], [("routed", "bazi_chart")]),
    (["我卧室朝北，特别潮，墙角发霉，怎么办"], [("space", "space_check")]),
    (["用紫微斗数看看我的性格，1995年5月12日上午10点半出生，女"], [("named", "ziwei_chart")]),
    (["用奇门帮我挑个时辰，明天几点去见客户好"], [("named", "qimen_pick")]),
    (["用奇门遁甲看看我下午去见客户怎么样"], [("named", "qimen_chart")]),
    (["摇个六爻看看"], [("declined", None)]),
    (["用八字和紫微一起看看我"], [("confirm", None)]),
    (["八字准不准"], [("chat", None)]),
    (["你好"], [("chat", None)]),
    (["十分钟后提醒我喝水"], [("chat", None)]),
    (["用紫微斗数看看我，1995年5月12日上午10点半出生，女", "那我的财帛宫呢"], [("named", "ziwei_chart"), ("follow-up", None)]),
    (["用奇门遁甲看看我下午去见客户怎么样", "那要带合同过去吗"], [("named", "qimen_chart"), ("follow-up", None)]),
    (["今天下午去面试能成吗", "为什么这么说"], [("routed", "daily_reading"), ("follow-up", None)]),
]
RULES = {"almanac": "XG-ALMANAC", "chat": "XG-", "declined": "ROUTE-ADMISSION", "confirm": "ROUTE-CONFLICT",
         "follow-up": "XG-FOLLOW", "space": "ROUTE-SPACE", "named": "ROUTE-EXPLICIT", "routed": "ROUTE-"}
READING = {"daily_reading", "cast_now", "ziwei_chart", "qimen_chart", "qimen_pick", "bazi_chart", "xiaoliu_chart",
           "space_check"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="comma-separated words; scenarios whose first question has one")
    parser.add_argument("--out", help="write every turn (route, tools, checks, answer) to this JSON file")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    scenarios = [s for s in SCENARIOS if not args.only or any(w in s[0][0] for w in args.only.split(","))]

    cfg = config.Config.load()
    key, _ = config.api_key(cfg.provider)
    print(f"代码 {meihua.__file__}\n厂商 {cfg.provider}  模型 {cfg.model}\n")
    rows, bad = [], 0
    for turns, expected in scenarios:
        agent = make_agent(cfg.model, key, cfg.provider, cfg.base_url, cfg.deep_thinking)
        agent.session = Session(None)
        agent.session.memory = Memory()
        agent.session.zodiac = "羊"
        daily = {"mode": "daily"} if "mode" in inspect.signature(agent.ask).parameters else {}   # the 日常版 has no modes
        for question, (kind, tool) in zip(turns, expected):
            start = time.time()
            try:
                reply = agent.ask(question, **daily)
            except Exception as error:  # noqa: BLE001 — a failed call is a row, not the end of the run
                print(f"✗ {question}: {type(error).__name__} {error}")
                rows.append({"question": question, "error": str(error)})
                bad += 1
                continue
            called = [c["tool"] for c in reply.tool_calls]
            rule = reply.route.split("·")[1] if reply.route else ""
            ok_route = rule.startswith(RULES[kind]) and (kind != "routed" or rule != "ROUTE-EXPLICIT")
            ok_tool = (tool in called) if tool else (kind == "follow-up" or not set(called) & READING)
            ok = ok_route and ok_tool and not any(c["status"] == "NOT_ROUTED" for c in reply.tool_calls)
            bad += not ok
            size = len(re.sub(r"\s", "", reply.text))
            print(f"{'✓' if ok else '✗'} {question[:30]:<32} 路由:{reply.route}  "
                  f"工具:{','.join(f'{c['tool']}({c['status']})' for c in reply.tool_calls) or '-'}  {size}字  "
                  f"{'；'.join(reply.checks) or '干净'}  {round(time.time() - start, 1)}s")
            rows.append({"question": question, "route": reply.route, "tools": reply.tool_calls, "checks": reply.checks,
                         "chars": size, "validated": reply.validated, "answer": reply.text, "ok": ok})
    print(f"\n{len(rows)} 轮，{bad} 轮不符合预期")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
