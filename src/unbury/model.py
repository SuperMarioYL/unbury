"""The AnswerCard model — unbury's core primitive.

A card is a typed, provenance-linked conclusion over one finished agent
session: which session it came from (:class:`SessionRef`), the agent's final
answer extracted verbatim (``conclusion``), and what the session actually did
(:class:`Evidence` rows — files edited, commands run, decisions stated), each
carrying the exact ``path:line`` transcript location it came from.

Parsers normalize each agent's JSONL dialect into the ``Turn`` /
``ToolCall`` / ``ParsedSession`` contracts (see :mod:`unbury.parsers`,
re-exported below so the whole data model imports from one place).
:mod:`unbury.extract` builds cards from parsed sessions; renderers
(:mod:`unbury.render`, :mod:`unbury.htmlview`) consume only this model, which
is what keeps extraction and rendering agent-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from unbury.parsers import ParsedSession, ToolCall, Turn

__all__ = [
    "AnswerCard",
    "Evidence",
    "ParsedSession",
    "SessionRef",
    "ToolCall",
    "Turn",
]


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
