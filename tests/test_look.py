"""Look and interaction (learnt from dsh-pet-indesktop): the settings window's cards and pages,
小瓜's menu, 锁定位置, 气泡字号, 随口说两句."""

from __future__ import annotations

import os
import random
from datetime import datetime

import pytest

from meihua.companion import life


@pytest.fixture
def qt(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))


@pytest.fixture
def pet(qt, monkeypatch):
    from meihua.companion import app as companion
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.show()
    return pet


@pytest.fixture
def window(qt):
    from meihua.companion import config
    from meihua.companion.settings_window import SettingsWindow
    return SettingsWindow(config.Config.load())


# ------------------------------------------------------------ the settings window

def test_the_pages_have_icons_and_the_pet_page_is_split_in_three(window):
    from meihua.companion.settings_window import PAGES
    names = [window.nav.item(i).text().strip() for i in range(window.nav.count())]
    assert names == list(PAGES) and {"小瓜", "外观", "互动"} <= set(names)
    assert all(not window.nav.item(i).icon().isNull() for i in range(window.nav.count()))
    assert window.pages.count() == len(PAGES)


def test_every_page_scrolls_so_nothing_is_cut_off(window):
    from PySide6.QtWidgets import QScrollArea
    assert all(isinstance(window.pages.widget(i), QScrollArea) for i in range(window.pages.count()))


def test_choices_side_by_side_save_like_the_old_drop_downs(window):
    from meihua.companion import config
    window.style_box.setCurrentText("直白")
    window.proactive_box.setCurrentText("少")
    window.bubble_font_box.setCurrentText("大")
    window.chatter_often_box.setCurrentText("常常")
    saved = config.Config.load()
    assert (saved.voice_style, saved.proactive, saved.bubble_font, saved.chatter_often) == ("直白", "少", "大", "常常")
    assert window.style_box.currentText() == "直白"


def test_the_new_switches_save(window):
    from meihua.companion import config
    window.lock_box.setChecked(True)
    window.chatter_box.setChecked(False)
    window.on_top_box.setChecked(False)
    saved = config.Config.load()
    assert saved.lock_position and not saved.chatter and not saved.always_on_top


def test_own_chatter_lines_are_saved_a_moment_after_typing(window):
    from meihua.companion import config
    window.chatter_edit.setPlainText("记得站起来走走\n\n  今天也辛苦啦  ")
    assert window._chatter_timer.isActive() and config.Config.load().chatter_lines == []    # not on every key
    window._chatter_timer.timeout.emit()
    assert config.Config.load().chatter_lines == ["记得站起来走走", "今天也辛苦啦"]


def test_the_window_follows_switches_flipped_on_the_pet(window):
    window.config.lock_position, window.config.always_on_top = True, False
    window.sync_from(window.config)
    assert window.lock_box.isChecked() and not window.on_top_box.isChecked()


# ------------------------------------------------------------ the menu

def test_the_menu_is_rounded_cream_with_icons():
    from meihua.companion import look
    menu = look.menu()
    item = look.add_action(menu, "问小瓜", None, "问小瓜", shortcut="Ctrl+Alt+X")
    switch = look.add_action(menu, "锁定位置", None, checked=True)
    assert "border-radius: 12px" in menu.styleSheet() and not item.icon().isNull()
    assert item.text() == "问小瓜\tCtrl+Alt+X" and switch.isCheckable() and switch.isChecked()


@pytest.mark.parametrize("name", list(__import__("meihua.companion.look", fromlist=["_ICONS"])._ICONS))
def test_every_icon_draws(qt, name):
    from meihua.companion import look
    assert not look._pixmap(name, look.INK, 18).isNull()


def test_the_pet_menu_in_groups_with_the_new_switches(pet):
    menu = pet.context_menu()
    entries = [a.text().split("\t")[0] if not a.isSeparator() else "—" for a in menu.actions()]
    assert entries == ["问小瓜", "打开对话", "今天怎么样", "—", "大小", "缩成小球", "锁定位置", "总在最前面", "—",
                       "新对话", "删除这个对话…", "—", "退出每日一瓜"]       # 设置… only when the app gives it
    switches = {a.text(): a.isChecked() for a in menu.actions() if a.isCheckable()}
    assert switches == {"锁定位置": False, "总在最前面": True}


def test_a_switch_on_the_pet_is_saved_and_said_to_the_rest(pet):
    from meihua.companion.config import Config
    heard = []
    pet.settings_changed.connect(lambda: heard.append(True))
    pet.set_setting("always_on_top", False)
    assert Config.load().always_on_top is False and heard
    from PySide6.QtCore import Qt
    assert not pet.windowFlags() & Qt.WindowStaysOnTopHint


def test_today_from_the_menu_says_the_morning_line_again(pet):
    pet.config.last_greet = datetime.now().date().isoformat()          # said this morning already
    pet.show_today()
    assert pet.bubble.isVisible() and pet.bubble.toPlainText().startswith(("今天", "别忘了", "明天"))


# ------------------------------------------------------------ 锁定位置

def _drag(pet, distance: int):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    start = QPointF(100, 100)
    for kind, point, buttons in ((QMouseEvent.Type.MouseButtonPress, start, Qt.LeftButton),
                                 (QMouseEvent.Type.MouseMove, start + QPointF(distance, 0), Qt.LeftButton),
                                 (QMouseEvent.Type.MouseButtonRelease, start + QPointF(distance, 0), Qt.NoButton)):
        QApplication.sendEvent(pet, QMouseEvent(kind, point, QPointF(pet.mapToGlobal(point.toPoint())),
                                                Qt.LeftButton, buttons, Qt.NoModifier))


def test_a_locked_pet_stays_put_and_says_why(pet):
    pet.config.lock_position = True
    where = pet.pos()
    _drag(pet, 80)
    assert pet.pos() == where and not pet._dragging
    assert "锁住" in pet.bubble.toPlainText() and not pet.bubble.asking         # a drag is not a click
    pet.config.lock_position = False
    _drag(pet, 80)
    assert pet.pos() != where


# ------------------------------------------------------------ 气泡字号

def test_the_bubble_font_size_grows_the_words_and_the_width(pet):
    from meihua.companion import app as companion
    pet.config.bubble_font = "大"
    pet.apply_config(pet.config)
    pet.bubble.say("今天宜理发。" * 20, pet.frameGeometry())
    assert "font-size: 16px" in pet.bubble.label.styleSheet()
    assert pet.bubble.label.maximumWidth() == round(companion.NOTE_WIDTH * 16 / 13)
    pet.config.bubble_font = "小"
    pet.apply_config(pet.config)
    pet.bubble.say("好。", pet.frameGeometry())
    assert "font-size: 12px" in pet.bubble.label.styleSheet() and pet.bubble.label.maximumWidth() < companion.NOTE_WIDTH


# ------------------------------------------------------------ 随口说两句

def test_chatter_lines_come_from_today_and_small_kindnesses():
    rng = random.Random(3)
    noon = datetime(2026, 10, 26, 12, 0)
    said = {life.chatter_line(["理发"], ["申时（下午三点到五点）"], [(5, "万圣夜")], noon, rng=rng) for _ in range(200)}
    assert "今天宜理发，想做的话就趁今天。" in said and "还有 5 天就是万圣夜啦。" in said
    assert "到饭点啦，先去吃饭吧。" in said and any("申时" in s for s in said)
    assert "到饭点啦，先去吃饭吧。" not in {life.chatter_line([], [], [], datetime(2026, 10, 26, 15, 0), rng=rng)
                                           for _ in range(100)}
    assert life.chatter_line(["理发"], [], [(1, "冬至")], noon, own=["我写的"], rng=rng) == "我写的"
    assert life.chatter_line([], [], [(1, "冬至")], noon, rng=random.Random(0)) in {*life.CARE_LINES, "明天就是冬至啦。"}


def test_chatter_waits_its_turn():
    rng = random.Random(1)
    low, high = life.CHATTER_EVERY["常常"]
    assert all(low <= life.chatter_delay("常常", rng) <= high for _ in range(20))
    assert life.allows("正常", "chatter") and not life.allows("少", "chatter") and not life.allows("关", "chatter")


def test_the_pet_chatters_only_when_idle_and_allowed(pet, monkeypatch):
    monkeypatch.setattr(life, "is_night", lambda now=None: False)
    pet.config.chatter_lines = ["记得站起来走走"]
    pet.bubble.hide()
    pet.play("待机")
    assert pet._chatter() == "记得站起来走走" and pet.bubble.toPlainText() == "记得站起来走走"
    pet.bubble.hide()
    pet.play("待机")
    for setting, value in (("proactive", "少"), ("chatter", False), ("mini", True)):
        old = getattr(pet.config, setting)
        setattr(pet.config, setting, value)
        assert pet._chatter() is None and pet.chatter_timer.isActive()
        setattr(pet.config, setting, old)
    pet.busy = True
    assert pet._chatter() is None
    pet.busy = False
    monkeypatch.setattr(life, "is_night", lambda now=None: True)
    assert pet._chatter() is None and pet.chatter_timer.interval() == life.CHATTER_RETRY_MS


# ------------------------------------------------------------ first-time tips in the bubble

def test_the_box_tip_shows_until_the_first_question_then_never(pet):
    from meihua.companion.config import Config
    pet.bubble.ask(pet.frameGeometry())
    assert pet.bubble.footer.isVisibleTo(pet.bubble) and "Enter 发送" in pet.bubble.footer.text()
    pet.bubble.input.setText("今天宜什么")
    pet.bubble.send()
    pet.bubble.ask(pet.frameGeometry())
    assert not pet.bubble.footer.isVisibleTo(pet.bubble) and Config.load().learnt == ["ask"]


def test_the_answer_tip_goes_once_a_bubble_was_clicked(pet):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    pet.bubble.answer("宜理发。", pet.frameGeometry())
    assert pet.bubble.footer.text() == "点气泡看完整对话"
    QApplication.sendEvent(pet.bubble, QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(10, 10),
                                                   QPointF(10, 10), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    pet.bubble.answer("宜理发。", pet.frameGeometry())
    assert not pet.bubble.footer.isVisibleTo(pet.bubble) and "answer" in pet.config.learnt


def test_tips_learnt_before_stay_away_after_a_restart(pet):
    pet.config.learnt = ["ask", "answer"]
    pet.apply_config(pet.config)
    pet.bubble.ask(pet.frameGeometry())
    assert not pet.bubble.footer.isVisibleTo(pet.bubble)
