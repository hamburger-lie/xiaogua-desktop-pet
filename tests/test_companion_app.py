"""Window smoke tests, run headless (no hotkey hook, no API)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402

qapp = QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def temp_home(tmp_path, monkeypatch):
    """Config, logs and the stored-key lookup stay inside a temp folder."""
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from meihua.companion import config
    monkeypatch.setattr(config, "CREDENTIAL_PREFIX", "meihua-xiaogua-pytest-" + tmp_path.name)
    return tmp_path / "home"


@pytest.fixture
def gif_only_assets(tmp_path, monkeypatch):
    """The original three GIFs and the avatar, without any PNG motion folders."""
    import shutil
    assets = tmp_path / "assets"
    shutil.copytree(companion.ASSETS, assets,
                    ignore=lambda folder, names: [n for n in names if folder.endswith("xiaogua")
                                                  and not n.endswith(".gif")])
    monkeypatch.setattr(companion, "ASSETS", assets)
    return assets


def test_cut_out_clears_the_paper_but_keeps_the_figure():
    gif = Image.open(companion.ASSETS / "xiaogua" / "小瓜_摸鱼.gif")
    frame = companion.cut_out(gif.copy())
    alpha = frame.getchannel("A")
    assert alpha.getpixel((2, 2)) < 30                       # corner paper removed
    assert alpha.getpixel((181, 181)) == 255                 # body kept
    assert alpha.getpixel((90, 290)) > 200                   # cream cushion kept, not keyed out


def test_missing_motions_fall_back_or_are_skipped(gif_only_assets):
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    used = {state: source for state, (_, _, source) in pet.motions.items()}
    assert used["待机"] == "小瓜_摸鱼.gif" and used["翻书"] == "小瓜_思考.gif" and used["头像"] == "@avatar"
    assert used["招手"] is None                     # no artwork yet
    assert pet.state == "待机"                        # 招手 was skipped straight to 待机


def test_a_reply_lands_in_the_chat_and_the_pet_settles(gif_only_assets):
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    reply = pet.agent.ask("今天面试能成吗")
    pet.busy = True
    pet.chat.start_thinking()
    pet._on_reply(reply)
    assert pet.busy is False and pet.state == "待机"  # 灵光一闪 has no art here -> straight to 待机
    kinds = [kind for kind, _ in pet.chat.transcript()]
    assert kinds == ["xiaogua"] and "本卦" in pet.chat.transcript()[0][1]   # typing indicator gone
    assert not pet.chat.busy and pet.chat.send_button.isEnabled()


def test_new_artwork_is_picked_up_from_a_folder(gif_only_assets):
    wave = gif_only_assets / "xiaogua" / "招手"
    wave.mkdir()
    for i in range(3):
        Image.new("RGBA", (512, 512), (0, 0, 0, 0)).save(wave / f"{i + 1:02d}.png")
    (wave / "motion.json").write_text('{"frame_ms": 70}', encoding="utf-8")
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    kind, frames, source = pet.motions["招手"]
    assert (kind, len(frames), source) == ("once", 3, "招手")
    assert {duration for _, duration in frames} == {70}  # per-motion speed from motion.json
    assert pet.state == "招手"                        # starts by waving now
    for _ in range(3):
        pet._next_frame()
    assert pet.state == "待机"                        # one-shot hands over when done


def test_errors_are_shown_in_the_chat_not_raised():
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet._on_reply(RuntimeError("network down"))
    kind, text = pet.chat.transcript()[-1]
    assert pet.state in ("摇头", "待机") and kind == "error" and "network down" in text


def test_shipped_artwork_covers_the_p0_p1_motions():
    """The sliced sheets (companion/sprites.py) are what the pet actually plays."""
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    used = {state: source for state, (_, _, source) in pet.motions.items()}
    for state in ("待机", "招手", "翻书", "灵光一闪", "摇头", "歪头", "睡着", "加油"):
        assert used[state] == state, state                    # a PNG folder, not a GIF stand-in
    for state in ("待机", "睡着", "翻书"):
        _, frames, _ = pet.motions[state]
        assert len(frames) >= 6                               # no more two-frame flip-flop


def test_sliced_frames_share_the_foot_anchor():
    from meihua.companion import sprites
    for motion in ("招手", "翻书", "睡着"):
        feet = set()
        for frame in sorted((companion.ASSETS / "xiaogua" / motion).glob("*.png")):
            alpha = Image.open(frame).getchannel("A").point(lambda a: 255 if a >= sprites.ALPHA_SOLID else 0)
            feet.add(alpha.getbbox()[3])
        assert max(feet) - min(feet) <= 2, (motion, feet)     # the figure does not hop


def test_frame_is_painted_to_the_window_size_not_a_fixed_pixmap_size():
    """Regression: on a 125%/100% two-monitor setup the pet was cropped."""
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    assert not pet.findChildren(companion.QLabel)          # no fixed-size label to crop into
    assert pet.pixmap.width() == companion.ART_PX
    for size in (120, 150, 188):                           # 80%, 100%, 125% of logical size
        pet.resize(size, size)
        image = pet.grab().toImage()
        assert image.width() == size and image.height() == size


def _chat():
    from meihua.companion.chat import ChatPanel
    panel = ChatPanel(None, "Ctrl+Alt+X")
    sent = []
    panel.submitted.connect(lambda *args: sent.append(args))
    return panel, sent


def _press_enter(panel, shift=False):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    modifiers = Qt.ShiftModifier if shift else Qt.NoModifier
    QApplication.sendEvent(panel.edit, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, modifiers))


def test_shift_enter_is_a_new_line_not_a_send():
    panel, sent = _chat()
    panel.edit.setPlainText("第一行")
    _press_enter(panel, shift=True)
    assert sent == []


def test_typed_text_is_sent_and_quick_chips_send_at_once():
    panel, sent = _chat()
    panel.edit.setPlainText("  今天适合理发吗  ")
    _press_enter(panel)
    assert sent == [("今天适合理发吗",)] and panel.edit.toPlainText() == ""
    chip = next(b for b in panel.findChildren(companion.QWidget) if getattr(b, "text", None)
                and callable(b.text) and b.text() == "帮我挑个好日子")
    chip.click()
    assert sent[-1] == ("帮我挑个好日子",)


def test_an_empty_enter_sends_nothing():
    panel, sent = _chat()
    _press_enter(panel)
    assert sent == []


def test_chat_shows_progress_and_blocks_a_second_question_while_busy():
    panel, sent = _chat()
    panel.add_mine("今天面试能成吗")
    panel.start_thinking()
    panel.step("almanac_day")
    assert "翻黄历" in panel.status.text() and "翻黄历" in panel.typing.body.text()
    panel.edit.setPlainText("再问一个")
    _press_enter(panel)
    assert sent == []                                        # one question at a time
    panel.add_reply("能成。", "（只当参考）")
    assert [k for k, _ in panel.transcript()] == ["mine", "xiaogua"]
    assert "只当参考" in panel.transcript()[-1][1] and panel.status.isHidden()     # status only while working


def test_clearing_brings_back_the_welcome():
    panel, _ = _chat()
    panel.add_mine("你好")
    panel.add_reply("在的")
    panel.clear()
    QApplication.processEvents()
    assert panel.transcript() == [] and not panel.welcome.isHidden()


def test_chat_opens_beside_the_pet_on_the_pets_screen():
    panel, _ = _chat()
    screen = QApplication.primaryScreen().availableGeometry()
    from PySide6.QtCore import QRect
    pet = QRect(screen.right() - 200, screen.bottom() - 200, 180, 180)     # bottom-right corner
    panel.open_beside(pet)
    assert screen.contains(panel.geometry())
    assert panel.geometry().right() <= pet.left() + 20                     # to the left of 小瓜


def test_clicking_the_pet_toggles_the_chat():
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.show()
    point = QPointF(pet.width() / 2, pet.height() / 2)
    global_point = QPointF(pet.mapToGlobal(point.toPoint()))
    for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(pet, QMouseEvent(kind, point, global_point, Qt.LeftButton,
                                                Qt.LeftButton, Qt.NoModifier))
    assert pet.chat.isVisible()


def test_submitting_starts_the_reading(monkeypatch):
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    started = []
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: started.append(args)})())
    pet._submit("今天宜什么")
    assert pet.busy and [args[:1] for args in started] == [("今天宜什么",)]
    assert pet.state == "思考入" and pet.queue == ["思考"]      # raises a hand to the chin, then thinks


def test_pet_is_bigger_by_default_and_size_is_remembered():
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    assert pet.width() == companion.PET_SIZES["中"] == 220
    pet.move(500, 300)
    feet = pet.geometry().center().x(), pet.geometry().bottom()
    pet.set_size(companion.PET_SIZES["大"])
    assert pet.width() == pet.height() == 300
    assert abs(pet.geometry().center().x() - feet[0]) <= 1 and pet.geometry().bottom() == feet[1]
    pet.set_size(9999)
    assert pet.width() == companion.PET_MAX                # clamped
    again = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    assert again.width() == companion.PET_MAX              # restored from settings


def test_the_scroll_loop_is_the_end_of_the_cast(monkeypatch):
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    kind, frames, source = pet.motions["卦中"]
    cast = pet.motions["起卦"][1]
    assert kind == "loop" and source == "起卦#6-8@170"
    assert [f[0].cacheKey() for f in frames] == [cast[i][0].cacheKey() for i in (5, 6, 7, 6)]   # 6 7 8 7 | 6 …
    assert {f[1] for f in frames} == {170}


def test_after_a_cast_xiaogua_stays_at_the_scroll_until_the_answer(monkeypatch):
    """It cast for 0.7 s, then went back to 托腮 for 核对证据 and the writing: the user saw no 起卦."""
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet._submit("我今年仕途怎么样")
    assert pet.queue == ["思考"]                                    # nothing cast yet: chin in hand
    pet.bridge.step.emit(pet._turn, "daily_reading")
    assert pet.state == "起卦" and pet.queue == ["卦中"]             # opens the scroll, then keeps writing
    pet.play("卦中")
    for tool in ("lookup_hexagrams", "validate_reading", "almanac_day"):
        pet.bridge.step.emit(pet._turn, tool)
        assert pet.state == "卦中"                                   # not off to the book or the chin
    pet.bridge.delta.emit(pet._turn, "要先")
    pet.bridge.discard.emit(pet._turn)                              # that text was not the answer
    assert pet.state == "卦中"
    from meihua.companion.agent import Reply
    pet.bridge.replied.emit(pet._turn, Reply("今年稳中有升。", True))
    pet._submit("今天几点出门好")                                     # the next question starts afresh
    pet.bridge.step.emit(pet._turn, "almanac_day")
    assert pet.state == "翻书"
