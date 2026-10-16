"""One-command answer cards for finished coding agent sessions.

``unbury`` reads the session logs Claude Code and Codex already write to
disk, extracts the agent's final answer verbatim plus the evidence trail
(files edited, commands run, decisions made) with ``path:line`` references,
and renders a one-screen answer card. Zero config: no API key, no settings
file, no network.

The public surface, one import per pipeline stage:

* :mod:`unbury.model` — the AnswerCard primitive and parser contracts
* :mod:`unbury.parsers` — per-agent JSONL dialect parsers (Claude Code, Codex)
* :mod:`unbury.discover` — finished-session discovery and ``--session`` selection
* :mod:`unbury.extract` — heuristic conclusion/evidence extraction
* :mod:`unbury.render` — the one-screen terminal card
* :mod:`unbury.htmlview` — the linked transcript HTML view
* :mod:`unbury.cli` — the ``unbury`` command
"""

from unbury.discover import SessionInfo, latest_finished, list_sessions, select_session
from unbury.extract import build_card
from unbury.htmlview import write_html_view
from unbury.model import AnswerCard, Evidence, ParsedSession, SessionRef, ToolCall, Turn
from unbury.render import print_card

__version__ = "0.2.0"

__all__ = [
    "AnswerCard",
    "Evidence",
    "ParsedSession",
    "SessionInfo",
    "SessionRef",
    "ToolCall",
    "Turn",
    "__version__",
    "build_card",
    "latest_finished",
    "list_sessions",
    "print_card",
    "select_session",
    "write_html_view",
]
