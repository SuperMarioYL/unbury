"""Extraction, card rendering, and linked-view tests.

Milestone coverage: m1 (claude parse → extract → render), m2 (htmlview
anchors), m3 (codex extraction — the parser side lives in test_parsers.py),
plus an end-to-end pass over the bundled example session.
"""

from __future__ import annotations

import re
from pathlib import Path

from rich.console import Console

from unbury import extract, htmlview, render
from unbury.model import AnswerCard, Evidence, ParsedSession, SessionRef
from unbury.parsers import Turn, claude, codex

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_FIXTURE = FIXTURES / "claude-session.jsonl"
CODEX_FIXTURE = FIXTURES / "codex-session.jsonl"
EXAMPLE_SESSION = Path(__file__).parent.parent / "examples" / "demo-session.jsonl"


def claude_card() -> AnswerCard:
    return extract.build_card(claude.parse_session(CLAUDE_FIXTURE))


# --- m1: conclusion and evidence extraction ------------------------------------


def test_conclusion_is_final_assistant_text_verbatim() -> None:
    card = claude_card()

    assert card.conclusion.startswith("Fixed. The cache now restores in 18 seconds")
    assert "Verified with `act -j test`" in card.conclusion
    # Verbatim means the whole final answer, with its transcript location.
    assert card.conclusion_ref == (CLAUDE_FIXTURE, 16)


def test_evidence_covers_files_commands_and_decisions() -> None:
    card = claude_card()

    rows = [(row.kind, row.summary, row.ref[1]) for row in card.evidence]
    assert rows == [
        ("command", "git log --oneline -3 -- .github/workflows/ci.yml", 4),
        ("file", "edit .github/workflows/ci.yml (×2)", 6),
        ("decision", "Root cause", 8),
        ("file", "write scripts/warm_cache.py", 13),
        ("command", "act -j test 2>&1 | tail -5", 14),
    ]
    assert all(row.ref[0] == CLAUDE_FIXTURE for row in card.evidence)


def test_evidence_dedupes_repeated_files_and_commands() -> None:
    card = claude_card()

    file_rows = [row for row in card.evidence if row.kind == "file"]
    command_rows = [row for row in card.evidence if row.kind == "command"]

    # ci.yml was edited twice (lines 6 and 8) but appears once, with a count;
    # the identical `act -j test` on lines 14 and 15 collapses to one row.
    assert [row.summary for row in file_rows] == [
        "edit .github/workflows/ci.yml (×2)",
        "write scripts/warm_cache.py",
    ]
    assert sorted(row.summary for row in command_rows) == [
        "act -j test 2>&1 | tail -5",
        "git log --oneline -3 -- .github/workflows/ci.yml",
    ]


def test_decisions_skip_process_narration() -> None:
    """Short narration ("Found it — …") is not a finding; structured
    mid-session texts are."""
    card = claude_card()

    decisions = [row for row in card.evidence if row.kind == "decision"]
    assert [(row.summary, row.ref[1]) for row in decisions] == [("Root cause", 8)]
    assert "Found it" not in " ".join(row.summary for row in card.evidence)


def test_file_summaries_are_relative_to_session_cwd() -> None:
    card = claude_card()

    file_rows = [row for row in card.evidence if row.kind == "file"]
    ci_row = next(row for row in file_rows if "ci.yml" in row.summary)
    assert ci_row.summary.startswith("edit .github/workflows/ci.yml")
    assert all("/home/dev/project" not in row.summary for row in file_rows)


def test_session_ref_carries_title_and_span() -> None:
    session = claude.parse_session(CLAUDE_FIXTURE)
    card = extract.build_card(session)

    assert isinstance(card.session, SessionRef)
    assert card.session.agent == "claude"
    assert card.session.title == "Fix the CI cache restore"
    assert card.session.turns == len(session.turns)
    assert card.session.cwd == "/home/dev/project"


def test_codex_card_extracts_same_shape() -> None:
    """The card is agent-agnostic: a codex session yields the same shape."""
    card = extract.build_card(codex.parse_session(CODEX_FIXTURE))

    assert card.session.agent == "codex"
    assert card.conclusion.startswith("Done — the integration test now retries")
    assert card.conclusion_ref == (CODEX_FIXTURE, 13)
    assert [(row.kind, row.ref[1]) for row in card.evidence] == [
        ("command", 6), ("file", 7), ("file", 8), ("command", 11), ("file", 12),
    ]


def test_empty_session_yields_empty_card(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text('{"type": "user", "message": {"role": "user", "content": "hi"}}\n',
                    encoding="utf-8")

    card = extract.build_card(claude.parse_session(path))
    assert card.conclusion == ""
    assert card.conclusion_ref is None
    assert card.evidence == []


# --- m1: terminal card rendering ------------------------------------------------


def test_print_card_shows_header_conclusion_and_evidence() -> None:
    console = Console(record=True, width=96, height=44)
    render.print_card(claude_card(), console)
    text = console.export_text()

    assert "Fix the CI cache restore" in text
    assert "Fixed. The cache now restores in 18 seconds" in text
    assert "evidence" in text
    assert ".github/workflows/ci.yml" in text
    # Transcript refs are line numbers into the session file.
    assert ":6" in text and ":16" in text


def test_print_card_survives_tiny_terminal() -> None:
    console = Console(record=True, width=60, height=10)
    render.print_card(claude_card(), console)
    assert console.export_text().strip()  # renders something without raising


# --- m2: linked transcript view ---------------------------------------------------


def test_html_view_anchors_every_card_row() -> None:
    session = claude.parse_session(CLAUDE_FIXTURE)
    card = extract.build_card(session)
    document = htmlview.render_html(card, session)

    anchors = set(re.findall(r'id="L(\d+)"', document))
    linked = set(re.findall(r'href="#L(\d+)"', document))
    assert linked <= anchors, f"dangling links: {sorted(linked - anchors)}"

    # The conclusion and every evidence row deep-link to their turn.
    assert f'href="#L{card.conclusion_ref[1]}"' in document
    for row in card.evidence:
        assert f'href="#L{row.ref[1]}"' in document
    # Every turn in the transcript keeps its own stable anchor.
    assert {str(turn.line) for turn in session.turns} <= anchors


def test_write_html_view_writes_default_filename(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = claude.parse_session(CLAUDE_FIXTURE)
    card = extract.build_card(session)

    out = htmlview.write_html_view(card, session)
    assert out.name == "unbury-answer.html"
    written = tmp_path / "unbury-answer.html"
    assert written.is_file()
    assert "unbury answer card" in written.read_text(encoding="utf-8")


def test_html_view_is_self_contained_and_escapes_content() -> None:
    nasty = "done <script>alert(1)</script> & done"
    session = ParsedSession(
        path=Path("s.jsonl"), agent="claude",
        turns=[Turn(role="assistant", line=3, text=nasty)],
    )
    card = AnswerCard(
        session=SessionRef(agent="claude", path=Path("s.jsonl"), turns=1),
        conclusion=nasty,
        conclusion_ref=(Path("s.jsonl"), 3),
        evidence=[Evidence("command", "sh -c 'x && <b>y</b>'", (Path("s.jsonl"), 3))],
    )

    document = htmlview.render_html(card, session)
    # Hostile markup in the transcript is escaped, never executed.
    assert "<script" not in document
    assert "&lt;script&gt;" in document
    # No JavaScript and no external resources.
    assert not re.findall(r"<script", document)
    assert not re.findall(r'(?:src|href)="https?://', document)


# --- end to end over the bundled example ------------------------------------------


def test_example_session_renders_end_to_end(tmp_path: Path) -> None:
    session = claude.parse_session(EXAMPLE_SESSION)
    card = extract.build_card(session)

    assert card.session.title == "Why is /v1/models returning 500"
    assert card.conclusion.startswith("Fixed. GET /v1/models returns 200 again")
    kinds = {row.kind for row in card.evidence}
    assert kinds == {"file", "command", "decision"}

    console = Console(record=True, width=96, height=44)
    render.print_card(card, console)
    assert "Why is /v1/models returning 500" in console.export_text()

    document = htmlview.render_html(card, session)
    anchors = set(re.findall(r'id="L(\d+)"', document))
    linked = set(re.findall(r'href="#L(\d+)"', document))
    assert linked <= anchors
