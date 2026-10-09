"""Conversations (会话): separate chat threads, each with its own messages and Q&A turns.

Stored one file per conversation in history/chats/<id>.json, text only. A new conversation
starts with a clean context; the old ones stay in the list until deleted.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

TITLE_CHARS = 18


@dataclass
class Chat:
    id: str
    title: str = ""
    created: str = ""
    updated: str = ""
    messages: list = field(default_factory=list)    # [{"id", "role", "text", "at", "reply_to"}]
    daily: list = field(default_factory=list)       # Q&A turns the model sees [{"q", "a", "at", "id"}]

    @property
    def empty(self) -> bool:
        return not self.messages and not self.daily

    def entitle(self, question: str) -> None:
        """The first question names the conversation."""
        if not self.title:
            text = " ".join((question or "").split())
            self.title = (text[:TITLE_CHARS] + ("…" if len(text) > TITLE_CHARS else "")) if text else "新对话"


def new_chat(now: datetime) -> Chat:
    stamp = now.isoformat()
    return Chat(id=uuid.uuid4().hex[:12], created=stamp, updated=stamp)


class ChatStore:
    """history/chats: list, load, save, delete. folder None keeps everything in memory."""

    def __init__(self, folder: Path | None):
        self.folder = folder

    def _path(self, chat_id: str) -> Path | None:
        return self.folder / f"{chat_id}.json" if self.folder else None

    def save(self, chat: Chat) -> None:
        path = self._path(chat.id)
        if path is None or chat.empty:
            return                                      # an empty conversation is never written
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(chat), ensure_ascii=False, indent=1), encoding="utf-8")
        temp.replace(path)

    def load(self, chat_id: str) -> Chat | None:
        path = self._path(chat_id)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Chat(**{k: data.get(k, v) for k, v in asdict(Chat(id=chat_id)).items()})
        except (OSError, ValueError, TypeError):
            return None

    def delete(self, chat_id: str) -> bool:
        path = self._path(chat_id)
        if path is None or not path.is_file():
            return False
        path.unlink()
        return True

    def list(self) -> list[dict]:
        """Newest first: [{"id", "title", "updated", "count"}]."""
        if not self.folder or not self.folder.is_dir():
            return []
        out = []
        for path in self.folder.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append({"id": data.get("id", path.stem), "title": data.get("title") or "新对话",
                        "updated": data.get("updated", ""), "count": len(data.get("messages", []))})
        return sorted(out, key=lambda c: c["updated"], reverse=True)
