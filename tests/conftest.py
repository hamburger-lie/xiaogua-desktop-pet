"""Shared test setup."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _close_windows():
    """Close every window a test left open.

    A 小瓜 left on screen by an earlier test still gets mouse events (another window moving
    over it is enough) and saves its settings, into whatever MEIHUA_HOME the current test
    uses: a later test then read someone else's config.
    """
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    from PySide6.QtCore import QEvent

    app = QApplication.instance()
    if app is not None:                     # hidden is not enough offscreen: they still get Enter events
        for window in app.topLevelWidgets():
            window.hide()
            window.deleteLater()
        QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
