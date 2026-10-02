from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import (
    BaseMessage,
    message_to_dict,
    messages_from_dict,
)

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_DIR = Path(__file__).resolve().parent.parent / "data" / "chat_history"

_SAFE_NAME_RE = re.compile(r"[^0-9A-Za-z_\-]")

DEFAULT_MAX_MESSAGES = 10

DEFAULT_MAX_CACHED_SESSIONS = 512

_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _get_lock(session_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _locks[session_id] = lock
        return lock


def _safe_name(session_id: str) -> str:
    name = _SAFE_NAME_RE.sub("_", str(session_id)).strip("._")
    return name or "default"


def _trim_pairs(
    messages: list[BaseMessage], max_messages: int
) -> list[BaseMessage]:
    if max_messages <= 0:
        return messages
    if len(messages) <= max_messages:
        return messages

    start = len(messages) - max_messages
    for idx in range(start, len(messages)):
        if messages[idx].type == "human":
            return messages[idx:]

    for idx in range(start - 1, -1, -1):
        if messages[idx].type == "human":
            return messages[idx:]

    return messages[start:]


class FileChatMessageHistory(BaseChatMessageHistory):
    def __init__(
        self,
        session_id: str,
        storage_dir: str | os.PathLike[str] = DEFAULT_HISTORY_DIR,
        max_messages: int = DEFAULT_MAX_MESSAGES,
        encoding: str = "utf-8",
    ) -> None:
        self.session_id = str(session_id)
        self.storage_dir = Path(storage_dir)
        self.max_messages = max_messages
        self.encoding = encoding
        self.file_path = self.storage_dir / f"{_safe_name(self.session_id)}.json"

    @property
    def messages(self) -> list[BaseMessage]:
        if not self.file_path.exists():
            return []
        try:
            with open(self.file_path, "r", encoding=self.encoding) as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            logger.warning("历史文件读取失败，降级为空历史: %s", self.file_path)
            return []

        if not isinstance(data, list):
            return []

        try:
            return messages_from_dict(data)
        except (KeyError, TypeError, ValueError):
            logger.warning("历史文件内容不合法，降级为空历史: %s", self.file_path)
            return []

    def add_messages(self, messages: Sequence[BaseMessage]) -> None:
        if not messages:
            return

        with _get_lock(self.session_id):
            all_messages = self.messages
            all_messages.extend(messages)
            all_messages = _trim_pairs(all_messages, self.max_messages)

            payload = [message_to_dict(m) for m in all_messages]
            self._write(payload)

    def _write(self, payload: list[dict[str, Any]]) -> None:
        tmp_path = None
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

            fd, tmp_name = tempfile.mkstemp(
                dir=str(self.storage_dir), prefix=".tmp_", suffix=".json"
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding=self.encoding) as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.file_path)
        except (OSError, ValueError):
            logger.warning("历史写入失败，本轮记忆未落盘: %s", self.file_path, exc_info=True)
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def clear(self) -> None:
        with _get_lock(self.session_id):
            try:
                self.file_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("历史清空失败: %s", self.file_path, exc_info=True)

    def __repr__(self) -> str:
        return (
            f"FileChatMessageHistory(session_id={self.session_id!r}, "
            f"messages={len(self.messages)}, file={str(self.file_path)!r})"
        )


_history_cache: "OrderedDict[str, FileChatMessageHistory]" = OrderedDict()
_history_cache_guard = threading.Lock()


def get_session_history(
    session_id: str,
    storage_dir: str | os.PathLike[str] = DEFAULT_HISTORY_DIR,
    max_messages: int = DEFAULT_MAX_MESSAGES,
) -> FileChatMessageHistory:
    key = f"{Path(storage_dir)}\x00{max_messages}\x00{session_id}"
    with _history_cache_guard:
        history = _history_cache.get(key)
        if history is None:
            history = FileChatMessageHistory(
                session_id=session_id,
                storage_dir=storage_dir,
                max_messages=max_messages,
            )
            _history_cache[key] = history
        else:
            _history_cache.move_to_end(key)

        while len(_history_cache) > DEFAULT_MAX_CACHED_SESSIONS:
            _history_cache.popitem(last=False)

        return history


def trim_messages(
    messages: Sequence[BaseMessage],
    max_messages: int = DEFAULT_MAX_MESSAGES,
    keep_pairs: bool = True,
) -> list[BaseMessage]:
    items = list(messages)
    if max_messages <= 0:
        return items
    if not keep_pairs:
        return items[-max_messages:]
    return _trim_pairs(items, max_messages)


def format_history(
    messages: Sequence[BaseMessage],
    max_messages: int = DEFAULT_MAX_MESSAGES,
    max_chars: int = 2000,
) -> str:
    recent = _trim_pairs(list(messages), max_messages)

    role_map = {"human": "用户", "ai": "助手", "system": "系统", "tool": "工具"}

    lines: list[str] = []
    for idx, msg in enumerate(recent, start=1):
        role = role_map.get(getattr(msg, "type", ""), "消息")
        content = msg.content if isinstance(msg.content, str) else json.dumps(
            msg.content, ensure_ascii=False
        )
        lines.append(f"{idx}. {role}: {content}")

    text = "\n".join(lines)

    if max_chars > 0 and len(text) > max_chars:
        kept: list[str] = []
        used = 0
        for line in reversed(lines):
            extra = len(line) + (1 if kept else 0)
            if used + extra > max_chars:
                break
            kept.append(line)
            used += extra
        body = "\n".join(reversed(kept))
        if body:
            text = f"……（更早的对话已省略）\n{body}"
        else:
            text = lines[-1][:max_chars]

    return text


def new_session_id(prefix: str = "sess") -> str:
    return f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def list_sessions(
    storage_dir: str | os.PathLike[str] = DEFAULT_HISTORY_DIR,
) -> list[dict[str, Any]]:
    directory = Path(storage_dir)
    if not directory.is_dir():
        return []

    sessions: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        if path.name.startswith(".tmp_"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        sessions.append(
            {
                "session_id": path.stem,
                "file": str(path),
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "_mtime": stat.st_mtime,
            }
        )

    sessions.sort(key=lambda item: item["_mtime"], reverse=True)
    for item in sessions:
        del item["_mtime"]
    return sessions


def clear_session(
    session_id: str,
    storage_dir: str | os.PathLike[str] = DEFAULT_HISTORY_DIR,
) -> None:
    get_session_history(session_id, storage_dir=storage_dir).clear()
