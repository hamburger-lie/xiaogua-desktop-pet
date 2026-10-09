"""小瓜's small life between questions: when to speak up, idle fidgets, night, being patted.

Learnt from other companions:
- 逗逗: proactive talk is opt-in and adjustable (正常 / 少 / 关), and only on set events,
  never the model chatting on its own.
- VPet / DyberPet: random idle actions with probabilities, a night routine (sleep sooner),
  touch-head reactions.
Pure logic here; the pet (app.py) owns the timers and the drawing.
"""

from __future__ import annotations

import random
import time
from datetime import datetime

PROACTIVE_LEVELS = ("正常", "少", "关")
# What may make 小瓜 speak up without being asked, per level.
#   morning: the daily 黄历 line     plan: a plan due today / how a past one went
#   night: a word when woken late at night
_ALLOWED = {
    "正常": {"morning", "plan", "night"},
    "少": {"plan"},
    "关": set(),
}

NIGHT_START, NIGHT_END = 23, 6           # 23:00 – 06:00
NIGHT_SLEEP_MS = 2 * 60_000              # at night 小瓜 dozes off after two quiet minutes
FIDGET_MS = (60_000, 150_000)            # an idle fidget every one to two and a half minutes
FIDGETS = (("点头", 3), ("歪头", 3), ("招手", 1))


def reminder_text(text: str, at: str, now: datetime) -> str:
    """「到点啦：交报告（15:00）」, or, when 小瓜 was not running then, that it is late."""
    hour, minute = int(at[:2]), int(at[3:])
    late = (now.hour * 60 + now.minute) - (hour * 60 + minute) > 5
    return f"刚才 {at} 的事：{text}（那会儿小瓜没开着）" if late else f"到点啦：{text}（{at}）"


PAT_LINES = ("嘿嘿", "痒～", "再摸要收费了", "瓜瓜开心", "头发要乱了啦", "嗯？")


def allows(level: str, kind: str) -> bool:
    return kind in _ALLOWED.get(level, _ALLOWED["正常"])


def is_night(now: datetime | None = None) -> bool:
    hour = (now or datetime.now()).hour
    return hour >= NIGHT_START or hour < NIGHT_END


def fidget_delay(rng: random.Random | None = None) -> int:
    return (rng or random).randint(*FIDGET_MS)


def pick_fidget(available: set[str], rng: random.Random | None = None) -> str | None:
    """A random idle action among those that have artwork."""
    choices = [(name, weight) for name, weight in FIDGETS if name in available]
    if not choices:
        return None
    names, weights = zip(*choices)
    return (rng or random).choices(names, weights)[0]


class PatDetector:
    """Patting = the mouse rubbing back and forth over the head without a button pressed.

    Three changes of direction, each at least `step` pixels, within `window` seconds,
    in the head area (top 45%, middle 70% of the pet), count as one pat; then a cooldown.
    """

    def __init__(self, step: int = 6, reversals: int = 3, window: float = 1.5, cooldown: float = 4.0):
        self.step, self.reversals, self.window, self.cooldown = step, reversals, window, cooldown
        self._last_x: float | None = None
        self._direction = 0
        self._turns: list[float] = []
        self._quiet_until = 0.0

    @staticmethod
    def on_head(x: float, y: float, width: float, height: float) -> bool:
        return y < height * 0.45 and width * 0.15 < x < width * 0.85

    def feed(self, x: float, y: float, width: float, height: float, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self.on_head(x, y, width, height) or now < self._quiet_until:
            self._last_x, self._direction, self._turns = None, 0, []
            return False
        if self._last_x is None:
            self._last_x = x
            return False
        moved = x - self._last_x
        if abs(moved) < self.step:
            return False
        direction = 1 if moved > 0 else -1
        if self._direction and direction != self._direction:
            self._turns = [t for t in self._turns if now - t <= self.window] + [now]
        self._direction, self._last_x = direction, x
        if len(self._turns) >= self.reversals:
            self._turns, self._direction, self._last_x = [], 0, None
            self._quiet_until = now + self.cooldown
            return True
        return False
