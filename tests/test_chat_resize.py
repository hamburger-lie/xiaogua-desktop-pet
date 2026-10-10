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
    return pet


def panel_rect(panel) -> QRect:
    return QRect(panel.panel.mapToGlobal(QPoint(0, 0)), panel.panel.size())


def mouse(widget, kind, point: QPoint, buttons=Qt.NoButton, button=Qt.NoButton):
    local = QPointF(widget.mapFromGlobal(point))
    QApplication.sendEvent(widget, QMouseEvent(kind, local, QPointF(point), button, buttons, Qt.NoModifier))


def test_the_edges_and_corners_are_found(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    mid_y = rect.center().y()
    assert panel._edges_at(QPoint(rect.right() + 3, mid_y)) == Qt.RightEdge           # in the shadow
    assert panel._edges_at(QPoint(rect.right() - 2, mid_y)) == Qt.RightEdge           # just inside
    assert panel._edges_at(QPoint(rect.left() + 1, mid_y)) == Qt.LeftEdge
    assert panel._edges_at(QPoint(rect.center().x(), rect.bottom())) == Qt.BottomEdge
    assert panel._edges_at(QPoint(rect.right(), rect.bottom() - 10)) == Qt.RightEdge | Qt.BottomEdge
    assert panel._edges_at(rect.center()) == chat._NO_EDGE
    assert panel._edges_at(QPoint(rect.right() + 20, mid_y)) == chat._NO_EDGE         # beyond the shadow
    assert chat.edge_cursor(Qt.LeftEdge) == Qt.SizeHorCursor
    assert chat.edge_cursor(Qt.LeftEdge | Qt.TopEdge) == Qt.SizeFDiagCursor
    assert chat.edge_cursor(chat._NO_EDGE) is None


def test_hovering_an_edge_shows_the_resize_arrow(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    mouse(panel.feed, QEvent.MouseMove, QPoint(rect.right() - 1, rect.center().y()))
    assert panel.cursor().shape() == Qt.SizeHorCursor
    mouse(panel.feed, QEvent.MouseMove, rect.center())
    assert panel.cursor().shape() == Qt.ArrowCursor


def test_dragging_the_left_edge_makes_it_wider_and_keeps_the_right_side_put(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    before = panel.geometry()
    start = QPoint(rect.left() + 1, rect.center().y())
    mouse(panel.feed, QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    assert panel._resizing is not None                      # offscreen: no system resize, done by hand
    mouse(panel.feed, QEvent.MouseMove, start - QPoint(120, 0), Qt.LeftButton)
    mouse(panel.feed, QEvent.MouseButtonRelease, start - QPoint(120, 0), Qt.NoButton, Qt.LeftButton)
    after = panel.geometry()
    assert after.width() == before.width() + 120 and after.right() == before.right()
    assert after.height() == before.height()


def test_it_never_gets_smaller_than_its_minimum(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    start = QPoint(rect.right(), rect.bottom())
    mouse(panel.feed, QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    mouse(panel.feed, QEvent.MouseMove, start - QPoint(1000, 1000), Qt.LeftButton)
    mouse(panel.feed, QEvent.MouseButtonRelease, start, Qt.NoButton, Qt.LeftButton)
    assert (panel.width(), panel.height()) == chat.CHAT_MIN


def test_the_size_is_remembered_and_used_next_time(pet):
    panel = pet.chat
    rect = panel_rect(panel)
    start = QPoint(rect.center().x(), rect.bottom())
    mouse(panel.feed, QEvent.MouseButtonPress, start, Qt.LeftButton, Qt.LeftButton)
    mouse(panel.feed, QEvent.MouseMove, start - QPoint(0, 80), Qt.LeftButton)
    mouse(panel.feed, QEvent.MouseButtonRelease, start, Qt.NoButton, Qt.LeftButton)
    QTest.qWait(500)
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
    """Away from the edges nothing changes: the header still drags the window, buttons still work."""
    panel = pet.chat
    rect = panel_rect(panel)
    mouse(panel.feed, QEvent.MouseButtonPress, rect.center(), Qt.LeftButton, Qt.LeftButton)
    assert panel._resizing is None
    mouse(panel.feed, QEvent.MouseButtonRelease, rect.center(), Qt.NoButton, Qt.LeftButton)
