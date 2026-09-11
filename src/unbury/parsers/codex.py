"""Codex session transcripts: finished-session discovery and parsing.

Layout on disk (verified against real Codex CLI / Desktop sessions):

* ``~/.codex/sessions/YYYY/MM/DD/rollout-<timestamp>-<thread-id>[_<id>].jsonl``
  — one JSONL "rollout" file per conversation segment. A continued thread
  writes a new file whose name carries the original thread id plus a
  continuation suffix. Subagent threads (``session_meta.thread_source ==
  "subagent"``) write their own rollout files and are not user sessions, so
  discovery skips them. Codex keeps no liveness registry (its
  ``thread-writer-locks`` are never cleaned up), so a session counts as
  finished once its file has been quiescent for ``FINISHED_GRACE_SECONDS``.

Record schema: every line is ``{"timestamp", "ordinal", "type", "payload"}``.
``response_item`` records are the model transcript — everything a card needs:

* ``payload.type "message"`` — ``role`` ``user``/``assistant`` (``developer``
  records are system instructions). Content blocks carry ``input_text``
  (user) or ``output_text`` (assistant). User texts that are system
  envelopes (``<environment_context>``, ``<codex_internal_context>``,
  ``# Files mentioned by the user``, ...) are dropped, mirroring the
  ``isMeta`` filtering in the Claude parser.
* ``payload.type "reasoning"`` — thinking; skipped.
* ``payload.type "custom_tool_call"``:
  - ``name "exec"`` (July 2026 onward): ``input`` is a JavaScript source
    string. Commands run as ``tools.exec_command({cmd:"..."})`` and file
    edits as ``tools.apply_patch("...")`` — current sessions contain zero
    structured apply_patch calls, so file-edit evidence exists only inside
    those JS string literals. The patch markers (``*** Add/Update/Delete
    File:``) are recovered by decoding the literals.
  - ``name "apply_patch"`` (older sessions): ``input`` is the raw patch text.
* ``payload.type "function_call"`` (older sessions): ``exec_command`` with
  JSON arguments ``{"cmd": ...}`` and ``apply_patch`` with
  ``{"input": <patch>}``.
* ``event_msg`` / ``turn_context`` / ``token_usage_record`` lines are UI and
  accounting events that duplicate response items; skipped.

Tool calls are normalized into the shared evidence vocabulary that
``unbury.extract`` recognizes: a file edit becomes a ``Write``/``Edit`` call
with a ``file_path`` input and a shell command becomes a ``Bash`` call with
a ``command`` input. Scripts whose JS the heuristics cannot fully decode
still yield the calls that were recovered, plus one placeholder call
carrying the raw script so the transcript keeps the fact that a tool ran.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from unbury.parsers import ParsedSession, ToolCall, Turn

SESSIONS_DIR = Path.home() / ".codex" / "sessions"

# A rollout file untouched for this many seconds is treated as finished.
# Active turns write records frequently but can pause for minutes while a
# long command runs (gaps up to ~5 minutes observed in real sessions), so
# the grace must cover those pauses to avoid carding a session mid-turn.
FINISHED_GRACE_SECONDS = 300

_ROLLOUT_GLOB = "rollout-*.jsonl"
_ROLLOUT_NAME_RE = re.compile(r"^rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-(.+)$")

# System-generated user texts: environment and context envelopes, plugin
# notices, interrupt notices, attachment listings.
_NOISE_TEXT_PREFIXES = (
    "<environment_context>",
    "<codex_internal_context",
    "<goal_context>",
    "<in-app-browser-context",
    "<recommended_plugins>",
    "<skill",
    "<subagent_notification",
    "<turn_aborted>",
    "<send_user_message_question_reply",
    "# Files mentioned by the user",
)

_PATCH_MARKER = "*** Begin Patch"
_PATCH_FILE_RE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+)$", re.MULTILINE)
# A ``cmd`` property (quoted or bare) whose value is a string literal.
_CMD_PROP_RE = re.compile(r"[\"']?cmd[\"']?\s*:\s*(?=[\"'`])")

_JS_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_JS_UNICODE_RE = re.compile(r"\{([0-9a-fA-F]+)\}|([0-9a-fA-F]{4})")


@dataclass
class SessionHeader:
    """Line-1 ``session_meta`` metadata of a rollout file."""

    session_id: str
    cwd: str | None
    started_at: datetime | None
    subagent: bool


@dataclass
class FinishedSession:
    """A quiescent, non-subagent rollout session ready to be read."""

    path: Path
    session_id: str
    cwd: str | None
    started_at: datetime | None
    modified_at: datetime


def session_files(*, sessions_dir: Path | None = None) -> list[tuple[datetime, Path]]:
    """Every rollout file under ``sessions_dir`` as ``(modified_at, path)``,
    newest-first."""
    root = sessions_dir or SESSIONS_DIR
    if not root.is_dir():
        return []
    files = []
    for path in root.glob(f"*/*/*/{_ROLLOUT_GLOB}"):
        if path.is_file():
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            files.append((modified_at, path))
    files.sort(key=lambda entry: entry[0], reverse=True)
    return files


def finished_sessions(
    *, sessions_dir: Path | None = None, grace: float = FINISHED_GRACE_SECONDS
) -> Iterator[FinishedSession]:
    """Quiescent, non-subagent rollout sessions, newest-first."""
    cutoff = time.time() - grace
    for modified_at, path in session_files(sessions_dir=sessions_dir):
        if modified_at.timestamp() > cutoff:
            continue
        header = read_header(path)
        if header is None or header.subagent:
            continue
        yield FinishedSession(
            path=path,
            session_id=header.session_id,
            cwd=header.cwd,
            started_at=header.started_at,
            modified_at=modified_at,
        )


def read_header(path: Path) -> SessionHeader | None:
    """Read a rollout file's ``session_meta`` header (its first line)."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            record = json.loads(fh.readline())
        payload = record["payload"]
        if record.get("type") != "session_meta" or not isinstance(payload, dict):
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    source = payload.get("source")
    cwd = payload.get("cwd")
    return SessionHeader(
        session_id=str(payload.get("session_id") or _session_id_from_name(path)),
        cwd=cwd if isinstance(cwd, str) else None,
        started_at=_timestamp(payload.get("timestamp")),
        subagent=payload.get("thread_source") == "subagent" or isinstance(source, dict),
    )


def parse_session(path: Path | str) -> ParsedSession:
    """Normalize a Codex rollout JSONL file into shared turns."""
    path = Path(path)
    turns: list[Turn] = []
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
            if rtype == "session_meta":
                payload = record.get("payload") or {}
                session_id = payload.get("session_id")
                cwd = payload.get("cwd")
                continue
            if rtype != "response_item":
                continue

            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            timestamp = _timestamp(record.get("timestamp"))
            ptype = payload.get("type")
            if ptype == "message":
                turn = _message_turn(payload, line_no, timestamp)
            elif ptype == "custom_tool_call":
                turn = _tool_call_turn(_custom_calls(payload, line_no), line_no, timestamp)
            elif ptype == "function_call":
                turn = _tool_call_turn(_function_calls(payload, line_no), line_no, timestamp)
            else:
                continue
            if turn is not None:
                turns.append(turn)

    timestamps = [t.timestamp for t in turns if t.timestamp is not None]
    return ParsedSession(
        path=path,
        agent="codex",
        session_id=session_id or _session_id_from_name(path),
        title=None,
        cwd=cwd,
        started_at=min(timestamps) if timestamps else None,
        ended_at=max(timestamps) if timestamps else None,
        turns=turns,
        unparsed_lines=unparsed,
    )


def _session_id_from_name(path: Path) -> str:
    """Thread id encoded in a rollout file name (before any continuation
    suffix)."""
    match = _ROLLOUT_NAME_RE.match(path.stem)
    if match is None:
        return path.stem
    return match.group(1).split("_", 1)[0]


def _message_turn(payload: dict, line_no: int, timestamp: datetime | None) -> Turn | None:
    role = payload.get("role")
    if role not in ("user", "assistant"):
        return None  # "developer" records are system instructions
    texts: list[str] = []
    for block in payload.get("content") or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype in ("input_text", "output_text") and isinstance(block.get("text"), str):
            texts.append(block["text"])
    text = "\n\n".join(part for part in texts if part).strip()
    if role == "user" and text.startswith(_NOISE_TEXT_PREFIXES):
        text = ""
    if not text:
        return None
    return Turn(role=role, line=line_no, text=text, timestamp=timestamp)


def _tool_call_turn(
    calls: list[ToolCall], line_no: int, timestamp: datetime | None
) -> Turn | None:
    if not calls:
        return None
    return Turn(role="assistant", line=line_no, tool_calls=calls, timestamp=timestamp)


def _custom_calls(payload: dict, line_no: int) -> list[ToolCall]:
    name = str(payload.get("name") or "?")
    raw = payload.get("input")
    if not isinstance(raw, str):
        return [ToolCall(name, {}, line_no, payload.get("id"))]

    if name == "exec":
        commands, edits = _exec_evidence(raw)
        calls = _command_calls(commands, line_no) + _edit_calls(edits, line_no)
        return calls or [ToolCall(name, {"input": raw}, line_no, payload.get("id"))]
    if name == "apply_patch":
        edits = _patch_edits(raw)
        calls = _edit_calls(edits, line_no)
        return calls or [ToolCall(name, {"input": raw}, line_no, payload.get("id"))]
    return [ToolCall(name, {"input": raw}, line_no, payload.get("id"))]


def _function_calls(payload: dict, line_no: int) -> list[ToolCall]:
    name = str(payload.get("name") or "?")
    arguments: dict = {}
    if isinstance(payload.get("arguments"), str):
        try:
            decoded = json.loads(payload["arguments"])
        except ValueError:
            decoded = None
        if isinstance(decoded, dict):
            arguments = decoded

    if name == "exec_command":
        command = arguments.get("cmd")
        if isinstance(command, str) and command:
            return _command_calls([command], line_no)
        return []
    if name == "apply_patch":
        patch = arguments.get("input")
        edits = _patch_edits(patch) if isinstance(patch, str) else []
        return _edit_calls(edits, line_no)
    return [ToolCall(name, arguments, line_no, payload.get("call_id"))]


def _command_calls(commands: list[str], line_no: int) -> list[ToolCall]:
    return [ToolCall("Bash", {"command": command}, line_no) for command in commands]


def _edit_calls(edits: list[tuple[str, str]], line_no: int) -> list[ToolCall]:
    return [ToolCall(tool, {"file_path": target}, line_no) for tool, target in edits]


def _patch_edits(patch: str) -> list[tuple[str, str]]:
    """File-edit evidence from an apply_patch payload: ``(tool, path)`` pairs
    where tool is ``Write`` for additions and ``Edit`` for updates and
    deletions."""
    edits: list[tuple[str, str]] = []
    for verb, raw_target in _PATCH_FILE_RE.findall(patch):
        target = raw_target.strip()
        if target:
            edits.append(("Write" if verb == "Add" else "Edit", target))
    return edits


def _exec_evidence(source: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Commands and file edits recovered from an exec tool-call script.

    Commands come from ``cmd`` string-literal properties of
    ``tools.exec_command`` calls; file edits from patch string literals
    passed to ``tools.apply_patch``. A ``cmd:`` match only counts when a
    decoded literal starts exactly there, which naturally ignores matches
    inside another string's body (patch content, heredocs).
    """
    literals = list(_js_literals(source))
    edits: list[tuple[str, str]] = []
    for _start, _end, text in literals:
        if _PATCH_MARKER in text:
            edits.extend(_patch_edits(text))

    commands: list[str] = []
    if "exec_command" not in source:
        return commands, edits
    by_start = {start: text for start, _end, text in literals}
    for match in _CMD_PROP_RE.finditer(source):
        command = by_start.get(match.end())
        if command and command not in commands:
            commands.append(command)
    return commands, edits


def _js_literals(source: str) -> Iterator[tuple[int, int, str]]:
    """Yield ``(start, end, decoded)`` for each string literal in a JS source
    string. Unterminated literals are skipped."""
    i, n = 0, len(source)
    while i < n:
        char = source[i]
        if char not in ('"', "'", "`"):
            i += 1
            continue
        quote = char
        j = i + 1
        body: list[str] = []
        while j < n:
            ch = source[j]
            if ch == "\\":
                body.append(source[j : j + 2])
                j += 2
                continue
            if ch == quote:
                yield i, j + 1, _decode_js_string("".join(body))
                break
            if ch == "\n" and quote != "`":
                break
            body.append(ch)
            j += 1
        i = j + 1


def _decode_js_string(body: str) -> str:
    """Decode JS escape sequences in a string literal body."""
    out: list[str] = []
    i, n = 0, len(body)
    while i < n:
        char = body[i]
        if char != "\\" or i + 1 >= n:
            out.append(char)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in _JS_ESCAPES:
            out.append(_JS_ESCAPES[nxt])
            i += 2
        elif nxt == "u":
            match = _JS_UNICODE_RE.match(body, i + 2)
            if match is not None:
                try:
                    out.append(chr(int(match.group(1) or match.group(2), 16)))
                    i = match.end()
                    continue
                except (ValueError, OverflowError):
                    pass
            out.append(nxt)
            i += 2
        else:
            out.append(nxt)
            i += 2
    return "".join(out)


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
