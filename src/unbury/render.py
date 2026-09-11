"""One-screen answer card rendering.

The card shows the session header, the verbatim conclusion (with its
transcript reference), and the evidence trail as one line per row. When the
full trail would overflow the screen, the most useful rows are kept — all
file edits, the latest findings, the latest commands — and the footer says
how many more exist in the transcript.
"""

from __future__ import annotations

from pathlib import Path

from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from unbury.model import AnswerCard, Evidence

MAX_CARD_WIDTH = 120
CONCLUSION_MAX_LINES = 15
MAX_EVIDENCE_ROWS = 16

# Chrome lines consumed by everything that is not the conclusion text or an
# evidence row: panel borders, header, rules, note, footer, padding, plus the
# extra blank lines rich Markdown inserts around headings and code blocks.
_CHROME_LINES = 18

_KIND_TAG = {"file": "file", "command": "cmd", "decision": "dec"}
_KIND_STYLE = {"file": "yellow", "command": "cyan", "decision": "magenta"}

# When the trail overflows the screen, keep every file edit (they are few
# and carry the most weight), then the latest findings, then the latest
# commands with whatever budget remains.
_MAX_FILE_ROWS = 6
_MAX_DECISION_ROWS = 3


def print_card(card: AnswerCard, console: Console | None = None) -> None:
    """Print the answer card to the terminal."""
    if console is None:
        console = Console()
        console.width = min(console.width, MAX_CARD_WIDTH)
    console.print(_card(card, console))


def _card(card: AnswerCard, console: Console) -> RenderableType:
    return Panel(
        _card_body(card, console),
        title=Text(" unbury ", style="bold cyan"),
        title_align="left",
        border_style="bright_black",
        padding=(0, 1),
    )


def _card_body(card: AnswerCard, console: Console) -> RenderableType:
    conclusion_lines = card.conclusion.splitlines() or [""]
    shown = min(len(conclusion_lines), CONCLUSION_MAX_LINES)
    budget = max(4, min(MAX_EVIDENCE_ROWS, console.size.height - _CHROME_LINES - shown))
    rows = _select_evidence(card.evidence, budget)

    parts: list[RenderableType] = list(_header(card, console.width - 6))
    parts.append(Rule(Text("conclusion", style="bold"), style="dim"))
    parts.extend(_conclusion_block(card))
    parts.append(Rule(Text("evidence", style="bold"), style="dim"))
    parts.append(_evidence_table(rows, console.width - 6))
    parts.append(_footer(card, len(rows)))
    return Group(*parts)


def _header(card: AnswerCard, width: int) -> list[RenderableType]:
    title = Text(card.session.title or f"{card.session.agent} session", style="bold")
    meta = [card.session.agent]
    if card.session.cwd:
        meta.append(_fit(_home_shortened(card.session.cwd), 48))
    meta.append(f"{card.session.turns} turns")
    if card.session.started_at is not None and card.session.ended_at is not None:
        start, end = card.session.started_at.astimezone(), card.session.ended_at.astimezone()
        meta.append(
            start.strftime("%b %d %H:%M") + " → " + end.strftime("%b %d %H:%M")
        )
    transcript_line = _fit(_home_shortened(str(card.session.path)), width - 11)
    return [
        title,
        Text(" · ".join(meta), style="dim"),
        Text(f"transcript {transcript_line}", style="dim"),
    ]


def _conclusion_block(card: AnswerCard) -> list[RenderableType]:
    if not card.conclusion:
        return [
            Text(
                "this session ends without a narrative answer — evidence rows only",
                style="italic dim",
            )
        ]
    lines = card.conclusion.splitlines()
    if len(lines) > CONCLUSION_MAX_LINES:
        shown = "\n".join(lines[:CONCLUSION_MAX_LINES])
        note = Text(
            f"… +{len(lines) - CONCLUSION_MAX_LINES} more lines · "
            f"full answer at {_ref(card.conclusion_ref)}",
            style="dim",
        )
    else:
        shown = card.conclusion
        note = Text(f"verbatim · {_ref(card.conclusion_ref)}", style="dim")
    return [Markdown(shown), Align.right(note)]


def _evidence_table(rows: list[Evidence], width: int) -> RenderableType:
    if not rows:
        return Text("no tool evidence recorded in this session", style="italic dim")
    # Fixed column widths so every row stays on one line: rich only honors
    # overflow ellipsis reliably when a column has an explicit width.
    # 4 (tag) + 6 (":12345") + 4 (inter-column padding) leave the rest for text.
    table = Table.grid(padding=(0, 1))
    table.add_column(width=4)
    table.add_column(width=max(10, width - 14), no_wrap=True, overflow="ellipsis")
    table.add_column(width=6, justify="right", no_wrap=True)
    for row in rows:
        tag = _KIND_TAG.get(row.kind, row.kind[:4])
        style = _KIND_STYLE.get(row.kind, "white")
        table.add_row(
            Text(tag, style=style),
            Text(row.summary),
            Text(f":{row.ref[1]}", style="dim"),
        )
    return table


def _footer(card: AnswerCard, shown: int) -> RenderableType:
    bits = []
    if len(card.evidence) > shown:
        bits.append(f"+{len(card.evidence) - shown} more evidence rows in the transcript")
    bits.append("refs are line numbers into the transcript above")
    return Text(" · ".join(bits), style="dim")


def _select_evidence(evidence: list[Evidence], budget: int) -> list[Evidence]:
    if len(evidence) <= budget:
        return evidence
    files = [e for e in evidence if e.kind == "file"][-_MAX_FILE_ROWS:]
    decisions = [e for e in evidence if e.kind == "decision"][-_MAX_DECISION_ROWS:]
    commands = [e for e in evidence if e.kind == "command"]
    picked = files + decisions
    remaining = max(0, budget - len(picked))
    if remaining:
        picked += commands[-remaining:]
    picked.sort(key=lambda e: e.ref[1])
    return picked


def _ref(ref: tuple[Path, int] | None) -> str:
    if ref is None:
        return "?"
    return f"{ref[0].name}:{ref[1]}"


def _home_shortened(path: str) -> str:
    home = str(Path.home())
    return path.replace(home, "~") if path.startswith(home) else path


def _fit(text: str, width: int) -> str:
    """Truncate a too-long path from the left — the tail carries the identity."""
    if len(text) <= width:
        return text
    return "…" + text[-(width - 1):]
