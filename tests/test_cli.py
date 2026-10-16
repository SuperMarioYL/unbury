"""CLI contract tests: the ``unbury`` command surface in-process.

The CI smoke only exercises the empty-runner paths; these tests cover the real
surface — default selection, ``--session`` across directories, ``list`` with
``--agent`` filtering, ``--html`` output, and the failure contracts — over
synthetic fixture trees with the parser root constants pointed at them via
monkeypatch, so nothing here touches this machine's ``~/.claude`` or
``~/.codex``.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from unbury import __version__
from unbury.cli import app
from unbury.parsers import claude, codex

runner = CliRunner()


def write_jsonl(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
    )
    return path


def touch(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """One finished claude session recorded for proj-a and one codex session
    recorded for proj-b, with the parser roots redirected to the tree."""
    proj_a = tmp_path / "work" / "proj-a"
    proj_b = tmp_path / "work" / "proj-b"
    proj_a.mkdir(parents=True)
    proj_b.mkdir(parents=True)

    projects = tmp_path / "projects"
    claude_path = write_jsonl(
        projects / str(proj_a.resolve()).replace("/", "-") / "claude-only.jsonl",
        [
            {"type": "custom-title", "customTitle": "Fix the retry loop"},
            {
                "type": "user",
                "sessionId": "82ed5a79-0000-4000-8000-000000000001",
                "cwd": str(proj_a),
                "origin": {"kind": "human"},
                "message": {"role": "user", "content": "the retry loop never stops"},
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Edit",
                            "input": {"file_path": str(proj_a / "app.py")},
                            "id": "t1",
                        }
                    ],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Fixed. The loop now backs off exponentially.",
                        }
                    ],
                },
            },
        ],
    )

    codex_root = tmp_path / "codex"
    codex_path = write_jsonl(
        codex_root
        / "2026/09/11"
        / "rollout-2026-09-11T11-00-00-0199f7c0-feed-4000-8000-000000000002.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {
                    "session_id": "codex-only",
                    "cwd": str(proj_b),
                    "timestamp": "2026-09-11T08:00:00.000Z",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "do the thing"}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "input": "tools.exec_command({cmd: 'pytest -q'})",
                    "id": "c1",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "Done — the tests pass."}
                    ],
                },
            },
        ],
    )

    old = time.time() - 3600  # codex finished-sessions quiescence grace
    touch(claude_path, old)
    touch(codex_path, old)

    monkeypatch.setattr(claude, "PROJECTS_DIR", projects)
    monkeypatch.setattr(claude, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(codex, "SESSIONS_DIR", codex_root)
    return {"proj_a": proj_a, "proj_b": proj_b, "claude": claude_path}


def test_version_flag_prints_the_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"unbury {__version__}"


def test_default_card_for_this_directorys_newest_session(
    staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(staged["proj_a"])

    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Fix the retry loop" in result.output
    assert "Fixed. The loop now backs off exponentially." in result.output


def test_session_flag_reaches_across_directories(
    staged: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = runner.invoke(app, ["--session", "codex-on"])

    assert result.exit_code == 0
    assert "Done — the tests pass." in result.output


def test_html_flag_writes_the_linked_view(
    staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(staged["proj_a"])

    result = runner.invoke(app, ["--html"])

    assert result.exit_code == 0
    written = staged["proj_a"] / "unbury-answer.html"
    assert written.is_file()
    document = written.read_text(encoding="utf-8")
    assert "unbury answer card" in document
    assert 'id="L' in document


def test_list_shows_this_directorys_sessions(
    staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(staged["proj_b"])

    result = runner.invoke(app, ["list"])

    assert result.exit_code == 0
    assert "codex" in result.output
    assert "codex-only" in result.output


def test_list_agent_filter_narrows_discovery(
    staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(staged["proj_b"])

    claude_only = runner.invoke(app, ["list", "--agent", "claude"])

    # proj-b has no recorded claude sessions: clean failure, not a traceback.
    assert claude_only.exit_code == 1
    assert "no finished sessions found" in claude_only.output


def test_unknown_session_reference_fails_cleanly(
    staged: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(staged["proj_a"])

    result = runner.invoke(app, ["--session", "no-such-session"])

    assert result.exit_code == 1
    assert "no finished session matches" in result.output
    assert "Traceback" not in result.output


def test_unknown_agent_is_a_usage_error(staged: dict[str, Path]) -> None:
    result = runner.invoke(app, ["--agent", "astra"])

    assert result.exit_code != 0
    assert "Traceback" not in result.output
