"""The chat window: dragged bigger or smaller by its edges, and opened at that size next time."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402
from meihua.companion import chat  # noqa: E402
from meihua.companion.config import Config  # noqa: E402

qapp = QApplication.instance() or QApplication([])


@pytest.fixture
def pet(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.move(900, 500)
    pet.show()
    pet.open_chat()
    yield pet
    pet.chat._size_timer.stop()                 # a later test must not get this one's size saved
    pet.chat.resized.disconnect()
    pet.chat.hide()
    pet.hide()


def panel_rect(panel) -> QRect:
    return QRect(panel.panel.mapToGlobal(QPoint(0, 0)), panel.panel.size())


def mouse(widget, kind, point: QPoint, buttons=Qt.NoButton, button=Qt.NoButton):
    local = QPointF(widget.mapFromGlobal(point))
    QApplication.sendEvent(widget, QMouseEvent(kind, local, QPointF(point), button, buttons, Qt.NoModifier))


def grip(panel, edges):
    return next(g for g in panel.grips if g.edges == edges)


def global_rect(widget) -> QRect:
    return QRect(widget.mapToGlobal(QPoint(0, 0)), widget.size())


def test_the_grips_lie_on_the_edges_and_corners(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    mid = rect.center()
    assert global_rect(grip(panel, Qt.RightEdge)).contains(QPoint(rect.right() + 3, mid.y()))   # in the shadow
    assert global_rect(grip(panel, Qt.RightEdge)).contains(QPoint(rect.right() - 2, mid.y()))   # just inside
    assert global_rect(grip(panel, Qt.LeftEdge)).contains(QPoint(rect.left() + 1, mid.y()))
    assert global_rect(grip(panel, Qt.BottomEdge)).contains(QPoint(mid.x(), rect.bottom()))
    assert global_rect(grip(panel, Qt.RightEdge | Qt.BottomEdge)).contains(QPoint(rect.right(), rect.bottom() - 8))
    assert not any(global_rect(g).contains(mid) for g in panel.grips)                     # the middle is the chat's
    assert not any(global_rect(g).contains(QPoint(rect.right() + 20, mid.y())) for g in panel.grips)
    assert chat.edge_cursor(Qt.LeftEdge) == Qt.SizeHorCursor
    assert chat.edge_cursor(Qt.LeftEdge | Qt.TopEdge) == Qt.SizeFDiagCursor
    assert chat.edge_cursor(Qt.Edge(0)) is None


def test_each_grip_shows_its_resize_arrow_and_follows_a_resize(pet):
    panel = pet.chat
    assert grip(panel, Qt.RightEdge).cursor().shape() == Qt.SizeHorCursor
    assert grip(panel, Qt.TopEdge).cursor().shape() == Qt.SizeVerCursor
    assert grip(panel, Qt.RightEdge | Qt.BottomEdge).cursor().shape() == Qt.SizeFDiagCursor
    panel.resize(560, 600)
    assert global_rect(grip(panel, Qt.RightEdge)).contains(QPoint(panel_rect(panel).right(), panel_rect(panel).center().y()))


def test_no_python_runs_for_every_event_of_the_app(pet):
    """The freeze: an application-wide event filter ran for each event while the worker held the GIL."""
    assert not hasattr(pet.chat, "_edge_event")


def drag(panel, edges, start: QPoint, end: QPoint):
    handle = grip(panel, edges)
    mouse(handle, QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    assert panel._resizing is not None                      # offscreen: no system resize, done by hand
    mouse(handle, QEvent.MouseMove, end, Qt.LeftButton)
    mouse(handle, QEvent.MouseButtonRelease, end, Qt.NoButton, Qt.LeftButton)


def test_dragging_the_left_edge_makes_it_wider_and_keeps_the_right_side_put(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    before = panel.geometry()
    start = QPoint(rect.left() + 1, rect.center().y())
    drag(panel, Qt.LeftEdge, start, start - QPoint(120, 0))
    after = panel.geometry()
    assert after.width() == before.width() + 120 and after.right() == before.right()
    assert after.height() == before.height()


def test_it_never_gets_smaller_than_its_minimum(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    start = QPoint(rect.right(), rect.bottom())
    drag(panel, Qt.RightEdge | Qt.BottomEdge, start, start - QPoint(1000, 1000))
    assert (panel.width(), panel.height()) == chat.CHAT_MIN


def test_the_size_is_remembered_and_used_next_time(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    start = QPoint(rect.center().x(), rect.bottom())
    drag(panel, Qt.BottomEdge, start, start - QPoint(0, 80))
    for _ in range(60):                                      # saved once the drag stops (400 ms)
        QTest.qWait(50)
        if Config.load().chat_size is not None:
            break
    size = [panel.width(), panel.height()]
    assert Config.load().chat_size == size and size[1] == chat.CHAT_SIZE[1] - 80
    panel.hide()
    pet.open_chat()
    assert [panel.width(), panel.height()] == size


def test_a_remembered_size_bigger_than_the_screen_is_cut_to_fit(pet):
    from meihua.companion.chat import screen_rect_for
    area = screen_rect_for(pet.frameGeometry().center())
    pet.chat.preferred_size = (area.width() + 500, area.height() + 500)
    pet.chat.hide()
    pet.open_chat()
    assert pet.chat.width() <= area.width() and pet.chat.height() <= area.height()


def test_clicks_inside_still_reach_the_chat(pet):
    """Away from the edges nothing changes: a press in the chat starts no resize."""
    panel = pet.chat
    rect = panel_rect(panel)
    mouse(panel.feed, QEvent.MouseButtonPress, rect.center(), Qt.LeftButton, Qt.LeftButton)
    assert panel._resizing is None and QApplication.widgetAt(rect.center()) not in panel.grips
    mouse(panel.feed, QEvent.MouseButtonRelease, rect.center(), Qt.NoButton, Qt.LeftButton)


def test_the_bubbles_wrap_to_the_windows_width(pet):
    """Narrowed, a long answer used to stay 268 wide and run off the right side."""
    panel = pet.chat
    long = panel.add_notice("还没设置 豆包（火山方舟） 的 API key，小瓜先用离线模式陪你：能看今天的黄历、给你起个盘面，但细讲要接上模型。")
    short = panel.add_notice("好的。")
    panel.resize(*chat.CHAT_MIN)
    QApplication.processEvents()
    inside = QRect(panel.panel.mapToGlobal(QPoint(0, 0)), panel.panel.size())
    bubble = QRect(long.mapToGlobal(QPoint(0, 0)), long.size())
    assert inside.contains(bubble) and long.body.width() == chat.CHAT_MIN[0] - chat.BUBBLE_SIDES
    panel.resize(600, 600)
    assert long.body.width() == 600 - chat.BUBBLE_SIDES and short.body.width() < 100     # short ones stay short
    later = panel.add_notice("新消息" * 40)
    assert later.body.width() == 600 - chat.BUBBLE_SIDES


def test_just_opening_the_chat_saves_no_size(pet):
    """Only dragging an edge is the user's choice; opening (and Qt's own sizing) is not."""
    pet.chat.hide()
    pet.open_chat()
    QTest.qWait(600)
    assert Config.load().chat_size is None and not pet.chat._size_timer.isActive()


def test_a_frozen_window_is_logged_with_where_it_was_stuck(caplog):
    """Windows only shows blank 「未响应」 frames; the log says which line held the window."""
    import logging
    import time
    watch = companion.watch_for_stalls(stall_s=0.2, every_s=0.05)
    with caplog.at_level(logging.WARNING, logger="xiaogua"):
        time.sleep(0.6)                                       # the GUI thread blocked
        QTest.qWait(200)
    watch.stop()
    watch.halt.set()
    stuck = [r.getMessage() for r in caplog.records if "界面卡住" in r.getMessage()]
    assert stuck and "test_a_frozen_window_is_logged" in stuck[0]


def test_the_grips_paint_nothing(pet):
    """A fill under the strips showed as a black frame (opaque) or let clicks through (almost clear)."""
    for handle in pet.chat.grips:
        assert handle.styleSheet() == "" and not handle.autoFillBackground()
        assert not handle.testAttribute(Qt.WA_StyledBackground)
