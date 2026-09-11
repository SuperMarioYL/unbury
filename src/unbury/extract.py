"""Heuristic conclusion and evidence extraction over normalized sessions.

Zero-config by design: no model calls, no API keys, no network. The
conclusion is the agent's final substantive answer, extracted verbatim —
never re-summarized. Evidence rows come from what the session actually did:

* ``file``     — file-edit tool calls (Write / Edit / MultiEdit / NotebookEdit)
* ``command``  — shell commands the agent ran (Bash)
* ``decision`` — mid-session assistant findings: substantive or structured
  texts that state a conclusion before the final one

Every row carries a ``path:line`` reference back into the session transcript.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from unbury.parsers import ParsedSession

FILE_EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
COMMAND_TOOLS = {"Bash"}

# Assistant texts shorter than this read as process narration ("证据齐了。现在
# 写改造计划。"), not findings; longer or structured texts carry operative
# conclusions worth surfacing.
_MIN_FINDING_CHARS = 120

_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")


@dataclass
class SessionRef:
    """Which finished session a card was built from."""

    agent: str
    path: Path
    turns: int
    title: str | None = None
    cwd: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass
class Evidence:
    """One provenance-linked row: something the session did, and the exact
    transcript location it happened at."""

    kind: str  # "file" | "command" | "decision"
    summary: str
    ref: tuple[Path, int]


@dataclass
class AnswerCard:
    """A typed, provenance-linked conclusion over a finished session log."""

    session: SessionRef
    conclusion: str
    conclusion_ref: tuple[Path, int] | None = None
    evidence: list[Evidence] = field(default_factory=list)


def build_card(session: ParsedSession) -> AnswerCard:
    """Build the answer card for a parsed session."""
    conclusion, conclusion_ref = _conclusion(session)
    return AnswerCard(
        session=_session_ref(session),
        conclusion=conclusion,
        conclusion_ref=conclusion_ref,
        evidence=_evidence(session, conclusion_ref),
    )


def _session_ref(session: ParsedSession) -> SessionRef:
    title = session.title
    if not title:
        first_prompt = next(
            (t.text for t in session.turns if t.role == "user" and t.text), ""
        )
        title = _headline(first_prompt) if first_prompt else None
    return SessionRef(
        agent=session.agent,
        path=session.path,
        turns=len(session.turns),
        title=title,
        cwd=session.cwd,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


def _conclusion(session: ParsedSession) -> tuple[str, tuple[Path, int] | None]:
    """The final substantive assistant answer, quoted verbatim."""
    for turn in reversed(session.turns):
        if turn.role == "assistant" and turn.text:
            return turn.text, (session.path, turn.line)
    return "", None


def _evidence(
    session: ParsedSession, conclusion_ref: tuple[Path, int] | None
) -> list[Evidence]:
    conclusion_line = conclusion_ref[1] if conclusion_ref else -1
    file_rows: dict[str, Evidence] = {}
    file_counts: dict[str, int] = {}
    command_rows: dict[str, Evidence] = {}
    decisions: list[Evidence] = []

    for turn in session.turns:
        if (
            turn.role == "assistant"
            and turn.text
            and turn.line != conclusion_line
            and _is_finding(turn.text)
        ):
            decisions.append(
                Evidence("decision", _headline(turn.text), (session.path, turn.line))
            )
        for call in turn.tool_calls:
            if call.name in FILE_EDIT_TOOLS:
                target = call.input.get("file_path") or call.input.get("notebook_path")
                if not isinstance(target, str) or not target:
                    continue
                key = str(Path(target))
                file_counts[key] = file_counts.get(key, 0) + 1
                if key not in file_rows:
                    verb = "write" if call.name == "Write" else "edit"
                    file_rows[key] = Evidence(
                        "file",
                        f"{verb} {_display_path(target, session.cwd)}",
                        (session.path, call.line),
                    )
            elif call.name in COMMAND_TOOLS:
                command = " ".join(str(call.input.get("command") or "").split())
                if not command or command in command_rows:
                    continue
                command_rows[command] = Evidence(
                    "command", _shorten(command, 72), (session.path, call.line)
                )

    for key, row in file_rows.items():
        if file_counts[key] > 1:
            row.summary = f"{row.summary} (×{file_counts[key]})"

    rows = list(file_rows.values()) + decisions + list(command_rows.values())
    rows.sort(key=lambda row: row.ref[1])
    return rows


def _is_finding(text: str) -> bool:
    """Does this assistant text state a finding rather than narrate process?"""
    if len(text) >= _MIN_FINDING_CHARS:
        return True
    return any(
        line.startswith(("#", "|", "- ", "* ", "```", "> ", "**"))
        for line in text.splitlines()
    )


def _headline(text: str, limit: int = 90) -> str:
    line = next(
        (source.strip() for source in text.splitlines() if source.strip()), ""
    )
    line = line.lstrip("#").strip()
    line = _LINK_RE.sub(r"\1", line)
    line = line.replace("**", "").replace("`", "").strip()
    return _shorten(line, limit)


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _display_path(target: str, cwd: str | None) -> str:
    if cwd:
        try:
            return str(Path(target).relative_to(cwd))
        except ValueError:
            pass
    return target
