"""User settings for the desktop app: a JSON file, a credential, a Run-key entry.

- Preferences live in %APPDATA%/MeiriYigua/config.json (MEIHUA_HOME overrides
  the folder; tests point it at a temp dir). Unknown keys are kept, missing keys
  take defaults, so older and newer versions can share one file.
- Each provider's API key is stored in Windows Credential Manager under its own
  name, never in the JSON. The provider's environment variable (ANTHROPIC_API_KEY,
  DEEPSEEK_API_KEY, ...) still works and wins.
- "Start with Windows" is a value under HKCU\\...\\Run pointing at this program.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import providers

APP_NAME = "每日一瓜"
CREDENTIAL_PREFIX = "xiaogua-desktop-pet"  # credential name: <prefix>/<provider>-api-key
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "xiaogua-desktop-pet"

MODEL_CHOICES = list(providers.BY_ID["anthropic"].models)
DEFAULT_MODEL = MODEL_CHOICES[0]


def home() -> Path:
    base = os.environ.get("MEIHUA_HOME") or Path(os.environ.get("APPDATA", Path.home())) / "MeiriYigua"
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_dir() -> Path:
    """The conversations: history/chats/<id>.json."""
    return home() / "history"


def log_dir() -> Path:
    path = home() / "logs"
    path.mkdir(exist_ok=True)
    return path


@dataclass
class Config:
    provider: str = providers.DEFAULT
    models: dict = field(default_factory=dict)       # provider id -> chosen model
    base_urls: dict = field(default_factory=dict)    # provider id -> address, when changed from the preset
    offline: bool = False
    pet_size: int = 220
    opacity: int = 100                  # percent
    click_through: bool = False
    always_on_top: bool = True
    sleep_minutes: int = 10
    bubble_seconds: int = 20            # how long an answer stays before 小瓜 goes back to idle
    hotkey: str = "<ctrl>+<alt>+x"     # 叫出小瓜: the input box over 小瓜's head, from anywhere
    greet_on_start: bool = True
    keep_history: bool = True          # store the conversations (text only)
    voice_style: str = "平衡"          # 直白 / 平衡 / 玄一点
    zodiac: str = ""                    # the user's 属相 (鼠…猪), for the 黄历; "" = not told yet
    first_day: str = ""                 # the day 小瓜 was first opened (YYYY-MM-DD), for 「陪你第 N 天」
    last_greet: str = ""                # the day 小瓜 last said its morning line (YYYY-MM-DD)
    proactive: str = "正常"             # 主动说话: 正常 / 少 / 关 (life.py)
    mini: bool = False                  # 贴边小球 mode
    voice_hotkey: str = "<ctrl>+<alt>+v"    # 按键说话: once to start Windows voice typing, again to send
    deep_thinking: bool = False         # let models that think first (豆包 Seed…) do so: slower, ~10 s a call
    position: list[int] | None = None   # last top-left, restored on start
    chat_size: list[int] | None = None  # the chat panel's size, once the user has dragged its edges
    extra: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls) -> "Config":
        path = home() / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if "model" in data:                         # 0.4.0 files: one Anthropic model
            data.setdefault("models", {}).setdefault("anthropic", data.pop("model"))
        known = {f.name for f in fields(cls)} - {"extra"}
        config = cls(**{k: v for k, v in data.items() if k in known})
        config.extra = {k: v for k, v in data.items() if k not in known}
        return config

    @property
    def preset(self) -> providers.Provider:
        return providers.get(self.provider)

    @property
    def model(self) -> str:
        chosen = self.models.get(self.provider)
        return chosen or (self.preset.models[0] if self.preset.models else "")

    @model.setter
    def model(self, value: str) -> None:
        self.models[self.provider] = value

    @property
    def base_url(self) -> str:
        return self.base_urls.get(self.provider) or self.preset.base_url

    def save(self) -> None:
        data = asdict(self)
        data.update(data.pop("extra"))
        path = home() / "config.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)


# ------------------------------------------------------------ API key

class _CREDENTIAL(ctypes.Structure):
    _fields_ = [("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32), ("TargetName", ctypes.c_wchar_p),
                ("Comment", ctypes.c_wchar_p), ("LastWritten", ctypes.c_uint64),
                ("CredentialBlobSize", ctypes.c_uint32), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32),
                ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
                ("UserName", ctypes.c_wchar_p)]


_CRED_TYPE_GENERIC, _CRED_PERSIST_LOCAL_MACHINE = 1, 2


def _advapi():
    if sys.platform != "win32":
        return None
    return ctypes.WinDLL("advapi32", use_last_error=True)


def _target(provider: str) -> str:
    # anthropic keeps the name 0.4.0 used, so an already saved key still works
    return f"{CREDENTIAL_PREFIX}/{provider}-api-key"


def stored_api_key(provider: str = providers.DEFAULT) -> str | None:
    advapi = _advapi()
    if advapi is None:
        return None
    pointer = ctypes.POINTER(_CREDENTIAL)()
    if not advapi.CredReadW(_target(provider), _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        return None
    try:
        credential = pointer.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return blob.decode("utf-16-le") or None
    finally:
        advapi.CredFree(pointer)


def store_api_key(key: str, provider: str = providers.DEFAULT) -> None:
    advapi = _advapi()
    if advapi is None:
        env = providers.get(provider).env or "对应的"
        raise OSError(f"只有 Windows 支持把密钥存进凭据管理器；其他系统请用 {env} 环境变量")
    blob = key.encode("utf-16-le")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    credential = _CREDENTIAL(Type=_CRED_TYPE_GENERIC, TargetName=_target(provider),
                             CredentialBlobSize=len(blob), CredentialBlob=buffer,
                             Persist=_CRED_PERSIST_LOCAL_MACHINE, UserName=provider)
    if not advapi.CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def delete_api_key(provider: str = providers.DEFAULT) -> None:
    advapi = _advapi()
    if advapi is not None:
        advapi.CredDeleteW(_target(provider), _CRED_TYPE_GENERIC, 0)


def api_key(provider: str = providers.DEFAULT) -> tuple[str | None, str]:
    """(key, where it came from). The provider's environment variable wins over the stored key."""
    preset = providers.get(provider)
    if preset.env and os.environ.get(preset.env):
        return os.environ[preset.env], f"环境变量 {preset.env}"
    key = stored_api_key(provider)
    if key:
        return key, "Windows 凭据管理器"
    return None, "本机服务，不需要密钥" if not preset.needs_key else "未设置"


def mask(key: str | None) -> str:
    return "" if not key else f"{key[:7]}…{key[-4:]}" if len(key) > 14 else "••••"


# ------------------------------------------------------------ autostart

def launch_command() -> str:
    """How Windows should start 小瓜 at login: the packaged exe, or pythonw -m."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --autostart'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    interpreter = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{interpreter}" -m meihua.companion.app --autostart'


def autostart_enabled() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_VALUE)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        raise OSError("开机自启目前只支持 Windows")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE)
            except FileNotFoundError:
                pass
