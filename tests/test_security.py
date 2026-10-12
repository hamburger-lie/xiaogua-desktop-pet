"""Security: links in model-written text, the single-instance pipe, keys sent unencrypted."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402
from meihua.companion import chat  # noqa: E402
from meihua.companion.settings_window import plain_http_elsewhere  # noqa: E402

qapp = QApplication.instance() or QApplication([])


@pytest.fixture
def opened(monkeypatch):
    from PySide6.QtGui import QDesktopServices
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url.toString()) or True)
    return urls


@pytest.mark.parametrize("url", ["https://github.com/hamburger-lie", "http://example.com/page"])
def test_web_links_in_messages_open_in_the_browser(opened, url):
    assert chat.open_web_link(url) and opened == [url]


@pytest.mark.parametrize("url", [
    "file:///C:/Windows/System32/cmd.exe", r"\attacker\share\evil.exe", "C:/Users/me/evil.exe",
    "javascript:alert(1)", "mailto:a@b.c", "data:text/html,hi", "ms-settings:", "https://", "  file:x.bat"])
def test_other_links_in_messages_open_nothing(opened, url):
    """A model answer is not trusted: a link to a program or a share must not run it."""
    assert not chat.open_web_link(url) and opened == []


def test_messages_do_not_open_links_by_themselves():
    message = chat.Message("xiaogua", "[点这里](file:///C:/Windows/System32/cmd.exe)")
    assert not message.body.openExternalLinks()


@pytest.mark.parametrize("url, warn", [
    ("http://203.0.113.5/v1", True), ("http://my-proxy.example.com/v1", True),
    ("https://my-proxy.example.com/v1", False), ("http://localhost:11434/v1", False),
    ("http://127.0.0.1:1234/v1", False), ("http://[::1]:8000/v1", False)])
def test_a_key_about_to_go_unencrypted_is_flagged(url, warn):
    assert plain_http_elsewhere(url) is warn


def test_the_single_instance_pipe_is_for_this_user_only(monkeypatch):
    from PySide6.QtNetwork import QLocalServer
    monkeypatch.setattr(companion, "SERVER_NAME", f"xiaogua-pytest-{os.getpid()}")
    server = companion.claim_single_instance(lambda: None)
    try:
        assert server is not None and server.socketOptions() & QLocalServer.UserAccessOption
    finally:
        server.close()
