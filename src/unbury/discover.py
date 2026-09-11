"""Cross-agent session discovery: ``unbury list`` and ``--session`` selection.

Finished-session semantics live with the parsers: a Claude Code session is
finished when no live process owns it (``parsers.claude``), a Codex rollout
file when it has been quiescent past a grace period and is not a subagent
thread (``parsers.codex``). This module merges both agents' finished
sessions newest-first, filters by working directory, and promotes candidates
into :class:`SessionInfo` rows. A session file is parsed only when its row
is actually produced, so listing stays cheap.

Selection matches a ``--session`` reference against the session id, the file
stem, and the file path; longer prefixes disambiguate, and among equally
good matches the newest session wins.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from unbury.parsers import ParsedSession, claude, codex

DEFAULT_AGENTS: tuple[str, ...] = ("claude", "codex")
DEFAULT_LIMIT = 20

_PARSERS = {"claude": claude.parse_session, "codex": codex.parse_session}

# Selection match quality: an exact path beats an exact id/stem, which beats
# an id/stem prefix.
_PATH_MATCH = 3
_ID_MATCH = 2
_PREFIX_MATCH = 1


@dataclass
class SessionInfo:
    """One finished session as ``unbury list`` shows it."""

    agent: str
    path: Path
    session_id: str
    project: str
    cwd: str | None
    started_at: datetime | None
    ended_at: datetime | None
    turns: int
    modified_at: datetime


@dataclass
class SessionDirs:
    """Where each agent keeps its session logs. ``None`` fields fall back to
    the agent's real on-disk location; tests override them with fixture
    trees."""

    projects_dir: Path | None = None  # ~/.claude/projects
    claude_sessions_dir: Path | None = None  # ~/.claude/sessions (live state)
    codex_sessions_dir: Path | None = None  # ~/.codex/sessions


@dataclass
class _Candidate:
    """A finished session file plus the metadata discovery already had to
    read to find it."""

    agent: str
    path: Path
    session_id: str
    modified_at: datetime
    cwd: str | None = None
    project_hint: str | None = None


def list_sessions(
    cwd: Path | str | None = None,
    *,
    agents: Sequence[str] = DEFAULT_AGENTS,
    limit: int = DEFAULT_LIMIT,
    dirs: SessionDirs | None = None,
) -> list[SessionInfo]:
    """Finished sessions across agents, newest-first.

    ``cwd`` restricts the list to sessions run in that directory.
    """
    _check_agents(agents)
    rows: list[SessionInfo] = []
    if limit <= 0:
        return rows
    for candidate in _merged_candidates(cwd, agents, dirs or SessionDirs()):
        rows.append(_promote(candidate))
        if len(rows) >= limit:
            break
    return rows


def latest_finished(
    cwd: Path | str | None = None,
    *,
    agents: Sequence[str] = DEFAULT_AGENTS,
    dirs: SessionDirs | None = None,
) -> SessionInfo | None:
    """The newest finished session for ``cwd`` across agents, or ``None``."""
    _check_agents(agents)
    for candidate in _merged_candidates(cwd, agents, dirs or SessionDirs()):
        return _promote(candidate)
    return None


def select_session(
    ref: str,
    *,
    agents: Sequence[str] = DEFAULT_AGENTS,
    dirs: SessionDirs | None = None,
) -> SessionInfo | None:
    """The finished session identified by ``ref``: a session id, a unique id
    or file-stem prefix, or a session file path. ``None`` when nothing
    matches. The cwd filter does not apply — an explicit reference wins."""
    _check_agents(agents)
    ref = ref.strip()
    if not ref:
        return None
    ref_path = Path(ref).expanduser()
    if not ref_path.is_absolute():
        ref_path = None
    best: _Candidate | None = None
    best_score = 0
    for candidate in _merged_candidates(None, agents, dirs or SessionDirs()):
        score = _match_score(candidate, ref, ref_path)
        if score > best_score:
            best, best_score = candidate, score
            if score == _PATH_MATCH:
                break
    return None if best is None else _promote(best)


def _merged_candidates(
    cwd: Path | str | None, agents: Sequence[str], dirs: SessionDirs
) -> Iterator[_Candidate]:
    """Finished-session candidates across the requested agents, newest-first
    by file modification time."""
    streams: list[Iterator[_Candidate]] = []
    if "claude" in agents:
        streams.append(_claude_candidates(cwd, dirs))
    if "codex" in agents:
        streams.append(_codex_candidates(cwd, dirs))
    yield from heapq.merge(*streams, key=lambda c: c.modified_at, reverse=True)


def _claude_candidates(cwd: Path | str | None, dirs: SessionDirs) -> Iterator[_Candidate]:
    """Finished Claude Code sessions, newest-first.

    Finished-session detection is the parsers' job: sessions owned by a
    live Claude Code process are skipped via ``claude._live_session_ids``.
    """
    root = dirs.projects_dir or claude.PROJECTS_DIR
    live = claude._live_session_ids(dirs.claude_sessions_dir or claude.SESSIONS_DIR)
    if cwd is not None:
        project_dirs = [root / _claude_project_name(Path(cwd).resolve())]
    elif root.is_dir():
        project_dirs = sorted(entry for entry in root.iterdir() if entry.is_dir())
    else:
        project_dirs = []

    entries: list[tuple[float, Path, str]] = []
    for project in project_dirs:
        for path in project.glob("*.jsonl"):
            if path.is_file() and path.stem not in live:
                entries.append((path.stat().st_mtime, path, project.name))
    entries.sort(key=lambda entry: entry[0], reverse=True)
    for mtime, path, project_name in entries:
        yield _Candidate(
            agent="claude",
            path=path,
            session_id=path.stem,
            modified_at=datetime.fromtimestamp(mtime),
            project_hint=project_name,
        )


def _codex_candidates(cwd: Path | str | None, dirs: SessionDirs) -> Iterator[_Candidate]:
    """Finished Codex rollout sessions, newest-first, optionally restricted
    to one working directory."""
    target = str(Path(cwd).resolve()) if cwd is not None else None
    for session in codex.finished_sessions(sessions_dir=dirs.codex_sessions_dir):
        if target is not None and session.cwd != target:
            continue
        yield _Candidate(
            agent="codex",
            path=session.path,
            session_id=session.session_id,
            modified_at=session.modified_at,
            cwd=session.cwd,
        )


def _promote(candidate: _Candidate) -> SessionInfo:
    """Parse the candidate's session file and fill in its list row."""
    session: ParsedSession = _PARSERS[candidate.agent](candidate.path)
    cwd = session.cwd or candidate.cwd
    return SessionInfo(
        agent=candidate.agent,
        path=candidate.path,
        session_id=session.session_id or candidate.session_id,
        project=_project_label(cwd, candidate.project_hint),
        cwd=cwd,
        started_at=session.started_at,
        ended_at=session.ended_at,
        turns=len(session.turns),
        modified_at=candidate.modified_at,
    )


def _match_score(candidate: _Candidate, ref: str, ref_path: Path | None) -> int:
    if ref_path is not None and candidate.path == ref_path:
        return _PATH_MATCH
    if (ref.endswith(".jsonl") or "/" in ref) and str(candidate.path).endswith(ref):
        return _PATH_MATCH
    if ref in (candidate.session_id, candidate.path.stem):
        return _ID_MATCH
    if candidate.session_id.startswith(ref) or candidate.path.stem.startswith(ref):
        return _PREFIX_MATCH
    return 0


def _claude_project_name(cwd: Path) -> str:
    """Claude Code stores a project's sessions under ``~/.claude/projects``
    in a directory named after the cwd with ``/`` replaced by ``-`` (see
    ``parsers.claude``)."""
    return str(cwd).replace("/", "-")


def _project_label(cwd: str | None, hint: str | None) -> str:
    if cwd:
        return Path(cwd).name or cwd
    return hint or "?"


def _check_agents(agents: Sequence[str]) -> None:
    unknown = [agent for agent in agents if agent not in _PARSERS]
    if unknown:
        raise ValueError(f"unknown agent(s): {', '.join(unknown)}")
