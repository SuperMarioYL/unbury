"""Agent-agnostic session transcript contracts.

Each parser (Claude Code, Codex) normalizes its agent's JSONL dialect into
the ``ParsedSession`` / ``Turn`` / ``ToolCall`` shapes defined here, so that
extraction and card rendering never need to know which agent produced a
session.

Line numbers are 1-based positions in the session JSONL file, which is what
turns a reference into a jumpable ``path:line`` transcript location.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal


@dataclass
class ToolCall:
    """A single tool invocation inside an assistant turn."""

    name: str
    input: dict[str, Any] = field(default_factory=dict)
    line: int = 0
    id: str | None = None


@dataclass
class Turn:
    """One normalized conversational turn.

    ``text`` is the visible message text (empty for pure tool-call turns).
    Tool *results* are not normalized: evidence comes from tool-call inputs,
    not their outputs.
    """

    role: Literal["user", "assistant"]
    line: int
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    timestamp: datetime | None = None


@dataclass
class ParsedSession:
    """A finished agent session, normalized from its on-disk transcript."""

    path: Path
    agent: str  # "claude" | "codex"
    session_id: str | None = None
    title: str | None = None
    cwd: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    turns: list[Turn] = field(default_factory=list)
    unparsed_lines: int = 0
