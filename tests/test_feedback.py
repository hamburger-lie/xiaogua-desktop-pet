"""「反馈这条回答」: what goes out is only what the user sees and ticks, and 小瓜 sends nothing itself."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402
from meihua.companion import feedback  # noqa: E402
from meihua.companion.agent import Reply  # noqa: E402

qapp = QApplication.instance() or QApplication([])

EXCHANGE = feedback.Exchange(question="明天面试能成吗", answer="能成，七八成把握。", asked_at="2026-10-10T09:30:00",
                             model="豆包（火山方舟） · doubao-seed-2-1-lite-260915",
                             checks=["说晚了结论，退回重说"], zodiac="虎")


@pytest.fixture
def pet(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(companion.threading, "Thread",
                        lambda target, args, daemon: type("T", (), {"start": lambda self: None})())
    pet = companion.Pet(companion.OfflineAgent(), "Ctrl+Alt+X")
    pet.show()
    return pet


@pytest.fixture
def opened(monkeypatch):
    urls = []
    monkeypatch.setattr(feedback.QDesktopServices, "openUrl", lambda url: urls.append(url.toString()))
    return urls


def answered(pet, question="明天面试能成吗", answer="能成，七八成把握。"):
    pet.open_chat()
    pet.chat.send(question)
    pet.bridge.replied.emit(pet._turn, Reply(answer, True, checks=["说晚了结论，退回重说"]))
    return next(m for m in pet.chat.messages() if m.kind == "xiaogua")


def test_the_text_holds_only_what_was_ticked():
    full = feedback.feedback_text(EXCHANGE, "说得不对", "应该是不宜", zodiac=True)
    for part in ("问题类型：说得不对", "补充说明：应该是不宜", "明天面试能成吗", "能成，七八成把握。",
                 "doubao-seed", "2026-10-10 09:30", "说晚了结论", "属相：虎", "每日一瓜 1."):
        assert part in full
    bare = feedback.feedback_text(EXCHANGE, "其他", question=False, answer=False)
    assert "面试" not in bare and "七八成" not in bare and "虎" not in bare and "补充" not in bare
    assert "属相" not in feedback.feedback_text(EXCHANGE, "其他")             # off unless ticked


def test_answers_keep_which_model_gave_them_but_never_the_address(pet):
    message = answered(pet)
    stored = pet.session.message(message.msg_id)
    assert stored["model"] == "离线模式" and stored["checks"] == ["说晚了结论，退回重说"]
    pet.agent = type("A", (), {"model": "doubao-seed-2-1-lite-260915"})()
    pet.config.base_urls[pet.config.provider] = "https://my-private-server.example/v1"
    assert pet._model_label().endswith("doubao-seed-2-1-lite-260915") and "example" not in pet._model_label()


def test_every_answer_has_a_feedback_button_but_notices_do_not(pet):
    message = answered(pet)
    assert message.feedback_button is not None and message.feedback_button.text() == "反馈"
    notice = pet.chat.add_notice("该喝水啦", "n1")                        # a reminder, not an answer
    assert notice.feedback_button is None
    mine = next(m for m in pet.chat.messages() if m.kind == "mine")
    assert mine.feedback_button is None


def test_a_streamed_answer_gets_its_button_when_it_is_done(pet):
    pet.open_chat()
    pet.chat.send("今天适合理发吗")
    pet.bridge.delta.emit(pet._turn, "适合。")
    pet.chat._flush_draft()
    assert pet.chat.draft.feedback_button is None                          # still arriving
    pet.bridge.replied.emit(pet._turn, Reply("适合。", True))
    message = next(m for m in pet.chat.messages() if m.kind == "xiaogua")
    assert message.feedback_button is not None


def test_answers_restored_after_a_restart_keep_the_button(pet):
    answered(pet)
    pet._show_conversation()
    assert any(m.feedback_button is not None for m in pet.chat.messages() if m.kind == "xiaogua")


def test_the_button_and_the_right_click_menu_open_the_dialog(pet):
    message = answered(pet)
    message.feedback_button.click()
    dialog = pet._feedback_dialog
    assert dialog.isVisible() and "明天面试能成吗" in dialog.text() and "离线模式" in dialog.text()
    dialog.reject()
    pet.chat._message_menu(message, QPoint(0, 0))
    labels = [action.text() for action in pet.chat._menu.actions()]
    pet.chat._menu.close()
    assert "反馈这条回答…" in labels


def test_unticking_takes_things_out_of_the_preview(pet):
    pet.session.zodiac = "虎"
    message = answered(pet)
    pet._feedback(message.msg_id)
    dialog = pet._feedback_dialog
    assert "属相" not in dialog.text()
    dialog.with_zodiac.setChecked(True)
    assert "属相：虎" in dialog.text()
    dialog.with_question.setChecked(False)
    assert "明天面试能成吗" not in dialog.text()
    dialog.problems.button(2).click()
    assert "问题类型：太长或太绕" in dialog.text()
    dialog.reject()


def test_sending_copies_the_preview_and_opens_a_page_with_nothing_personal_in_its_address(pet, opened):
    message = answered(pet)
    pet._feedback(message.msg_id)
    dialog = pet._feedback_dialog
    dialog.preview.setPlainText(dialog.text().replace("面试", "××"))             # the user edited it
    dialog.open_button.click()
    assert QApplication.clipboard().text() == dialog.text() and "××" in QApplication.clipboard().text()
    assert opened == [feedback.FEEDBACK_URL]
    assert "面试" not in opened[0] and "%" not in opened[0]
    assert "粘贴" in pet.chat.status.text()


def test_only_copy_opens_nothing(pet, opened):
    message = answered(pet)
    pet._feedback(message.msg_id)
    only_copy = next(b for b in pet._feedback_dialog.findChildren(feedback.QPushButton) if b.text() == "只复制")
    only_copy.click()
    assert opened == [] and "明天面试能成吗" in QApplication.clipboard().text()


def test_the_feedback_page_exists_in_the_repository():
    from pathlib import Path
    form = Path(__file__).resolve().parents[1] / ".github" / "ISSUE_TEMPLATE" / "answer-feedback.yml"
    assert form.exists() and form.name in feedback.FEEDBACK_URL
    text = form.read_text(encoding="utf-8")
    assert "公开" in text and "type: textarea" in text


def test_the_privacy_terms_mention_the_one_thing_the_user_can_send():
    import meihua
    text = (meihua.ROOT / "PRIVACY.txt").read_text(encoding="utf-8-sig")
    assert "反馈" in text and "自己提交" in text and "公开" in text
