"""Claude Code session transcripts: discovery and parsing.

Layout on disk (Claude Code 2.1.x):

* ``~/.claude/projects/<project>/<session-id>.jsonl`` — one JSONL file per
  session, where ``<project>`` is the session's cwd with ``/`` replaced by
  ``-`` (e.g. ``~/work/api`` → ``-Users-me-work-api``).
* ``~/.claude/sessions/<pid>.json`` — state for every *running* Claude Code
  process (``pid``, ``sessionId``, ``cwd``). The file is removed when the
  process exits, so a session is finished exactly when no live process owns
  it. PIDs are liveness-checked, so state files left behind by crashed
  processes do not block discovery.

Record schema: each line is a JSON object keyed by ``type``. ``user`` and
``assistant`` records carry a ``message`` whose ``content`` is either a
string (user prompts) or a list of blocks — ``text``, ``thinking``,
``tool_use`` (assistant) and ``tool_result`` (user). Records with
``isSidechain: true`` belong to subagent transcripts; ``isApiErrorMessage``
assistant records are API error placeholders; ``isMeta`` user records are
system-injected rather than typed by the human. Of the metadata record
types only ``custom-title`` is read (it names the session); the rest
(``queue-operation``, ``mode``, ``attachment``, ``file-history-snapshot``,
``summary``, ...) are ignored.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from unbury.parsers import ParsedSession, ToolCall, Turn

PROJECTS_DIR = Path.home() / ".claude" / "projects"
SESSIONS_DIR = Path.home() / ".claude" / "sessions"

# Text that Claude Code generates rather than the human or the agent:
# slash-command envelopes, IDE events, task notifications, interrupt notices.
_NOISE_TEXT_PREFIXES = (
    "<command-",
    "<local-command",
    "<system-reminder",
    "<builtin>",
    "<ide",
    "<task-",
    "Caveat:",
    "[Request interrupted",
)


def latest_finished_session(
    cwd: Path | str | None = None,
    *,
    projects_dir: Path | None = None,
    sessions_dir: Path | None = None,
) -> Path | None:
    """Return the newest finished session file for ``cwd``, or ``None``.

    Sessions owned by a live Claude Code process are skipped, so the card is
    never built from the currently-open session. ``projects_dir`` and
    ``sessions_dir`` override the default on-disk locations (used by tests).
    """
    root = projects_dir or PROJECTS_DIR
    cwd = Path(cwd or Path.cwd()).resolve()
    project_dir = root / str(cwd).replace("/", "-")
    if not project_dir.is_dir():
        return None
    candidates = sorted(
        (p for p in project_dir.glob("*.jsonl") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    live = _live_session_ids(sessions_dir or SESSIONS_DIR)
    for path in candidates:
        if path.stem not in live:
            return path
    return None


def parse_session(path: Path | str) -> ParsedSession:
    """Normalize a Claude Code session JSONL file into shared turns."""
    path = Path(path)
    turns: list[Turn] = []
    title: str | None = None
    session_id: str | None = None
    cwd: str | None = None
    unparsed = 0

    with path.open(encoding="utf-8", errors="replace") as fh:
        for line_no, raw in enumerate(fh, 1):
            try:
                record = json.loads(raw)
            except ValueError:
                unparsed += 1
                continue
            if not isinstance(record, dict):
                unparsed += 1
                continue

            rtype = record.get("type")
            if rtype == "custom-title":
                if record.get("customTitle"):
                    title = record["customTitle"]
                continue
            if rtype not in ("user", "assistant"):
                continue
            if record.get("isSidechain") or record.get("isMeta"):
                continue
            if rtype == "assistant" and record.get("isApiErrorMessage"):
                continue
            if rtype == "user" and not _is_human_origin(record):
                continue

            turn = _turn_from_record(record, line_no)
            if turn is None:
                continue
            turns.append(turn)
            session_id = session_id or record.get("sessionId")
            cwd = cwd or record.get("cwd")

    timestamps = [t.timestamp for t in turns if t.timestamp is not None]
    return ParsedSession(
        path=path,
        agent="claude",
        session_id=session_id or path.stem,
        title=title,
        cwd=cwd,
        started_at=min(timestamps) if timestamps else None,
        ended_at=max(timestamps) if timestamps else None,
        turns=turns,
        unparsed_lines=unparsed,
    )


def _turn_from_record(record: dict, line_no: int) -> Turn | None:
    message = record.get("message") or {}
    content = message.get("content")
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []

    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
            elif btype == "tool_use":
                tool_input = block.get("input")
                tool_calls.append(
                    ToolCall(
                        name=str(block.get("name") or "?"),
                        input=tool_input if isinstance(tool_input, dict) else {},
                        line=line_no,
                        id=block.get("id"),
                    )
                )

    text = "\n\n".join(part for part in text_parts if part).strip()
    if text and text.startswith(_NOISE_TEXT_PREFIXES):
        text = ""
    if not text and not tool_calls:
        return None
    return Turn(
        role=record["type"],
        line=line_no,
        text=text,
        tool_calls=tool_calls,
        timestamp=_timestamp(record.get("timestamp")),
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_human_origin(record: dict) -> bool:
    """Did a human type this user record?

    Claude Code injects user-role records for IDE events, task notifications
    and command echoes; those carry ``origin.kind`` values other than
    ``"human"``. Records without an ``origin`` field (older format) fall back
    to text-prefix filtering in ``_turn_from_record``.
    """
    origin = record.get("origin")
    if isinstance(origin, dict):
        return origin.get("kind") == "human"
    return True


def _live_session_ids(sessions_dir: Path) -> set[str]:
    """Session ids owned by a running Claude Code process."""
    ids: set[str] = set()
    if not sessions_dir.is_dir():
        return ids
    for state_file in sessions_dir.glob("*.json"):
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pid, session_id = state.get("pid"), state.get("sessionId")
        if isinstance(pid, int) and session_id and _pid_alive(pid):
            ids.add(session_id)
    return ids


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # alive, owned by another user
    return True
