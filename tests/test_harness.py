"""The harness around 小瓜's answers: wording fixed by code, 时辰 checked against the 黄历 code worked out."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from meihua.companion import harness
from meihua.companion.agent import XiaoguaAgent
from meihua.companion.session import Session, answer_facts

from test_companion_agent import ScriptedClient, text  # noqa: E402


def facts_with(*branches: str, today=date(2026, 10, 8), now=datetime(2026, 10, 8, 9, 0)) -> harness.Facts:
    facts = harness.Facts(today=today, now=now)
    facts.days.append(harness.DayHours("今天", list(branches), list(branches)))
    return facts


# --- wording --------------------------------------------------------------------

def test_a_dash_the_model_used_becomes_a_comma():
    seen = "今天跟你三合，日子顺——不过黄历说其余的事别做，签合同缓一缓。"    # a real answer
    fixed, fixes = harness.polish(seen)
    assert fixed == "今天跟你三合，日子顺，不过黄历说其余的事别做，签合同缓一缓。" and fixes == ["破折号×1"]


def test_markdown_stock_phrases_and_overclaiming_are_taken_out():
    fixed, fixes = harness.polish("**能签**，建议你先看条款。\n值得注意的是，今天冲你（MH-01、MH-07）。\n"
                                  "- 先问清付款\n这事必然顺，不建议你今天签。")
    assert fixed == "能签，你先看条款。\n今天冲你。\n先问清付款\n这事多半顺，最好别今天签。"
    assert {f.split("×")[0] for f in fixes} == {"加粗", "套话", "证据编号", "清单符号", "说死"}


def test_a_clean_answer_is_left_alone():
    clean = "能签，早点去。\n益变屯，开头顺，收尾见好就收。"
    assert harness.polish(clean) == (clean, [])


# --- 时辰 -----------------------------------------------------------------------

def test_the_hour_the_model_got_wrong_is_caught():
    facts = facts_with("酉", "戌")                       # the 黄历 said 傍晚五点到七点
    said = "能成，稳着去。下午五点前都是好时辰，早点到。"    # what the model said (「面试能成吗」)
    assert harness.wrong_hours(said, facts) == ["下午五点前都是好时辰，早点到。"]


@pytest.mark.parametrize("sentence", [
    "傍晚五点到七点这个时辰不错。", "酉时出门最好。", "傍晚五六点去最合适。", "傍晚五点到七点之间去最好。", "傍晚五点到晚上九点都合适。", "17:00-18:59 是好时辰。",
    "晚上七点到九点出门也行，时辰好。"])
def test_hours_inside_the_good_ones_pass(sentence):
    assert harness.wrong_hours(sentence, facts_with("酉", "戌")) == []


@pytest.mark.parametrize("sentence", [
    "下午三点到五点是好时辰。", "申时出门不错。", "五点以后都是好时候。", "上午十点出门最好。", "下午三四点去最合适。"])
def test_hours_outside_them_do_not(sentence):
    assert harness.wrong_hours(sentence, facts_with("酉", "戌")) == [sentence]


@pytest.mark.parametrize("sentence", [
    "下午三点那个时辰别出门。", "早一点到，留一点余地最合适。", "十二时辰里今天酉时最好。", "你三点的面试能成。"])
def test_what_is_not_a_good_hour_claim_is_not_checked(sentence):
    assert harness.wrong_hours(sentence, facts_with("酉")) == []


@pytest.mark.parametrize("branch", list(harness.BRANCH_HOURS))
def test_every_hour_in_words_reads_back_as_that_hour(branch):
    said = f"{harness.clock_words(*harness.BRANCH_HOURS[branch])}是好时辰。"
    assert harness.wrong_hours(said, facts_with(branch)) == []
    other = next(b for b in harness.BRANCH_HOURS if abs(harness.BRANCH_HOURS[b][0] - harness.BRANCH_HOURS[branch][0]) > 2)
    assert harness.wrong_hours(said, facts_with(other)) == [said]


@pytest.mark.parametrize("sentence", ["十几点去都合适。", "五六七点都是好时辰。", "二十五点出门最好。", "一十点合适。"])
def test_odd_numbers_never_break_the_check(sentence):
    harness.wrong_hours(sentence, facts_with("酉"))                     # no exception, whatever it decides


def test_a_fault_in_the_harness_lets_the_answer_through(tmp_path, monkeypatch):
    def broken(*_):
        raise RuntimeError("bug")
    monkeypatch.setattr(harness, "review", broken)
    client = ScriptedClient([[text("傍晚五点到七点去。\n〔开心〕")]])
    assert XiaoguaAgent(client=client, session=Session(tmp_path)).ask("几点去").text == "傍晚五点到七点去。"


def test_nothing_to_check_against_means_nothing_is_flagged():
    assert harness.wrong_hours("下午五点前都是好时辰。", harness.Facts()) == []


def test_another_day_looked_up_is_checked_too():
    from meihua.companion import tools
    facts = harness.Facts(today=date(2026, 10, 8), now=datetime(2026, 10, 8, 9, 0))
    facts.add_page(tools.almanac_day("2026-10-09", "羊"))
    assert facts.days[0].label == "10月9日" and facts.days[0].branches


def test_the_context_gives_the_hours_in_words():
    from meihua.companion.session import daily_context_text
    line = daily_context_text("羊", datetime(2026, 10, 8, 9, 0).astimezone())
    assert "（下午一点到三点）" in line or "（傍晚五点到七点）" in line


# --- in the agent ---------------------------------------------------------------

def today_hour(facts: harness.Facts) -> str:
    branch = (facts.days[0].ahead or facts.days[0].branches)[0]
    return harness.clock_words(*harness.BRANCH_HOURS[branch])


def test_a_wrong_hour_goes_back_once_and_the_fixed_answer_is_shown(tmp_path):
    session = Session(tmp_path)
    session.zodiac = "羊"
    right = today_hour(answer_facts("羊"))
    client = ScriptedClient([[text("能成。下午五点前都是好时辰。\n〔开心〕")],
                             [text(f"能成。{right}是好时辰。\n〔开心〕")]])
    reply = XiaoguaAgent(client=client, session=session).ask("今天面试能成吗")
    assert reply.text == f"能成。{right}是好时辰。" and reply.checks[0] == "退回:时辰「下午五点前都是好时辰。」"
    sent_back = client.requests[1]["messages"][-1]["content"][0]["text"]
    assert "对不上" in sent_back and "下午五点前" in sent_back


def test_still_wrong_after_the_redo_code_says_the_hours(tmp_path):
    session = Session(tmp_path)
    session.zodiac = "羊"
    wrong = "能成。下午五点前都是好时辰。\n〔开心〕"
    client = ScriptedClient([[text(wrong)], [text(wrong)]])
    reply = XiaoguaAgent(client=client, session=session).ask("今天面试能成吗")
    assert "五点前" not in reply.text and reply.text.startswith("能成。")
    assert "好时辰" in reply.text and "时辰改由程序说" in reply.checks
    assert len(client.requests) == 2                                   # one redo, no more


def test_wording_is_fixed_before_it_is_shown_and_remembered(tmp_path):
    session = Session(tmp_path)
    client = ScriptedClient([[text("在的——今天想问点什么？")]])
    agent = XiaoguaAgent(client=client, session=session)
    reply = agent.ask("你好")
    assert reply.text == "在的，今天想问点什么？"
    assert "破折号×1" in reply.checks and "漏情绪标签" in reply.checks
    assert session.chat.daily and all("——" not in t["a"] for t in session.chat.daily)


# --- shape: verdict first, no runaway length --------------------------------------

@pytest.mark.parametrize("answer", [
    "今天下午这场面试，成不成不好说，但你这边气场是往外输出的。",          # real answers that buried the verdict
    "今天下午这场面试，卦象说：你能好好表现出来，但决定权多半在对方那一头。",
    "卦象是个「鼎」，意思是这事本身是成型的、能立住的，跟你也没有相冲。",
    "今天跟你三合，日子顺，下午五点到七点还是好时辰，赶得上。"])
def test_a_yes_no_question_answered_reason_first_is_caught(answer):
    assert harness.verdict_late(answer, "今天下午去面试能成吗")


@pytest.mark.parametrize("answer", [
    "今天能签，卦里是个「鼎」，立得稳。", "行，今天去签这事能成。", "明天不太适合理发，它是个破日。",
    "下午去面试能成，但未必当场拍板。", "面试嘛，能成，早点到。", "先别签，条款再看两天。"])
def test_a_verdict_up_front_passes(answer):
    assert not harness.verdict_late(answer, "今天去签合同行吗")


def test_only_yes_no_questions_need_a_verdict_first():
    assert not harness.verdict_late("这周能搬的日子里，最合适的是周日。", "这周哪天适合搬家")
    assert not harness.verdict_late("今天宜祭拜，别的事别做。", "今天宜什么")


def test_length_is_checked_against_the_limit():
    facts = harness.Facts(max_chars=20)
    assert harness.review("能签，早点去。", facts).too_long == 0
    assert harness.review("去" * 30, facts).too_long == 30


def test_a_buried_verdict_goes_back_once(tmp_path):
    client = ScriptedClient([[text("今天下午这场面试，成不成不好说，看你发挥。\n〔犹豫〕")],
                             [text("能成，早点到，先讲结果再讲过程。\n〔开心〕")]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("今天下午去面试能成吗")
    assert reply.text.startswith("能成") and reply.checks == ["退回:结论在后「今天下午这场面试，成不成不好说，看你发挥」"]
    assert "先给结论" in client.requests[1]["messages"][-1]["content"][0]["text"]


def test_a_second_miss_goes_out_as_it_is(tmp_path):
    buried = "今天下午这场面试，成不成不好说，看你发挥。\n〔犹豫〕"
    client = ScriptedClient([[text(buried)], [text(buried)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("今天下午去面试能成吗")
    assert reply.text.startswith("今天下午这场面试") and "仍结论在后" in reply.checks
    assert len(client.requests) == 2


def test_several_problems_share_one_send_back(tmp_path):
    session = Session(tmp_path)
    session.zodiac = "羊"
    client = ScriptedClient([[text("今天这事，卦象说得看你。下午五点前都是好时辰。\n〔犹豫〕")],
                             [text(f"能成。{today_hour(answer_facts('羊'))}是好时辰。\n〔开心〕")]])
    reply = XiaoguaAgent(client=client, session=session).ask("今天面试能成吗")
    sent = client.requests[1]["messages"][-1]["content"][0]["text"]
    assert "时辰" in sent and "先给结论" in sent and len(client.requests) == 2
    assert reply.checks[0] == "退回:时辰「下午五点前都是好时辰。」" and reply.checks[1].startswith("退回:结论在后「")


def test_a_runaway_answer_is_sent_back(tmp_path):
    client = ScriptedClient([[text("今天适合出门。" + "天气也不错。" * 50 + "\n〔开心〕")],
                             [text("今天适合出门，下午最好。\n〔开心〕")]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("今天出去玩好吗")
    assert reply.text == "今天适合出门，下午最好。" and reply.checks[0].startswith("退回:太长")
