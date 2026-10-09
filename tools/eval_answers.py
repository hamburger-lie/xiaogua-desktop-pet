"""How often does the model break the answer rules, and what is left after the harness?

Asks a fixed set of questions through the configured provider (live calls, small cost),
in memory only: your history and memory are not touched.

    python tools/eval_answers.py               # each question twice
    python tools/eval_answers.py --rounds 3 --out eval.json --only 面试

For every answer: what the harness fixed or sent back (Reply.checks), and a fresh review of
the final text, which should find nothing. Answers that mention a time of day are printed
in full so a person can confirm the checker did not miss one.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime

from meihua.companion import config, harness
from meihua.companion.agent import make_agent
from meihua.companion.memory import Memory
from meihua.companion.session import Session, answer_facts

QUESTIONS = [
    "今天宜什么",
    "我今天适合干嘛",
    "今天什么时辰出门好",
    "今天下午去面试能成吗",
    "今天去签合同行吗，几点去好",
    "明天适合理发吗",
    "这周哪天适合搬家",
    "十分钟后提醒我喝水",
]
TIME_WORDS = ("点", "时辰", "子时", "丑时", "寅时", "卯时", "辰时", "巳时", "午时", "未时", "申时", "酉时", "戌时", "亥时")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--zodiac", default="羊")
    parser.add_argument("--out", default=None)
    parser.add_argument("--only", default=None, help="只问包含这几个字的问题")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = config.Config.load()
    key, _ = config.api_key(cfg.provider)
    print(f"厂商 {cfg.provider}  模型 {cfg.model}  深度思考 {cfg.deep_thinking}  每题 {args.rounds} 遍\n")
    rows, raw, left = [], Counter(), Counter()
    for question in QUESTIONS:
        if args.only and args.only not in question:
            continue
        for _ in range(args.rounds):
            agent = make_agent(cfg.model, key, cfg.provider, cfg.base_url, cfg.deep_thinking)
            agent.session = Session(None)
            agent.session.memory = Memory()
            agent.session.zodiac = args.zodiac
            looked_up = []                                    # 黄历 pages the agent fetched: same facts as it had
            run_tool = agent._run_tool

            def watched(name, arguments, run=run_tool, seen=looked_up):
                out = run(name, arguments)
                if name == "almanac_day":
                    seen.append(out)
                return out

            agent._run_tool = watched
            start = time.time()
            try:
                reply = agent.ask(question)
            except Exception as error:  # noqa: BLE001 — a failed call is a row, not the end of the run
                print(f"{question}: 出错 {type(error).__name__}")
                rows.append({"question": question, "error": str(error)[:200]})
                continue
            seconds = round(time.time() - start, 1)
            facts = answer_facts(args.zodiac)
            for page in looked_up:
                facts.add_page(page)
            after = harness.review(reply.text, facts)
            for check in reply.checks:
                raw[check.split("×")[0].split("「")[0]] += 1
            for fix in after.fixes:
                left[fix.split("×")[0]] += 1
            if after.wrong_hours:
                left["时辰"] += 1
            rows.append({"question": question, "seconds": seconds, "checks": reply.checks,
                         "left": after.fixes + after.wrong_hours, "mood": reply.mood, "answer": reply.text})
            print(f"{question}  {seconds}s  {'；'.join(reply.checks) or '干净'}")
            for fact in agent.session.memory.facts:           # a reminder: was the minute worked out right?
                if fact.time:
                    asked = datetime.fromtimestamp(start)
                    print(f"    提醒记成 {fact.date} {fact.time}「{fact.text}」（问的时候 {asked:%H:%M}）")
            if any(w in reply.text for w in TIME_WORDS):
                print("    " + reply.text.replace("\n", " / "))
    answered = [r for r in rows if "answer" in r]
    clean = sum(1 for r in answered if not [c for c in r["checks"] if c != "漏情绪标签"])
    print(f"\n{len(answered)} 条回答，模型原样就合规的 {clean} 条")
    print("模型原样回答里查出的：" + ("、".join(f"{k} {v} 次" for k, v in raw.most_common()) or "无"))
    print("经过 harness 之后还剩：" + ("、".join(f"{k} {v} 次" for k, v in left.most_common()) or "无"))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"raw": raw, "left": left, "rows": rows}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
