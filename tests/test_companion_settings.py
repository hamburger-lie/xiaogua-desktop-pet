"""Settings, tray and packaging-related behaviour of the desktop app (headless)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from meihua.companion import app as companion  # noqa: E402
from meihua.companion import config  # noqa: E402
from meihua.companion.settings_window import SettingsWindow, hotkey_label, to_pynput  # noqa: E402

qapp = QApplication.instance() or QApplication([])


class FakeListener:
    def __init__(self, combo):
        self.combo, self.stopped = combo, False

    def stop(self):
        self.stopped = True


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("MEIHUA_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(config, "CREDENTIAL_PREFIX", "meihua-xiaogua-pytest-" + tmp_path.name)
    monkeypatch.setattr(companion, "start_hotkey", lambda combo, bridge, voice=None: FakeListener(combo))
    yield
    config.delete_api_key()


# ------------------------------------------------------------ config

def test_config_round_trip_keeps_unknown_keys():
    home = config.home()
    (home / "config.json").write_text(json.dumps({"opacity": 70, "from_a_newer_version": [1, 2]}),
                                      encoding="utf-8")
    loaded = config.Config.load()
    assert loaded.opacity == 70 and loaded.pet_size == 220          # missing keys take defaults
    loaded.pet_size = 300
    loaded.save()
    saved = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert saved["pet_size"] == 300 and saved["from_a_newer_version"] == [1, 2]
    assert "api" not in json.dumps(saved).lower()                   # no key ever lands here


def test_broken_config_file_falls_back_to_defaults():
    (config.home() / "config.json").write_text("{not json", encoding="utf-8")
    assert config.Config.load() == config.Config()


@pytest.mark.skipif(sys.platform != "win32", reason="Credential Manager is Windows-only")
def test_api_key_goes_to_credential_manager_and_env_wins(monkeypatch):
    assert config.api_key() == (None, "未设置")
    config.store_api_key("sk-ant-api03-abcdefghijklmnop")
    assert config.api_key() == ("sk-ant-api03-abcdefghijklmnop", "Windows 凭据管理器")
    assert config.mask("sk-ant-api03-abcdefghijklmnop") == "sk-ant-…mnop"
    monkeypatch.setenv("ARK_API_KEY", "sk-from-env")                           # 豆包, the default vendor
    assert config.api_key()[0] == "sk-from-env"
    config.delete_api_key()
    monkeypatch.delenv("ARK_API_KEY")
    assert config.api_key()[0] is None


def test_autostart_command_points_at_this_program():
    command = config.launch_command()
    assert command.endswith("--autostart")
    assert "meihua.companion.app" in command or getattr(sys, "frozen", False)


# ------------------------------------------------------------ hotkeys

def test_qt_key_presses_become_pynput_hotkeys():
    ctrl_alt = Qt.ControlModifier | Qt.AltModifier
    assert to_pynput(ctrl_alt, Qt.Key_G) == "<ctrl>+<alt>+g"
    assert to_pynput(Qt.NoModifier, Qt.Key_F8) == "<f8>"
    assert to_pynput(Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_Space) == "<ctrl>+<shift>+<space>"
    assert to_pynput(Qt.NoModifier, Qt.Key_G) is None                # would fire while typing
    assert to_pynput(Qt.ShiftModifier, Qt.Key_G) is None
    assert hotkey_label("<ctrl>+<alt>+g") == "Ctrl+Alt+G"
    assert hotkey_label("<cmd>+<f8>") == "Win+F8"


# ------------------------------------------------------------ app

def test_without_a_key_the_app_starts_offline_and_says_where_to_set_it():
    app = companion.Companion(config.Config.load())
    assert isinstance(app.pet.agent, companion.OfflineAgent)
    assert "设置" in app.notice
    app.start()
    assert app.pet.isVisible() and "没连上" in app.pet.bubble.toPlainText()     # short hint by 小瓜
    assert "API key" in app.pet.chat.transcript()[0][1]                          # details in the chat


def test_settings_apply_live_to_the_pet():
    app = companion.Companion(config.Config.load())
    cfg = app.config
    cfg.opacity, cfg.click_through, cfg.always_on_top = 60, True, False
    app.apply(cfg)
    assert abs(app.pet.windowOpacity() - 0.6) < 0.01
    flags = app.pet.windowFlags()
    assert flags & Qt.WindowTransparentForInput and not flags & Qt.WindowStaysOnTopHint
    assert app.tray_actions["through"].isChecked()


def test_tray_toggles_click_through_and_saves_it():
    app = companion.Companion(config.Config.load())
    app.toggle_click_through()
    assert app.pet.windowFlags() & Qt.WindowTransparentForInput
    assert config.Config.load().click_through is True
    app.toggle_click_through()
    assert not app.pet.windowFlags() & Qt.WindowTransparentForInput


def test_changing_the_hotkey_restarts_the_listener():
    app = companion.Companion(config.Config.load())
    first = app.listener
    app.config.hotkey = "<ctrl>+<shift>+x"
    app.apply(app.config)
    assert first.stopped and app.listener.combo == "<ctrl>+<shift>+x"
    assert "Ctrl+Shift+X" in app.tray_actions["ask"].text()


def test_a_click_on_the_tray_icon_calls_xiaogua_out_and_never_hides_it():
    from PySide6.QtWidgets import QSystemTrayIcon
    app = companion.Companion(config.Config.load())
    app.start(quiet=True)
    app._tray_clicked(QSystemTrayIcon.Trigger)
    assert app.pet.isVisible() and app.pet.bubble.asking                      # was: the click hid 小瓜
    app._tray_clicked(QSystemTrayIcon.Trigger)
    assert app.pet.isVisible()
    app.toggle_pet()                                                          # 隐藏小瓜 from the menu
    assert not app.pet.isVisible() and app.tray_actions["toggle"].text() == "显示小瓜"
    app._tray_clicked(QSystemTrayIcon.Trigger)
    assert app.pet.isVisible() and app.tray_actions["toggle"].text() == "隐藏小瓜"


def test_hotkey_strings_become_windows_key_codes():
    from meihua.companion import hotkeys
    from meihua.companion.settings_window import _SPECIAL
    assert hotkeys.parse("<ctrl>+<alt>+x") == (hotkeys.MOD_CONTROL | hotkeys.MOD_ALT, 0x58)
    assert hotkeys.parse("<ctrl>+<alt>+v") == (hotkeys.MOD_CONTROL | hotkeys.MOD_ALT, 0x56)
    assert hotkeys.parse("<f8>") == (0, 0x77)
    assert hotkeys.parse("<cmd>+<shift>+<space>") == (hotkeys.MOD_WIN | hotkeys.MOD_SHIFT, 0x20)
    for bad in ("<ctrl>+<alt>", "<ctrl>+<bogus>", "<ctrl>+é"):
        with pytest.raises(ValueError):
            hotkeys.parse(bad)
    keys = [Qt.Key(Qt.Key_F1 + n) for n in range(24)] + list(_SPECIAL) + \
           [Qt.Key(Qt.Key_A + n) for n in range(26)] + [Qt.Key(Qt.Key_0 + n) for n in range(10)]
    for key in keys:                                       # anything the settings can record can be registered
        combo = to_pynput(Qt.ControlModifier | Qt.AltModifier | Qt.ShiftModifier | Qt.MetaModifier, key)
        assert hotkeys.parse(combo)[1] > 0


def test_a_hotkey_another_program_has_is_said_out_loud(monkeypatch):
    class Taken(FakeListener):
        failed = ["<ctrl>+<alt>+v"]
    monkeypatch.setattr(companion, "start_hotkey", lambda combo, bridge, voice=None: Taken(combo))
    app = companion.Companion(config.Config.load())
    assert "Ctrl+Alt+V" in app.settings.hotkey_status.text() and "占用" in app.settings.hotkey_status.text()
    app.start(quiet=True)
    assert "占用" in app.pet.bubble.toPlainText() and "API key" in app.pet.chat.transcript()[0][1]
    monkeypatch.setattr(companion, "start_hotkey", lambda combo, bridge, voice=None: FakeListener(combo))
    app.config.voice_hotkey = "<ctrl>+<alt>+b"                          # the user picks another one
    app.apply(app.config)
    assert "占用" not in app.settings.hotkey_status.text() and app.hotkey_problem is None


def test_a_bad_hotkey_is_reported_not_raised(monkeypatch):
    app = companion.Companion(config.Config.load())

    def refuse(combo, bridge, voice=None):
        raise ValueError("bad combo")
    monkeypatch.setattr(companion, "start_hotkey", refuse)
    app.config.hotkey = "<ctrl>+<shift>+y"
    app.apply(app.config)
    assert app.listener is None and "用不了" in app.settings.hotkey_status.text()


def test_switching_model_rebuilds_the_agent_and_keeps_the_conversation(monkeypatch):
    built = []

    class FakeAgent:
        def __init__(self, model):
            self.model, self.history = model, []

    monkeypatch.setattr(companion, "build_agent",
                        lambda cfg: (built.append(cfg.model) or FakeAgent(cfg.model), None))
    app = companion.Companion(config.Config.load())
    app.pet.agent.history.append({"role": "user", "content": "上次问的面试"})
    app.config.model = "claude-sonnet-5"
    app.apply(app.config)
    assert built[-1] == "claude-sonnet-5" and app.pet.agent.model == "claude-sonnet-5"
    assert app.pet.agent.history == [{"role": "user", "content": "上次问的面试"}]


def test_pet_returns_to_its_saved_spot_but_not_onto_a_missing_monitor():
    cfg = config.Config.load()
    screen = QApplication.primaryScreen().availableGeometry()
    cfg.position = [screen.left() + 40, screen.top() + 40]
    app = companion.Companion(cfg)
    app.place_pet()
    assert (app.pet.x(), app.pet.y()) == (screen.left() + 40, screen.top() + 40)
    cfg.position = [screen.right() + 5000, 0]                        # that monitor was unplugged
    app.place_pet()
    assert screen.contains(app.pet.geometry().center())


# ------------------------------------------------------------ settings window

def test_settings_window_saves_and_emits_each_change():
    cfg = config.Config.load()
    window = SettingsWindow(cfg)
    seen = []
    window.changed.connect(lambda c: seen.append((c.pet_size, c.opacity)))
    window.size_slider.setValue(300)
    window.opacity_slider.setValue(80)
    assert seen[-1] == (300, 80)
    assert config.Config.load().pet_size == 300 and config.Config.load().opacity == 80


@pytest.mark.skipif(sys.platform != "win32", reason="Credential Manager is Windows-only")
def test_saving_the_key_in_the_window_rebuilds_the_agent(monkeypatch):
    app = companion.Companion(config.Config.load())
    monkeypatch.setattr(companion, "build_agent", lambda cfg: ("real-agent", None))
    app.settings.key_edit.setText("sk-ant-api03-zzzzzzzzzzzzzzzz")
    app.settings._save_key()
    assert app.pet.agent == "real-agent"
    assert app.settings.key_edit.text() == ""                        # not left on screen
    assert "凭据管理器" in app.settings.key_source.text() and "zzzz" in app.settings.key_source.text()


def test_closing_the_settings_window_only_hides_it():
    window = SettingsWindow(config.Config.load())
    window.show()
    window.close()
    assert not window.isVisible()


# ------------------------------------------------------------ lunar table

def test_lunar_table_matches_the_node_icu_script():
    import meihua  # noqa: F401
    import lunar
    try:
        subprocess.run(["node", "--version"], check=True, capture_output=True)
    except (OSError, subprocess.SubprocessError):
        pytest.skip("Node not installed; the table was built from it and checked day by day")
    script = str(meihua.ENGINES / "gregorian_to_lunar.mjs")
    for value, zone in (("2026-09-23T23:30:00+08:00", "Asia/Shanghai"),   # 子时 crosses the day
                        ("2023-03-22T12:00:00+08:00", "Asia/Shanghai"),   # leap 2nd month
                        ("2026-02-17T00:05:00+08:00", "Asia/Shanghai"),   # new year's first minutes
                        ("2026-09-23T15:30:00Z", "America/Los_Angeles")):
        node = json.loads(subprocess.run(["node", script, "--datetime", value, "--timezone", zone],
                                         check=True, capture_output=True, text=True, encoding="utf-8").stdout)
        mine = lunar.convert(value, zone)
        assert node["local_clock"] == mine["local_clock"]
        assert {k: node["lunar"][k] for k in ("year", "year_name", "month", "is_leap_month", "day")} == \
               {k: mine["lunar"][k] for k in ("year", "year_name", "month", "is_leap_month", "day")}


def test_the_about_page_opens_the_terms_and_privacy_text():
    import meihua
    window = SettingsWindow(config.Config.load())
    labels = [b.text() for b in window.findChildren(companion.QWidget) if hasattr(b, "text") and callable(b.text)
              and b.metaObject().className() == "QPushButton"]
    assert "查看使用协议与隐私说明" in labels
    text = (meihua.ROOT / "PRIVACY.txt").read_text(encoding="utf-8-sig")
    assert "不收集" in text and r"%APPDATA%\MeiriYigua" in text and "CC BY-NC 4.0" in text
