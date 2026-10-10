"""小瓜's motions: the imported 思考 / 拖拽 clips, drag, and motion that follows the conversation."""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402

qapp = QApplication.instance() or QApplication([])
ART = companion.ASSETS / "xiaogua"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))


@pytest.fixture
def pet():
    return companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")


def finish(pet, limit=200):
    """Run the current one-shot motions to their end, as the frame timer would."""
    for _ in range(limit):
        kind = pet.motions[pet.state][0]
        if kind != "once":
            return
        pet._next_frame()


# ------------------------------------------------------------ the imported clips

@pytest.mark.parametrize("motion, count", [("思考入", 7), ("思考", 6), ("思考出", 6),
                                           ("提起", 6), ("悬空", 6), ("落地", 7), ("起卦", 8), ("灵光一闪", 4)])
def test_clips_are_cut_out_and_sized_like_the_idle_melon(motion, count):
    frames = sorted((ART / motion).glob("*.png"))
    assert len(frames) == count
    first = Image.open(frames[0])
    alpha = np.asarray(first.getchannel("A"))
    assert alpha[:8, :8].max() == 0 and alpha[-8:, -8:].max() == 0        # paper keyed out
    if motion in ("思考入", "提起"):                                       # grounded, arms down
        solid = alpha >= 96
        rows = solid[180:330]
        width = max(np.nonzero(r)[0].max() - np.nonzero(r)[0].min() for r in rows if r.any())
        assert abs(width - 330) <= 12, width                                 # same melon size as 待机


def test_pingpong_loops_have_no_seam(pet):
    kind, frames, source = pet.motions["思考"]
    assert (kind, source, len(frames)) == ("loop", "思考", 6 + 4)          # 1..6 then 5..2
    assert pet.motions["悬空"][2] == "悬空" and len(pet.motions["悬空"][1]) == 6 + 4


def test_frame_timers_are_precise(pet):
    assert pet.timer.timerType() == Qt.PreciseTimer and pet.ambient.timerType() == Qt.PreciseTimer


# ------------------------------------------------------------ drag

def _mouse(pet, kind, point):
    local = QPointF(*point)
    QApplication.sendEvent(pet, QMouseEvent(kind, local, QPointF(pet.mapToGlobal(local.toPoint())),
                                            Qt.LeftButton, Qt.LeftButton if kind != QMouseEvent.Type.MouseButtonRelease
                                            else Qt.NoButton, Qt.NoModifier))


def test_drag_lifts_dangles_and_lands(pet):
    pet.show()
    _mouse(pet, QMouseEvent.Type.MouseButtonPress, (50, 50))
    _mouse(pet, QMouseEvent.Type.MouseMove, (80, 80))
    assert pet.state == "提起" and pet.queue == ["悬空"]
    finish(pet)
    assert pet.state == "悬空"
    _mouse(pet, QMouseEvent.Type.MouseMove, (120, 90))
    assert pet.state == "悬空"                                              # not restarted by more moves
    _mouse(pet, QMouseEvent.Type.MouseButtonRelease, (120, 90))
    assert pet.state == "落地"
    finish(pet)
    assert pet.state == "待机" and not pet.chat.isVisible()                 # a drag is not a click


def test_dragging_while_thinking_goes_back_to_thinking(pet):
    pet.busy = True
    pet._dragging = True
    pet._drag, pet._press = companion.QPoint(0, 0), companion.QPoint(0, 0)
    pet.play("悬空")
    _mouse(pet, QMouseEvent.Type.MouseButtonRelease, (40, 40))
    assert pet.state == "落地" and pet.queue == [companion.BUSY_LOOP]


# ------------------------------------------------------------ motion follows the conversation

def test_each_step_has_its_motion(pet):
    pet.busy = True
    pet.play("思考")
    pet.on_step("lookup_hexagrams")                 # no reading cast yet: the book, then the chin
    assert pet.state == "翻书"
    pet.on_step("validate_reading")
    assert pet.state == "思考"
    pet.on_step("cast_now")
    assert pet.state == "起卦"
    finish(pet)
    assert pet.state == "卦中"                       # cast: at the scroll with the brush from now on
    pet.on_step("lookup_hexagrams")
    assert pet.state == "卦中"
    pet.on_step("validate_reading")
    assert pet.state == "卦中"


def test_steps_are_ignored_when_idle(pet):
    pet.play("待机")
    pet.on_step("cast_now")
    assert pet.state == "待机"


def test_the_answer_arriving_holds_up_the_result_and_the_mood_follows(pet):
    pet.busy = True
    pet._answer_started = False
    pet.play("思考")
    pet._on_first_text("能成")
    assert pet.state == "灵光一闪"
    pet._on_first_text("，")
    assert pet.state == "灵光一闪"                                          # once per answer
    from meihua.companion.agent import Reply
    pet._on_reply(Reply("能成，冲吧。", True, [], mood="加油"))
    assert pet.state == "灵光一闪" and pet.queue == ["加油", "待机"]


def test_typing_makes_xiaogua_listen(pet):
    pet.play("待机")
    pet.chat.edit.setPlainText("我在")
    assert pet.state == "歪头" and pet.listen_timer.isActive()
    pet._stop_listening()
    assert pet.state == "待机"


def test_opening_the_chat_waves(pet):
    pet.play("待机")
    pet.open_chat()
    assert pet.state == "招手"


# ------------------------------------------------------------ breathing between keys

def test_idle_breathes_and_one_shots_do_not(pet):
    pet.play("待机")
    assert pet.ambient.isActive()
    image = pet.grab()                                                     # paints with the transform
    assert image.width() == pet.width()
    pet.play("起卦")
    assert not pet.ambient.isActive()


# ------------------------------------------------------------ nothing breaks a drag, nothing sticks

def _start_drag(pet):
    pet.show()
    _mouse(pet, QMouseEvent.Type.MouseButtonPress, (50, 50))
    _mouse(pet, QMouseEvent.Type.MouseMove, (80, 80))
    finish(pet)
    assert pet.state == "悬空"


def test_a_reply_arriving_mid_drag_does_not_interrupt_it(pet):
    from meihua.companion.agent import Reply
    _start_drag(pet)
    pet.busy = True
    pet._on_reply(Reply("能成。", False, []))                              # even an unchecked one (摇头)
    assert pet.state == "悬空"
    pet._settle()                                                            # the after-answer timer
    assert pet.state == "悬空"
    _mouse(pet, QMouseEvent.Type.MouseButtonRelease, (80, 80))
    assert pet.state == "落地"


def test_a_lost_release_still_lands(pet):
    _start_drag(pet)
    local = QPointF(90, 90)
    QApplication.sendEvent(pet, QMouseEvent(QMouseEvent.Type.MouseMove, local,
                                            QPointF(pet.mapToGlobal(local.toPoint())),
                                            Qt.NoButton, Qt.NoButton, Qt.NoModifier))
    assert not pet._dragging and pet.state == "落地"


def test_the_bubble_follows_a_drag(pet):
    pet.show()
    pet.bubble.say("嘿嘿", pet.frameGeometry(), 5)
    before = pet.bubble.pos()
    pet.move(pet.x() + 120, pet.y() + 40)
    assert pet.bubble.pos() != before and pet.bubble.x() - before.x() in range(100, 140)


def _melon_width(alpha):
    solid = alpha >= 96
    return max(np.ptp(np.nonzero(r)[0]) for r in solid[200:330] if r.any())


def test_the_drag_frames_are_the_idle_melon_lifted():
    """提起 / 悬空 / 落地 are made from 待机 itself: same size, same colours; the shadow stays down."""
    idle = np.asarray(Image.open(ART / "待机" / "01.png").convert("RGBA"))
    for name in ("提起", "悬空", "落地"):
        for frame in sorted((ART / name).glob("*.png")):
            alpha = np.asarray(Image.open(frame).getchannel("A"))
            assert abs(_melon_width(alpha) - _melon_width(idle[..., 3])) <= 16, frame
    hang = np.asarray(Image.open(ART / "悬空" / "01.png").convert("RGBA"))
    green = hang[..., 3] >= 200
    assert abs(np.median(hang[green][:, :3], axis=0) - np.median(idle[idle[..., 3] >= 200][:, :3], axis=0)).max() < 12
    land = [np.asarray(Image.open(ART / "落地" / f"{i:02d}.png").getchannel("A")) for i in (1, 2, 3, 4)]
    assert (land[0] == hang[..., 3]).all()                                 # no jump on release
    assert land[0][455:472].max() < 20 < land[3][455:472].max()            # the shadow comes back as it lands


def test_the_held_melon_swings_against_the_drag_and_settles_on_landing(pet):
    _start_drag(pet)
    for x in range(90, 300, 30):                                           # pulled quickly to the right
        _mouse(pet, QMouseEvent.Type.MouseMove, (x, 80))
        pet._last_drag = (pet._last_drag[0] - 0.02, pet._last_drag[1])     # as if 20 ms apart
    for _ in range(6):
        pet._tick()
    assert pet._swing < -3                                                 # the body lags to the left
    assert pet.grab().width() == pet.width()                               # paints turned
    _mouse(pet, QMouseEvent.Type.MouseButtonRelease, (300, 80))
    for _ in range(40):
        pet._tick()
    assert abs(pet._swing) < 1.0


def test_a_short_answer_does_not_leave_him_talking(pet):
    from meihua.companion.agent import Reply
    pet.busy, pet._answer_started = True, False
    pet.play("思考")
    pet._on_first_text("好")
    assert pet.state == "灵光一闪" and pet.queue == ["说话"]
    pet._on_reply(Reply("好。", True, []))
    assert pet.queue == ["待机"]


def test_text_that_was_not_the_answer_stops_the_talking(pet):
    pet.busy, pet._answer_started = True, False
    pet._on_first_text("我先")
    finish(pet)
    assert pet.state == "说话"
    pet._on_worker_discard()
    assert pet.state == companion.BUSY_LOOP and pet._answer_started is False


def test_a_held_tilt_with_something_after_it_moves_on(pet, monkeypatch):
    from PySide6.QtTest import QTest
    monkeypatch.setattr(companion, "HOLD_MS", 50)
    pet.play("歪头", "待机")
    finish(pet)
    for _ in range(10):
        pet._next_frame()
    QTest.qWait(120)
    assert pet.state == "待机"


def test_no_code_bounce_once_there_is_talking_art(pet):
    pet.busy, pet._answer_started = True, False
    pet._on_worker_delta("在")
    assert pet._talking_until == 0.0
