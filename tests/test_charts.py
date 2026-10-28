"""紫微、奇门、八字、小六壬、风水 in 小瓜: the chart tools, and what the harness lets an answer say of a chart."""

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


def test_a_named_chart_tool_is_offered_alone(tmp_path):
    client = ScriptedClient([[text("要出生时间。\n〔平静〕")]])
    XiaoguaAgent(client=client, session=Session(tmp_path)).ask("用紫微斗数看看我")
    offered = {t["name"] for t in client.requests[0]["tools"]}
    assert "ziwei_chart" in offered and not offered & {"qimen_chart", "bazi_chart", "daily_reading", "space_check"}


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
    said ="值符天芮落兑，值使死门落震，今天宜收尾。你往西走去谈更顺。\n〔平静〕"
    client = ScriptedClient([[tool("qimen_chart", question="用奇门看看下午见客户")], [text(said)], [text(said)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("用奇门看看下午见客户")
    assert reply.validated and reply.checks[0].startswith("退回:越界") and "删掉越界的话" in reply.checks
    assert "往西" not in reply.text and reply.text.startswith("值符天芮落兑")


def test_offline_draws_qimen_and_asks_for_a_model_for_ziwei():
    from meihua.companion.app import OfflineAgent
    assert OfflineAgent().ask("用奇门遁甲看看下午见客户").text.startswith("离线奇门（")
    assert "接上模型才行" in OfflineAgent().ask("用紫微斗数看看我").text
    assert OfflineAgent().ask("用奇门看看今晚下注").text.startswith("奇门不用于赌博下注")


# --- 奇门挑时辰 (QM-08) ---------------------------------------------------------------------

MORNING = datetime(2026, 10, 27, 10, 20, tzinfo=SHANGHAI)       # asked in the morning about the afternoon


def afternoon(matter="求财", question="用奇门看看下午几点去见客户好"):
    return charts.qimen_pick(question, matter, "2026-10-27 13:00", "2026-10-27 19:00", now=MORNING)


def test_the_matter_table_gives_each_matter_its_doors_and_main_door():
    matters = charts.pick_matters()
    assert len(matters) == 11 and matters["求财"]["主门"] == "生门" and matters["求财"]["门"] == ["生门", "开门", "休门"]
    assert matters["移徙"]["主门"] is None and matters["上书献策"]["门"] == ["景门"]


def test_hours_rank_by_main_door_with_a_wonder_then_any_door_with_one():
    out = afternoon()
    assert out["status"] == "OK" and out["kind"] == "挑时辰" and out["gate"] == "PASS"
    assert out["要点"] == "主门合奇的时辰：未时、申时"
    assert out["排序"] == [
        "未时 10月27日 13:00—15:00：主门合奇，生门合丙奇（乾，盘上西北，门生宫）、休门合乙奇（兑，盘上西，宫生门，得地）",
        "申时 10月27日 15:00—17:00：主门合奇，生门合丁奇（兑，盘上西，门生宫）、开门合丙奇（离，盘上南，宫克门，受制，不算）",
        "酉时 10月27日 17:00—19:00：门奇会合·得地，开门合丁奇（乾，盘上西北，比和，得地）"]
    assert "得时" in out["边界"] and set(out["象义"]) == {"生门", "开门", "休门"}


def test_without_a_main_door_a_grounded_meeting_leads_and_a_restrained_door_does_not_count():
    out = charts.qimen_pick("q", "移徙", "2026-10-28 07:00", "2026-10-28 17:00", now=MORNING)
    assert out["要点"] == "门奇会合且得地的时辰：未时"
    assert out["排序"][2] == "巳时 10月28日 09:00—11:00：有门无奇，生门合乙奇（巽，盘上东南，宫克门，受制，不算）"


@pytest.mark.parametrize("door, palaces", [("开门", "震巽"), ("休门", "离"), ("生门", "坎"), ("伤门", "坤艮"),
                                           ("杜门", "坤艮"), ("景门", "乾兑"), ("死门", "坎"), ("惊门", "震巽")])
def test_every_pair_in_the_tongzong_table_of_forcing_reads_forced(door, palaces):
    assert {charts.door_ground(door, palace) for palace in palaces} == {"迫"}           # 统宗 lines 129-133


def test_the_open_door_example_of_fanli_five():
    """「开门…其性属金，如临土宫、金位…得地…临于木火，则金气大衰」"""
    assert {p: charts.door_ground("开门", p) for p in "坤艮乾兑离震"} == {
        "坤": "义", "艮": "义", "乾": "比和", "兑": "比和", "离": "制", "震": "迫"}


def test_past_hours_are_not_picked():
    assert charts.qimen_pick("q", "求财", "2026-10-27 06:00", "2026-10-27 08:00", now=MORNING)["status"] == "ALL_PAST"
    out = charts.qimen_pick("q", "求财", "2026-10-27 08:00", "2026-10-27 13:00", now=MORNING)
    assert [row["时辰"] for row in out["时辰"]] == ["巳时", "午时"] and out["说明"] == "已经过去的时辰没排"
    assert len(charts.qimen_pick("q", "求财", now=MORNING)["时辰"]) == charts.MAX_PICK_HOURS


def test_late_night_hours_say_when_the_two_day_changes_disagree():
    out = charts.qimen_pick("q", "见贵", "2026-10-27 21:00", "2026-10-28 03:00", now=MORNING)
    late = next(row for row in out["时辰"] if row["时辰"] == "子时")
    assert "两说" in late and out["排序"][2].startswith("子时") and out["排序"][2].endswith("（两说）")
    assert out["排序"][0].startswith("亥时") and "休门合乙奇（离，盘上南，门迫，不算）" in out["排序"][0]


def test_the_matter_is_filed_by_the_table_when_his_words_name_one():
    out = charts.qimen_pick("用奇门看看明天几点去见客户好", "见贵", "2026-10-27 13:00", "2026-10-27 19:00", now=MORNING)
    assert out["事"].startswith("求财") and out["说明"] == "他的话照表归为求财，不是见贵"
    assert charts.qimen_pick("用奇门挑个时辰", "见贵", now=MORNING)["事"].startswith("见贵")      # nothing named: his choice


@pytest.mark.parametrize("matter, question, status", [("炒股", "q", "UNKNOWN_MATTER"),
                                                      ("求财", "用奇门挑个时辰去下注", "NOT_FOR_THIS")])
def test_unknown_matters_and_what_qimen_is_not_for_are_refused(matter, question, status):
    assert charts.qimen_pick(question, matter, now=MORNING)["status"] == status


@pytest.mark.parametrize("sentence, hours, slips", [
    ("下午一点到三点去最好，生门合丙奇。", False, False), ("傍晚五点到七点也行。", False, False),
    ("值符天蓬落坎，未时最顺。", False, True), ("中午十一点到一点去最好。", True, False)])
def test_a_pick_answer_is_read_back_against_its_hours(sentence, hours, slips):
    facts = harness.Facts(today=MORNING.date(), now=MORNING)
    facts.add_chart(afternoon())
    assert bool(harness.wrong_hours(sentence, facts)) is hours and bool(harness.chart_slips(sentence, facts.charts)) is slips


def test_named_qimen_picks_hours_and_the_picked_hour_goes_out(tmp_path, monkeypatch):
    monkeypatch.setattr("meihua.companion.session._now", lambda: MORNING)
    question = "用奇门看看下午几点去见客户好"
    answer = "下午一点到三点去最顺，生门合丙奇。这只看了门奇会合，没看衰旺，当个参考。\n〔平静〕"
    client = ScriptedClient([[tool("qimen_pick", question=question, matter="求财", start="2026-10-27 13:00",
                                   end="2026-10-27 19:00")], [text(answer)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask(question)
    told = client.requests[0]["messages"][-1]["content"][-1]["text"]
    assert "qimen_pick" in told
    assert reply.validated and reply.text.startswith("下午一点到三点去最顺") and not reply.checks


# --- 风水: space observation (SPACE-01) ----------------------------------------------------

DAMP_ROOM = "我卧室朝北，特别潮，墙角发霉，睡不好"


def test_the_space_checklist_covers_the_items_space_01_names():
    assert list(charts.space_items()) == ["采光", "通风", "潮湿", "噪声", "动线", "隐私", "收纳", "消防与结构安全"]


def test_a_room_gets_the_items_its_words_touch_and_its_direction_as_tradition():
    out = charts.space_check(DAMP_ROOM, "卧室", "北", ["潮", "发霉", "睡不好"], "租房")
    assert out["status"] == "OK" and out["system"] == "风水" and out["gate"] == "PASS"
    assert [item["项"] for item in out["现实环境"]] == ["潮湿", "噪声"] and out["要点"] == "先看：潮湿、噪声"
    assert out["传统象征"]["卦"] == "坎" and out["传统象征"]["五行"] == "水" and "飞星宅盘没排" in out["传统象征"]["说明"]
    assert "还缺" not in out


def test_with_nothing_said_it_gives_the_whole_list_and_asks():
    out = charts.space_check("看看我家风水")
    assert len(out["现实环境"]) == 8 and "传统象征" not in out and out["还缺"].startswith("用途（哪个房间）、朝向")


@pytest.mark.parametrize("question, systems", [("看看我家的风水", ["风水"]), ("帮我排个玄空飞星宅盘", ["风水排盘"]),
                                               ("风水轮流转，这次能成吗", [])])
def test_feng_shui_is_space_observation_and_flying_stars_are_still_declined(question, systems):
    assert harness.asked_systems(question) == systems


@pytest.mark.parametrize("answer, shape", [
    ("卧室潮先看墙角有没有霉点，柜子离墙几厘米。老说法里北方属坎水，只当个参考。", ""),
    ("北方属坎水，水气重。墙角发霉就放除湿机。", "传统说法在前"), ("北方属坎，主智。", "没说现实环境")])
def test_a_feng_shui_answer_puts_the_real_room_first(answer, shape):
    assert harness.space_shape(answer) == shape


@pytest.mark.parametrize("sentence", ["这屋朝北容易生病。", "西南角放八卦镜能化煞。", "把那面承重墙拆了就亮了。"])
def test_what_feng_shui_is_not_read_for_is_caught(sentence):
    assert harness.crossed_lines(sentence, {"风水"}) == [sentence]


@pytest.mark.parametrize("sentence", ["千万别拆承重墙。", "不用买八卦镜那些东西。", "飞星宅盘这次没排。"])
def test_holding_back_on_feng_shui_is_not_crossing_or_made_up(sentence):
    assert harness.crossed_lines(sentence, {"风水"}) == [] and harness.made_up_charts(sentence, "看看风水", {"风水"}) == []


def test_named_feng_shui_draws_the_checklist_and_a_room_first_answer_goes_out(tmp_path):
    answer = "卧室潮先看墙角和柜背有没有霉点，柜子离墙几厘米，放个除湿机。老说法里北方属坎水，只当个参考。\n〔平静〕"
    client = ScriptedClient([[tool("space_check", question=DAMP_ROOM, space="卧室", facing="北", problems=["潮"])],
                             [text(answer)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("看看我卧室风水，" + DAMP_ROOM)
    assert reply.validated and reply.text.startswith("卧室潮先看墙角") and not reply.checks


def test_a_feng_shui_answer_with_no_real_room_gets_the_items_put_in_front(tmp_path):
    only_symbols = "北方属坎，主智，卧室在这儿利读书。\n〔平静〕"
    client = ScriptedClient([[tool("space_check", question=DAMP_ROOM, space="卧室", facing="北", problems=["潮"])],
                             [text(only_symbols)], [text(only_symbols)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask("看看我卧室风水，" + DAMP_ROOM)
    assert reply.checks[0] == "退回:没说现实环境" and "补:现实环境" in reply.checks
    assert reply.text.startswith("先看：潮湿、噪声。")


# --- 八字 and 小六壬 (since 2026-10-28) ---------------------------------------------------

BAZI_BIRTH = "1995-05-12 10:30"   # 乙亥 辛巳 癸卯 丁巳, 日主癸水; 男 at NOW: 第3步大运戊寅, 流年丙午


def test_the_ten_god_and_palace_tables_cover_what_the_engines_name():
    gods = charts.ten_god_meanings()
    assert {"比肩", "劫财", "食神", "伤官", "正财", "偏财", "正官", "七杀", "正印", "偏印", "地支六冲"} <= set(gods)
    palaces = charts.palace_meanings()
    assert set(palaces) == set(charts.PALACES) and all(len(kinds) == 5 for kinds in palaces.values())


def test_a_bazi_chart_comes_with_its_structure_the_decade_now_and_a_passing_gate():
    out = charts.bazi_chart("用八字看看我适合什么工作", BAZI_BIRTH, "男", 113.26, now=NOW)
    assert out["status"] == "OK" and out["gate"] == "PASS" and out["置信"] == "A"
    assert out["要点"] == "四柱 乙亥 辛巳 癸卯 丁巳；日主癸水，生在巳月（月令火）；天干透食神、偏印、偏财；巳亥六冲"
    assert out["现在"] == "第3步大运戊寅（22—32岁）；2026年流年丙午（正财）"
    assert "按出生地真太阳时 10:06" in out["出生"] and "时辰" not in out
    assert {"偏财", "地支六冲"} <= set(out["象义"])


def test_without_a_sex_there_is_no_decade_and_without_a_time_it_asks():
    out = charts.bazi_chart("q", BAZI_BIRTH, now=NOW)
    assert out["现在"].endswith("大运要知道性别才排") and "大运" not in out["盘"]
    assert charts.bazi_chart("q", "1995年5月12日", now=NOW)["status"] == "NEED_INPUT"


def test_a_late_zi_birth_gives_the_midnight_pillars_as_a_candidate():
    out = charts.bazi_chart("q", "1995-05-12 23:30", now=NOW)
    assert out["置信"].startswith("B") and out["候选盘"][0]["为什么"] == "23 点按零点换日（子正）算当天"
    assert "日柱：甲辰 / 癸卯" in out["候选盘"][0]["不同"]


def test_a_bazi_question_about_money_from_stocks_is_drawn_but_that_part_is_not_read():
    assert "投资收益" in charts.bazi_chart("用八字看看我炒股能不能发财", BAZI_BIRTH, now=NOW)["不谈"]


def test_a_xiaoliu_lesson_for_now_and_its_candidate_at_23():
    out = charts.xiaoliu_chart("用小六壬看看下午面试", now=NOW)
    assert out["gate"] == "PASS" and out["要点"] == "落赤口" and out["置信"] == "A"
    assert out["起课"] == "2026-10-27 15:00，农历9月18日 申时" and set(out["象义"]) == {"赤口"}
    late = charts.xiaoliu_chart("q", now=LATE)
    assert late["要点"] == "落留连" and late["候选盘"][0]["不同"] == ["课宫：留连 / 速喜"]


def test_a_follow_up_keeps_its_xiaoliu_lesson(tmp_path):
    session = Session(tmp_path)
    first = session.run_daily_tool("xiaoliu_chart", {"question": "下午面试"}, now=NOW)
    later = datetime(2026, 10, 27, 17, 30, tzinfo=SHANGHAI)
    again = session.run_daily_tool("xiaoliu_chart", {"question": "那要早点到吗", "follow_up": True}, now=later)
    assert again["status"] == "REUSED" and again["要点"] == first["要点"] and "这一课" in again["note"]


@pytest.mark.parametrize("sentence, ok", [
    ("你是癸水日主，生在巳月。", True), ("年干乙透食神，点子多。", True), ("现在走戊寅大运，今年丙午。", True),
    ("日主是甲。", False), ("月干辛是正官。", False), ("日柱甲辰。", False), ("现在走己卯运。", False),
    ("现在走偏印大运，适合靠手艺吃饭。", False), ("今年是偏印年。", False), ("2026年正财年，踏实积累。", True),
    ("现在走戊寅这步正官运。", True)])
def test_a_bazi_answer_is_read_back_against_the_pillars(sentence, ok):
    facts = drawn(charts.bazi_chart("q", BAZI_BIRTH, "男", 113.26, now=NOW))
    assert (harness.chart_slips(sentence, facts.charts) == []) is ok


@pytest.mark.parametrize("sentence", ["你日主偏弱，喜用神是金。", "你五行缺土，多穿黄色。", "这盘看你寿命长。",
                                      "七杀透出，婚姻容易失败。"])
def test_what_bazi_is_not_read_for_is_caught(sentence):
    assert harness.crossed_lines(sentence, {"八字"}) == [sentence]


def test_a_drawn_bazi_may_use_its_own_words():
    assert harness.made_up_charts("时干透七杀，日主癸水，规矩压力大。", "用八字看看我", {"八字"}) == []


@pytest.mark.parametrize("sentence, ok", [("这一课落赤口，说话留点神。", True), ("落在大安，稳。", False),
                                          ("小吉宫，小步推进。", False), ("留连落宫，就是拖。", False)])
def test_a_xiaoliu_answer_is_read_back_against_the_lesson(sentence, ok):
    facts = drawn(charts.xiaoliu_chart("q", now=NOW))
    assert (harness.chart_slips(sentence, facts.charts) == []) is ok


def test_a_xiaoliu_lesson_names_no_thief():
    assert harness.crossed_lines("落赤口，多半是被同事偷了。", {"小六壬"}) == ["落赤口，多半是被同事偷了。"]


def test_named_bazi_is_drawn_and_an_answer_true_to_it_goes_out(tmp_path):
    question = "帮我排个八字，1995年5月12日上午10点半出生，男"
    answer = "你是癸水日主，生在巳月，天干透食神和偏财，想法多也肯落地。\n〔平静〕"
    client = ScriptedClient([[tool("bazi_chart", question=question, birth=BAZI_BIRTH, sex="男")], [text(answer)]])
    reply = XiaoguaAgent(client=client, session=Session(tmp_path)).ask(question)
    told = client.requests[0]["messages"][-1]["content"][-1]["text"]
    assert "bazi_chart" in told and "小瓜只会" not in told
    assert reply.validated and reply.text.startswith("你是癸水日主") and not reply.checks


def test_offline_draws_xiaoliu_and_asks_for_a_model_for_bazi():
    from meihua.companion.app import OfflineAgent
    assert OfflineAgent().ask("用小六壬看看下午面试").text.startswith("离线小六壬（")
    assert "离线时排不了八字" in OfflineAgent().ask("帮我排个八字").text
