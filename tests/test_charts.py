"""紫微 and 奇门 in 小瓜: the chart tools, and what the harness lets an answer say of a chart."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from meihua.companion import charts, harness
from meihua.companion.agent import XiaoguaAgent
from meihua.companion.session import Session

from test_companion_agent import ScriptedClient, text, tool  # noqa: E402

SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 27, 15, 0, tzinfo=SHANGHAI)
LATE = datetime(2026, 10, 27, 23, 30, tzinfo=SHANGHAI)          # 23:00 换日: a candidate chart
PLAIN = "1995-05-12 10:30"        # 女: 命宫在子 (no main star), 身宫在夫妻宫, 火六局, 天机化禄
LATE_BIRTH = "1995-05-12 23:30"   # 男: 晚子时, two charts; 巨门坐命 in one, in 疾厄 in the other


def drawn(output: dict) -> harness.Facts:
    facts = harness.Facts()
    facts.add_chart(output)
    return facts


# --- the tables ---------------------------------------------------------------------

def test_every_star_door_and_god_the_engines_place_has_a_meaning():
    stars = charts.meanings("ziwei-stars.md")
    symbols = charts.meanings("qimen-symbols.md")
    assert len(stars) == 18 and all("原文：" in v for v in stars.values())
    assert len(symbols) == 25
    board = charts.ziwei_chart("q", PLAIN, "女", now=NOW)["盘"]
    assert {s for row in board["十二宫"] for s in row["主星"]} <= set(stars)
    qimen = charts.qimen_chart("q", now=NOW)["盘"]
    assert {row.get(p) for row in qimen["九宫"] for p in ("星", "寄星", "门", "神")} - {None} <= set(symbols)


# --- the tools ----------------------------------------------------------------------

def test_a_ziwei_chart_comes_with_its_gist_the_decade_now_and_a_passing_gate():
    out = charts.ziwei_chart("用紫微斗数看看我的性格", PLAIN, "女", now=NOW)
    assert out["status"] == "OK" and out["gate"] == "PASS" and out["置信"] == "A" and "候选盘" not in out
    assert out["要点"].startswith("命宫在子（戊子），无主星（借对宫主星参看）；身宫在夫妻宫（戌）；火六局")
    assert out["现在"] == "虚岁32，走福德宫这一限（26—35岁）"
    assert "时辰" in out                                      # no longitude: says true solar time would be closer


def test_late_zi_gives_a_candidate_chart_and_what_differs():
    out = charts.ziwei_chart("q", LATE_BIRTH, "男", 113.26, now=NOW)
    assert out["置信"].startswith("B") and len(out["候选盘"]) == 1
    assert "命宫：主星 巨门 / 无" in out["候选盘"][0]["不同"] and "按出生地真太阳时" in out["出生"]


def test_a_birth_in_a_summer_time_year_gets_its_own_offset():
    assert charts.ziwei_chart("q", "1990-05-12 10:30", "男", now=NOW)["status"] == "OK"     # +09:00 then


@pytest.mark.parametrize("birth, sex, missing", [("1995年5月12日", "男", "birth"), ("", "女", "birth"),
                                                 (PLAIN, "", "sex"), (PLAIN, "不说", "sex")])
def test_a_missing_birth_time_or_sex_is_asked_for_not_guessed(birth, sex, missing):
    out = charts.ziwei_chart("q", birth, sex, now=NOW)
    assert out["status"] == "NEED_INPUT" and out["missing"] == missing


def test_an_impossible_date_is_an_input_error():
    assert charts.ziwei_chart("q", "1995-02-30 10:30", "男", now=NOW)["status"] == "INVALID_INPUT"


def test_a_question_about_lifespan_is_drawn_but_that_part_is_not_read():
    out = charts.ziwei_chart("用紫微看看我能活多久，事业怎么样", PLAIN, "女", now=NOW)
    assert out["status"] == "OK" and "寿命" in out["不谈"]


def test_a_qimen_chart_for_now():
    out = charts.qimen_chart("用奇门看看下午见客户", now=NOW)
    assert out["gate"] == "PASS" and out["置信"] == "A"
    assert out["要点"] == "霜降下元，阴遁二局；值符天芮落兑（盘上西），值使死门落震（盘上东）"
    late = charts.qimen_chart("q", now=LATE)
    assert late["置信"].startswith("B") and "值符：天蓬 / 天芮" in late["候选盘"][0]["不同"]


@pytest.mark.parametrize("question", ["用奇门看看今晚下注买哪队", "奇门看看怎么报复他", "用奇门看看怎么躲警察"])
def test_qimen_is_not_drawn_for_what_guard_07_rules_out(question):
    assert charts.qimen_chart(question, now=NOW)["status"] == "NOT_FOR_THIS"


def test_a_follow_up_on_the_same_matter_keeps_its_qimen_chart(tmp_path):
    session = Session(tmp_path)
    first = session.run_daily_tool("qimen_chart", {"question": "下午见客户"}, now=NOW)
    later = datetime(2026, 10, 27, 17, 30, tzinfo=SHANGHAI)                       # another 时辰
    again = session.run_daily_tool("qimen_chart", {"question": "那要带合同吗", "follow_up": True}, now=later)
    assert again["status"] == "REUSED" and again["要点"] == first["要点"] and "15:00" in again["note"]
    fresh = session.run_daily_tool("qimen_chart", {"question": "晚上约朋友"}, now=later)
    assert fresh["status"] == "OK" and fresh["要点"] != first["要点"]


def test_the_chart_tools_are_offered(tmp_path):
    client = ScriptedClient([[text("在的。\n〔平静〕")]])
    XiaoguaAgent(client=client, session=Session(tmp_path)).ask("你好")
    assert {"ziwei_chart", "qimen_chart"} <= {t["name"] for t in client.requests[0]["tools"]}


# --- what an answer may say of a drawn chart ---------------------------------------------

@pytest.mark.parametrize("sentence", [
    "你命宫在子，没有主星，借对宫来看。", "天机化禄落在夫妻宫，资源跟伴侣有关。", "紫微和七杀在兄弟宫。",
    "兄弟宫有紫微、七杀。", "你是火六局。", "身宫在夫妻宫。", "太阴化忌在迁移宫，出门在外容易操心。"])
def test_what_is_on_the_chart_passes(sentence):
    facts = drawn(charts.ziwei_chart("q", PLAIN, "女", now=NOW))
    assert harness.chart_slips(sentence, facts.charts) == []
    assert harness.made_up_charts(sentence, "用紫微看看我", facts.drawn) == []


@pytest.mark.parametrize("sentence, why", [
    ("你命宫在午，主星是太阳。", "命宫说成午"), ("你是巨门坐命，爱较真。", "巨门所在的宫说成命宫"),
    ("太阳化禄，名声带财。", "化禄的星说成太阳"), ("你是金四局。", "局数说成金四局"),
    ("天机化禄在财帛宫。", "化禄所在的宫说成财帛"), ("命主是武曲。", "命主说成武曲")])
def test_what_is_not_on_it_is_caught(sentence, why):
    slips = harness.chart_slips(sentence, drawn(charts.ziwei_chart("q", PLAIN, "女", now=NOW)).charts)
    assert slips and slips[0][1].startswith(why)


def test_with_a_candidate_chart_one_side_alone_is_caught_and_both_sides_pass():
    facts = drawn(charts.ziwei_chart("q", LATE_BIRTH, "男", now=NOW))
    one_side = harness.chart_slips("你是巨门坐命。", facts.charts)
    assert one_side and "只说了一边" in one_side[0][1]
    assert harness.chart_slips("巨门坐命或者在疾厄宫，两张盘不一样。", facts.charts) == []
    assert harness.chart_slips("命宫在巳，两张盘都一样。", facts.charts) == []     # what both share is said flat


@pytest.mark.parametrize("sentence, ok", [
    ("阴遁二局，值符天芮落兑，值使死门落震。", True), ("开门在离，适合开局。", True),
    ("阳遁二局。", False), ("值符是天蓬。", False), ("值使落坎宫。", False), ("生门在中间那一宫。", True)])
def test_a_qimen_answer_is_read_back_against_the_board(sentence, ok):
    facts = drawn(charts.qimen_chart("q", now=NOW))
    assert (harness.chart_slips(sentence, facts.charts) == []) is ok


@pytest.mark.parametrize("system, sentence", [
    ("紫微斗数", "疾厄宫有破军，寿命不会太长。"), ("紫微斗数", "夫妻宫化忌，婚姻容易失败。"),
    ("奇门遁甲", "值符落兑，今晚下注能赢。"), ("奇门遁甲", "生门在东南，你往东南走去谈。")])
def test_guard_07_lines_are_caught(system, sentence):
    assert harness.crossed_lines(sentence, {system}) == [sentence]


@pytest.mark.parametrize("sentence", ["寿命、健康这些紫微不看，身体的事听医生的。", "疾厄宫有破军。",
                                      "值使落在盘上东边那一宫，主了结。"])
def test_holding_back_or_plain_chart_talk_is_not_crossing(sentence):
    assert harness.crossed_lines(sentence, {"紫微斗数", "奇门遁甲"}) == []


def test_a_chart_hour_is_not_a_good_hour_claim():
    facts = harness.Facts()
    facts.days.append(harness.DayHours("今天", ["午"], ["午"]))
    assert harness.wrong_hours("你是子时出生的，适合安静做事。", facts) == []
    assert harness.wrong_hours("子时出门最合适。", facts) == ["子时出门最合适。"]


def test_evidence_ids_of_the_new_packs_are_taken_out_of_the_answer():
    assert harness.polish("命宫在子（ZW-01、QM-02）。")[0] == "命宫在子。"


# --- in the agent ---------------------------------------------------------------------

ZIWEI_Q = "用紫微斗数看看我的性格，1995年5月12日上午10点半出生，女"


def test_named_ziwei_is_drawn_and_an_answer_true_to_the_chart_goes_out(tmp_path):
    answer = "你命宫在子，没有主星，借对宫来看，性子随境况变。天机化禄落在夫妻宫，资源多从合作里来。\n〔平静〕"
    client = ScriptedClient([[tool("ziwei_chart", question=ZIWEI_Q, birth=PLAIN, sex="女")], [text(answer)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask(ZIWEI_Q)
    told = client.requests[0]["messages"][-1]["content"][-1]["text"]
    assert "ziwei_chart" in told and "小瓜只会" not in told
    assert reply.validated and reply.text.startswith("你命宫在子") and not reply.checks
    assert reply.tool_calls == [{"tool": "ziwei_chart", "status": "OK"}]


def test_a_chart_said_wrong_goes_back_once_then_the_sentence_goes(tmp_path):
    wrong = "你是巨门坐命，爱较真。天机化禄落在夫妻宫，资源多从合作里来。\n〔平静〕"
    client = ScriptedClient([[tool("ziwei_chart", question=ZIWEI_Q, birth=PLAIN, sex="女")],
                             [text(wrong)], [text(wrong)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask(ZIWEI_Q)
    sent_back = client.requests[2]["messages"][-1]["content"][0]["text"]
    assert "对不上" in sent_back and "命宫在子" in sent_back
    assert reply.checks[0].startswith("退回:盘面说错") and "删掉说错的盘面" in reply.checks
    assert reply.text == "天机化禄落在夫妻宫，资源多从合作里来。"


def test_chart_words_without_drawing_go_back_with_the_tool_to_call(tmp_path):
    made_up = "你命宫坐紫微，今年化禄入财帛宫。\n〔开心〕"
    client = ScriptedClient([[text(made_up)], [text(made_up)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("用紫微斗数帮我看看")
    assert "要说先调 ziwei_chart" in client.requests[1]["messages"][-1]["content"][0]["text"]
    assert reply.text == "紫微斗数得先排出盘才能说：告诉我公历出生日期、几点几分和性别。"


def test_the_old_i_cannot_goes_back_in_daily_mode(tmp_path):
    client = ScriptedClient([[text("紫微斗数小瓜不会，我只会梅花和黄历。\n〔平静〕")],
                             [text("能排。告诉我公历出生日期、几点几分和性别。\n〔平静〕")]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("用紫微斗数帮我看看")
    assert "现在能排了" in client.requests[1]["messages"][-1]["content"][0]["text"]
    assert reply.text.startswith("能排。") and reply.checks == ["退回:说不会紫微斗数"]


def test_a_qimen_reading_with_a_compass_direction_loses_that_sentence(tmp_path, monkeypatch):
    monkeypatch.setattr("meihua.companion.session._now", lambda: NOW)     # the answer below is NOW's chart
    said = "值符天芮落兑，值使死门落震，今天宜收尾。你往西走去谈更顺。\n〔平静〕"
    client = ScriptedClient([[tool("qimen_chart", question="用奇门看看下午见客户")], [text(said)], [text(said)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("用奇门看看下午见客户")
    assert reply.validated and reply.checks[0].startswith("退回:越界") and "删掉越界的话" in reply.checks
    assert "往西" not in reply.text and reply.text.startswith("值符天芮落兑")


def test_offline_draws_qimen_and_asks_for_a_model_for_ziwei():
    from meihua.companion.app import OfflineAgent
    assert OfflineAgent().ask("用奇门遁甲看看下午见客户").text.startswith("离线奇门（")
    assert "接上模型才行" in OfflineAgent().ask("用紫微斗数看看我").text
    assert OfflineAgent().ask("用奇门看看今晚下注").text.startswith("奇门不用于赌博下注")
