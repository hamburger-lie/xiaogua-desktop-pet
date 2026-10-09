"""回收站: a deleted conversation or remembered fact waits here 30 days before it is gone for good.

One file per deleted thing in <home>/trash/. Deleting still does everything it did before at
once (小瓜 forgets the conversation, its words leave the match records); the trash only keeps
a copy to bring back. A conversation comes back whole (messages and 日常 turns); the match
turns its words were cleared from do not, and the 战绩 never left. 设置 → 回收站 lists it:
恢复, 彻底删除, 清空. 删除全部记录 empties it too. Single messages do not come here.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

TRASH_DAYS = 30
_ID = re.compile(r"\d{14}-[0-9a-f]{6}")


def _naive(now: datetime | None) -> datetime:
    return (now or datetime.now()).replace(tzinfo=None, microsecond=0)


class Trash:
    def __init__(self, folder: Path | None):
        self.folder = folder                  # None: nothing is kept (tests, no history)

    def _path(self, entry_id: str) -> Path | None:
        if self.folder is None or not _ID.fullmatch(str(entry_id)):
            return None
        return self.folder / f"{entry_id}.json"

    def put(self, kind: str, title: str, data: dict, now: datetime | None = None) -> str | None:
        """Keep a copy of something just deleted (kind: 对话 / 记忆). Returns its id."""
        if self.folder is None:
            return None
        now = _naive(now)
        entry_id = f"{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
        self.folder.mkdir(parents=True, exist_ok=True)
        entry = {"kind": kind, "title": title, "deleted": now.isoformat(), "data": data}
        self._path(entry_id).write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
        return entry_id

    def _read(self, path: Path) -> dict | None:
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            datetime.fromisoformat(entry["deleted"])
            return entry if isinstance(entry.get("data"), dict) else None
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list(self, now: datetime | None = None) -> list[dict]:
        """Newest first: [{"id", "kind", "title", "deleted", "days_left"}]."""
        if self.folder is None or not self.folder.is_dir():
            return []
        now = _naive(now)
        out = []
        for path in self.folder.glob("*.json"):
            entry = self._read(path)
            if entry is None:
                continue
            deleted = _naive(datetime.fromisoformat(entry["deleted"]))
            left = TRASH_DAYS - (now - deleted).days
            out.append({"id": path.stem, "kind": entry["kind"], "title": entry["title"],
                        "deleted": deleted, "days_left": max(left, 0)})
        return sorted(out, key=lambda e: e["deleted"], reverse=True)

    def take(self, entry_id: str) -> dict | None:
        """Out of the trash to be restored: {"kind", "title", "data", …}, or None."""
        path = self._path(entry_id)
        if path is None or not path.is_file():
            return None
        entry = self._read(path)
        path.unlink()
        return entry

    def drop(self, entry_id: str) -> bool:
        """彻底删除 one thing."""
        path = self._path(entry_id)
        if path is None or not path.is_file():
            return False
        path.unlink()
        return True

    def clear(self) -> int:
        if self.folder is None or not self.folder.is_dir():
            return 0
        paths = list(self.folder.glob("*.json"))
        for path in paths:
            path.unlink()
        return len(paths)

    def purge(self, now: datetime | None = None) -> int:
        """Gone for good after TRASH_DAYS (run at start)."""
        if self.folder is None or not self.folder.is_dir():
            return 0
        cutoff = _naive(now) - timedelta(days=TRASH_DAYS)
        count = 0
        for path in self.folder.glob("*.json"):
            entry = self._read(path)
            if entry is None or _naive(datetime.fromisoformat(entry["deleted"])) < cutoff:
                path.unlink()
                count += 1
        return count
