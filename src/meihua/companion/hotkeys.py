"""Global hotkeys (叫出小瓜, 按键说话).

On Windows they are registered with the system (RegisterHotKey): Windows itself tells 小瓜
when the combination is pressed, whatever program is in front, and lets 小瓜 take the
keyboard right then. The first version listened with pynput's keyboard hook, which Windows
quietly drops when the program is slow to answer it: the keys then did nothing, with no sign.
A combination another program has already registered is reported, not silently lost.

Elsewhere pynput is still used.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable

log = logging.getLogger("xiaogua")

WM_HOTKEY = 0x0312
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
MODIFIERS = {"ctrl": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "cmd": MOD_WIN}
NAMED_KEYS = {"space": 0x20, "tab": 0x09, "enter": 0x0D, "insert": 0x2D, "home": 0x24, "end": 0x23,
              "page_up": 0x21, "page_down": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
              "pause": 0x13, "print_screen": 0x2C}
HELD_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)      # Shift, Ctrl, Alt, left and right Win


def parse(combo: str) -> tuple[int, int]:
    """pynput's hotkey string (what the settings store) as Windows modifier flags and key code:
    '<ctrl>+<alt>+x' -> (MOD_CONTROL | MOD_ALT, 0x58)."""
    mods, vk = 0, None
    for part in combo.lower().split("+"):
        name = part.strip("<>")
        if part.startswith("<") and name in MODIFIERS:
            mods |= MODIFIERS[name]
        elif part.startswith("<") and name[:1] == "f" and name[1:].isdigit() and 1 <= int(name[1:]) <= 24:
            vk = 0x6F + int(name[1:])
        elif part.startswith("<") and name in NAMED_KEYS:
            vk = NAMED_KEYS[name]
        elif len(part) == 1 and part.isascii() and part.isalnum():
            vk = ord(part.upper())
        else:
            raise ValueError(f"认不出「{part}」这个键")
    if vk is None:
        raise ValueError("组合里少了一个主键")
    return mods, vk


def modifiers_held() -> bool:
    """Is Ctrl, Alt, Shift or Win still physically down? (Windows only; elsewhere: no.)"""
    if sys.platform != "win32":
        return False
    state = ctypes.windll.user32.GetAsyncKeyState
    return any(state(vk) & 0x8000 for vk in HELD_VKS)


class WindowsHotkeys:
    """Hotkeys registered with Windows, delivered to a hidden window of our own.

    `failed` lists the combinations Windows refused (another program has them).
    """

    def __init__(self, keys: dict[str, Callable[[], None]]):
        from ctypes import wintypes

        from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QTimer
        from PySide6.QtWidgets import QWidget

        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
        user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
        self._user32 = user32
        self._window = QWidget()                      # never shown; its handle receives WM_HOTKEY
        self._hwnd = int(self._window.winId())
        self._actions: dict[int, Callable[[], None]] = {}
        self.failed: list[str] = []
        for number, (combo, action) in enumerate(keys.items(), start=1):
            mods, vk = parse(combo)
            if user32.RegisterHotKey(self._hwnd, number, mods | MOD_NOREPEAT, vk):
                self._actions[number] = action
                log.info("快捷键已登记：%s", combo)
            else:
                self.failed.append(combo)
                log.warning("快捷键登记失败（可能被别的程序占用）：%s，错误码 %s", combo, ctypes.GetLastError())
        actions, hwnd = self._actions, self._hwnd

        class Filter(QAbstractNativeEventFilter):
            def nativeEventFilter(self, event_type, message):
                if bytes(event_type) == b"windows_generic_MSG":
                    msg = wintypes.MSG.from_address(int(message))
                    if msg.message == WM_HOTKEY and msg.hWnd == hwnd and msg.wParam in actions:
                        log.info("快捷键按下：%s", msg.wParam)
                        QTimer.singleShot(0, actions[msg.wParam])    # out of the window procedure first
                        return True, 0
                return False, 0

        self._filter = Filter()
        QCoreApplication.instance().installNativeEventFilter(self._filter)

    def stop(self):
        from PySide6.QtCore import QCoreApplication

        for number in self._actions:
            self._user32.UnregisterHotKey(self._hwnd, number)
        self._actions.clear()
        app = QCoreApplication.instance()
        if app is not None and self._filter is not None:
            app.removeNativeEventFilter(self._filter)
        self._filter = None
        self._window.deleteLater()


class PynputHotkeys:
    """The keyboard-hook way, for systems other than Windows."""

    def __init__(self, keys: dict[str, Callable[[], None]]):
        from pynput import keyboard

        self.failed: list[str] = []
        self._listener = keyboard.GlobalHotKeys(keys)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        self._listener.stop()


def start(keys: dict[str, Callable[[], None]]):
    """Listen for each combination (pynput's string form) and call its action in the GUI thread."""
    for combo in keys:
        parse(combo)                                  # a bad string is the caller's error: say so now
    if sys.platform == "win32":
        return WindowsHotkeys(keys)
    return PynputHotkeys(keys)
