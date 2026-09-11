"""Parser and discovery tests over synthetic session fixtures.

The fixtures under ``tests/fixtures/`` are small synthetic transcripts that
mirror each agent's real JSONL dialect — including the noise records real
sessions carry — so the tests never depend on this machine's ``~/.claude`` or
``~/.codex`` trees. One opt-in smoke test at the bottom exercises the real
local sessions when they exist.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from unbury import discover
from unbury.parsers import claude, codex

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_FIXTURE = FIXTURES / "claude-session.jsonl"
CODEX_FIXTURE = FIXTURES / "codex-session.jsonl"


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    return path


def touch(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


# --- Claude Code dialect ------------------------------------------------------


def test_claude_parses_turns_and_skips_noise() -> None:
    session = claude.parse_session(CLAUDE_FIXTURE)

    assert session.agent == "claude"
    assert session.title == "Fix the CI cache restore"
    assert session.session_id == "aaa11111-2222-3333-4444-555555555555"
    assert session.cwd == "/home/dev/project"
    assert session.unparsed_lines == 0

    # Only the human/assistant mainline survives; tool results, subagent
    # sidechains, meta records, IDE events, command echoes and API error
    # placeholders are all dropped.
    assert [turn.line for turn in session.turns] == [3, 4, 6, 8, 13, 14, 15, 16]
    assert [turn.role for turn in session.turns] == [
        "user", "assistant", "assistant", "assistant",
        "assistant", "assistant", "assistant", "assistant",
    ]

    bash = session.turns[1].tool_calls[0]
    assert bash.name == "Bash"
    assert bash.input["command"] == "git log --oneline -3 -- .github/workflows/ci.yml"
    assert bash.line == 4

    # Thinking blocks never leak into turn text.
    assert "inspect the workflow" not in session.turns[1].text


def test_claude_counts_unparseable_lines(tmp_path: Path) -> None:
    good = json.dumps({"type": "user", "origin": {"kind": "human"},
                       "message": {"role": "user", "content": "hi"}})
    path = tmp_path / "broken.jsonl"
    path.write_text(f"{good}\nnot json at all\n[]\n", encoding="utf-8")

    session = claude.parse_session(path)
    assert session.unparsed_lines == 2
    assert [turn.text for turn in session.turns] == ["hi"]


def test_claude_latest_finished_skips_live_sessions(tmp_path: Path) -> None:
    cwd = tmp_path / "work" / "proj"
    cwd.mkdir(parents=True)
    projects = tmp_path / "projects"
    project_dir = projects / str(cwd.resolve()).replace("/", "-")
    project_dir.mkdir(parents=True)
    live = write_jsonl(project_dir / "aaa-live.jsonl",
                       [{"type": "user", "message": {"role": "user", "content": "live"}}])
    done = write_jsonl(project_dir / "bbb-done.jsonl",
                       [{"type": "user", "message": {"role": "user", "content": "done"}}])
    touch(live, time.time() + 10)
    touch(done, time.time() - 10)

    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    proc = subprocess.Popen(["sleep", "30"])
    try:
        (sessions_dir / "state.json").write_text(
            json.dumps({"pid": proc.pid, "sessionId": "aaa-live"}), encoding="utf-8"
        )
        found = claude.latest_finished_session(
            cwd, projects_dir=projects, sessions_dir=sessions_dir
        )
        assert found == done
    finally:
        proc.kill()
        proc.wait()


# --- Codex dialect ------------------------------------------------------------


def test_codex_recovers_file_edits_from_exec_scripts() -> None:
    """The m3 dialect reality: file edits exist only inside the JS string
    passed to tools.apply_patch in exec tool-call inputs."""
    session = codex.parse_session(CODEX_FIXTURE)

    assert session.agent == "codex"
    assert session.session_id == "0199f7c0-feed-4000-8000-000000000001"
    assert session.cwd == "/home/dev/project"
    assert session.unparsed_lines == 0

    pytest_call = session.turns[1].tool_calls[0]
    assert (pytest_call.name, pytest_call.input["command"]) == (
        "Bash", "pytest -q tests/test_integration.py",
    )

    add = session.turns[2].tool_calls[0]
    assert (add.name, add.input) == ("Write", {"file_path": "scripts/retry.sh"})

    update = session.turns[3].tool_calls[0]
    assert (update.name, update.input) == ("Edit", {"file_path": "pyproject.toml"})


def test_codex_legacy_function_calls() -> None:
    session = codex.parse_session(CODEX_FIXTURE)

    legacy_command = session.turns[4].tool_calls[0]
    assert (legacy_command.name, legacy_command.input["command"]) == (
        "Bash", "ruff check src/",
    )
    legacy_patch = session.turns[5].tool_calls[0]
    assert (legacy_patch.name, legacy_patch.input) == (
        "Edit", {"file_path": "scripts/old_retry.py"},
    )


def test_codex_drops_system_records() -> None:
    session = codex.parse_session(CODEX_FIXTURE)

    texts = [turn.text for turn in session.turns if turn.text]
    assert "You are Codex, running as a coding agent." not in texts  # developer role
    assert all("<environment_context>" not in text for text in texts)
    assert all("consider retry policies" not in text for text in texts)  # reasoning
    assert "Working on it." not in texts  # event_msg, not a response item
    assert [turn.line for turn in session.turns] == [2, 6, 7, 8, 11, 12, 13]


def test_codex_finished_sessions_grace_and_subagents(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    now = time.time()
    header = {"type": "session_meta", "payload": {
        "session_id": "thread-ok", "cwd": "/home/dev/project",
        "timestamp": "2026-09-11T08:00:00.000Z"}}
    subagent = {"type": "session_meta", "payload": {
        "session_id": "thread-sub", "cwd": "/home/dev/project", "thread_source": "subagent"}}

    quiet = write_jsonl(
        root / "2026/09/11/rollout-2026-09-11T08-00-00-thread-ok.jsonl", [header])
    fresh = write_jsonl(
        root / "2026/09/11/rollout-2026-09-11T09-00-00-thread-fresh.jsonl", [header])
    sub = write_jsonl(
        root / "2026/09/11/rollout-2026-09-11T08-30-00-thread-sub.jsonl", [subagent])
    touch(quiet, now - 3600)
    touch(fresh, now - 10)
    touch(sub, now - 3600)

    found = list(codex.finished_sessions(sessions_dir=root))
    assert [session.session_id for session in found] == ["thread-ok"]
    assert found[0].cwd == "/home/dev/project"


def test_codex_session_id_falls_back_to_filename(tmp_path: Path) -> None:
    path = tmp_path / "rollout-2026-09-11T08-00-00-0199dead-beef-4000-8000-000000000002_cont.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    session = codex.parse_session(path)
    # Continuation suffixes after the thread id are dropped.
    assert session.session_id == "0199dead-beef-4000-8000-000000000002"


# --- Cross-agent discovery -----------------------------------------------------


def stage_discovery_tree(tmp_path: Path) -> tuple[discover.SessionDirs, Path, Path]:
    """A claude project dir plus a codex rollout tree with known mtimes.
    Returns the dirs and the two project cwds."""
    proj_a = tmp_path / "work" / "proj-a"
    proj_b = tmp_path / "work" / "proj-b"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)

    projects = tmp_path / "projects"
    claude_dir = projects / str(proj_a.resolve()).replace("/", "-")
    write_jsonl(claude_dir / "claude-old.jsonl",
                [{"type": "user", "message": {"role": "user", "content": "old"}}])
    write_jsonl(claude_dir / "claude-new.jsonl",
                [{"type": "user", "message": {"role": "user", "content": "new"}}])

    def rollout_records() -> list[dict]:
        return [
            {"type": "session_meta", "payload": {"cwd": str(proj_b.resolve())}},
            {"type": "response_item", "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "do the thing"}]}},
        ]

    codex_root = tmp_path / "codex"
    codex_mid = write_jsonl(
        codex_root / "2026/09/10/rollout-2026-09-10T10-00-00-codex-mid.jsonl", rollout_records())
    codex_top = write_jsonl(
        codex_root / "2026/09/11/rollout-2026-09-11T11-00-00-codex-top.jsonl", rollout_records())

    base = time.time() - 10_000
    touch(claude_dir / "claude-old.jsonl", base)
    touch(claude_dir / "claude-new.jsonl", base + 500)
    touch(codex_mid, base + 100)
    touch(codex_top, base + 900)
    dirs = discover.SessionDirs(projects_dir=projects, claude_sessions_dir=tmp_path / "none",
                                codex_sessions_dir=codex_root)
    return dirs, proj_a, proj_b


def test_list_sessions_newest_first_across_agents(tmp_path: Path) -> None:
    dirs, _, _ = stage_discovery_tree(tmp_path)
    rows = discover.list_sessions(dirs=dirs)

    assert [(row.agent, row.session_id) for row in rows] == [
        ("codex", "codex-top"),
        ("claude", "claude-new"),
        ("codex", "codex-mid"),
        ("claude", "claude-old"),
    ]
    assert all(row.turns == 1 for row in rows)


def test_list_sessions_filter_by_cwd_and_agent(tmp_path: Path) -> None:
    dirs, proj_a, proj_b = stage_discovery_tree(tmp_path)

    claude_only = discover.list_sessions(proj_a, agents=["claude"], dirs=dirs)
    assert [row.session_id for row in claude_only] == ["claude-new", "claude-old"]

    # The codex rollout with a different cwd is filtered out.
    assert discover.list_sessions(proj_a, dirs=dirs)[0].agent == "claude"
    assert [row.session_id for row in discover.list_sessions(proj_b, dirs=dirs)] == [
        "codex-top", "codex-mid",
    ]


def test_latest_finished_prefers_newest(tmp_path: Path) -> None:
    dirs, _, _ = stage_discovery_tree(tmp_path)
    latest = discover.latest_finished(dirs=dirs)
    assert (latest.agent, latest.session_id) == ("codex", "codex-top")


def test_select_session_matches_id_prefix_and_path(tmp_path: Path) -> None:
    dirs, _, _ = stage_discovery_tree(tmp_path)

    assert discover.select_session("claude-new", dirs=dirs).session_id == "claude-new"
    assert discover.select_session("codex-t", dirs=dirs).session_id == "codex-top"
    top_path = dirs.codex_sessions_dir / "2026/09/11/rollout-2026-09-11T11-00-00-codex-top.jsonl"
    assert discover.select_session(str(top_path), dirs=dirs).session_id == "codex-top"
    assert discover.select_session("no-such-session", dirs=dirs) is None


def test_discovery_rejects_unknown_agent() -> None:
    try:
        discover.list_sessions(agents=["astra"])
    except ValueError as error:
        assert "astra" in str(error)
    else:
        raise AssertionError("expected ValueError for unknown agent")


# --- Opt-in: this machine's real sessions --------------------------------------


@pytest.mark.skipif(
    not claude.PROJECTS_DIR.is_dir(), reason="no local Claude Code sessions on this machine"
)
def test_real_local_sessions_smoke() -> None:
    """Parses the newest finished real session end to end, asserting only
    what must hold for any session (never its content)."""
    live = claude._live_session_ids(claude.SESSIONS_DIR)
    finished = sorted(
        (p for p in claude.PROJECTS_DIR.glob("*/*.jsonl") if p.stem not in live),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not finished:
        pytest.skip("every local session is currently live")

    session = claude.parse_session(finished[0])
    assert session.agent == "claude"
    assert session.path == finished[0]
