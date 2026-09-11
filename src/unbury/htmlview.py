"""Linked transcript view: what ``unbury --html`` writes.

The output is a single self-contained ``unbury-answer.html``: the answer card
on top (session header, verbatim conclusion, evidence rows) and the full
session transcript below. Every turn carries a stable ``#L<line>`` anchor —
its 1-based line in the session JSONL, the same number the terminal card
prints — and every card row (the conclusion and each evidence row) deep-links
to the exact turn it came from. The CSS ``:target`` rule scrolls to the turn
and highlights it, so the links work in any browser with no JavaScript, no
network, and no external assets.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from unbury.model import AnswerCard, Evidence, ParsedSession

DEFAULT_FILENAME = "unbury-answer.html"

# Tool inputs can embed whole files; cap what the view inline-formats so one
# giant Write payload cannot drown the transcript around it.
_MAX_TOOL_JSON_CHARS = 6000

_KIND_CLASS = {"file": "k-file", "command": "k-command", "decision": "k-decision"}

_STYLE = """
:root {
  --bg: #f6f8fa; --panel: #ffffff; --ink: #1f2328; --dim: #59636e;
  --line: #d1d9e0; --accent: #0969da; --target: #fff8c5;
  --file: #9a6700; --command: #0550ae; --decision: #8250df;
  --user-bg: #eef1f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --panel: #161b22; --ink: #e6edf3; --dim: #9198a1;
    --line: #3d444d; --accent: #4493f8; --target: #3a2d00;
    --file: #d29922; --command: #79c0ff; --decision: #d2a8ff;
    --user-bg: #1c2128;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1rem 4rem; background: var(--bg); color: var(--ink);
  font: 15px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 58rem; margin: 0 auto; }
h1 { font-size: 1.35rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 2rem 0 .5rem; color: var(--dim);
     text-transform: uppercase; letter-spacing: .06em; }
.meta { color: var(--dim); font-size: .85rem; margin: .15rem 0; }
.meta code { font-size: .8rem; }
.card { background: var(--panel); border: 1px solid var(--line);
        border-radius: 8px; padding: 1rem 1.25rem; }
.conclusion { margin: 0; white-space: pre-wrap; font: .85rem/1.5 ui-monospace,
              SFMono-Regular, Menlo, Consolas, monospace; }
.sourceline { display: block; text-align: right; font-size: .78rem;
              margin: .35rem 0 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
table.evidence { border-collapse: collapse; width: 100%; font-size: .88rem; }
table.evidence td { border-top: 1px solid var(--line); padding: .38rem .5rem;
                    vertical-align: top; }
td.kind, td.ref { white-space: nowrap; font-size: .78rem; }
td.ref { text-align: right; }
.k-file { color: var(--file); } .k-command { color: var(--command); }
.k-decision { color: var(--decision); }
.turn { background: var(--panel); border: 1px solid var(--line);
        border-radius: 8px; padding: .55rem 1rem; margin: .6rem 0;
        scroll-margin-top: 1rem; }
.turn.user { background: var(--user-bg); }
.turn:target { border-color: var(--accent); outline: 2px solid var(--accent); }
.turn header { display: flex; gap: .75rem; align-items: baseline;
               color: var(--dim); font-size: .78rem; margin-bottom: .3rem; }
.turn .role { font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
.turn .lineno { margin-left: auto; font-family: ui-monospace, Menlo, monospace; }
.turn pre.text { margin: 0; white-space: pre-wrap; font: .85rem/1.5 ui-monospace,
                 SFMono-Regular, Menlo, Consolas, monospace; }
details.tool { border-top: 1px dashed var(--line); padding: .3rem 0; font-size: .82rem; }
details.tool summary { cursor: pointer; color: var(--dim); }
details.tool summary .tool-name { color: var(--command); font-weight: 600; }
details.tool pre { margin: .35rem 0 0; white-space: pre-wrap;
                   font-size: .78rem; color: var(--dim); }
"""


def write_html_view(
    card: AnswerCard,
    session: ParsedSession,
    out: Path | str | None = None,
) -> Path:
    """Write the linked transcript view and return its path.

    ``out`` defaults to ``unbury-answer.html`` in the current directory.
    """
    path = Path(out) if out is not None else Path(DEFAULT_FILENAME)
    path.write_text(render_html(card, session), encoding="utf-8")
    return path


def render_html(card: AnswerCard, session: ParsedSession) -> str:
    """The full self-contained HTML document for a card and its transcript."""
    return _document(
        _header(card)
        + _card_section(card)
        + _transcript_section(session)
    )


def _document(body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<title>unbury — answer card</title>\n"
        f"<style>{_STYLE}</style>\n</head>\n<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def _header(card: AnswerCard) -> str:
    meta = [
        f"{html.escape(card.session.agent)} session",
        f"{card.session.turns} turns",
    ]
    if card.session.cwd:
        meta.append(html.escape(_short_home(card.session.cwd)))
    if card.session.started_at is not None and card.session.ended_at is not None:
        meta.append(
            card.session.started_at.astimezone().strftime("%b %d %H:%M")
            + " → "
            + card.session.ended_at.astimezone().strftime("%b %d %H:%M")
        )
    return (
        "<h1>unbury answer card</h1>\n"
        f'<p class="meta"><strong>{html.escape(card.session.title or "session")}</strong></p>\n'
        f'<p class="meta">{" · ".join(meta)}</p>\n'
        '<p class="meta">transcript: '
        f"<code>{html.escape(_short_home(str(card.session.path)))}</code></p>\n"
    )


def _card_section(card: AnswerCard) -> str:
    parts = ['<h2>Answer card</h2>\n<section class="card">\n']
    parts.append("<h2>conclusion</h2>\n")
    if card.conclusion:
        if card.conclusion_ref is not None:
            parts.append(_sourceline(card.conclusion_ref))
        parts.append(f'<pre class="conclusion">{html.escape(card.conclusion)}</pre>\n')
    else:
        parts.append(
            '<p class="meta">this session ends without a narrative answer '
            "— evidence rows only</p>\n"
        )
    parts.append("<h2>evidence</h2>\n")
    if card.evidence:
        parts.append('<table class="evidence">\n<tbody>\n')
        for row in card.evidence:
            parts.append(_evidence_row(row))
        parts.append("</tbody>\n</table>\n")
    else:
        parts.append('<p class="meta">no tool evidence recorded in this session</p>\n')
    parts.append("</section>\n")
    return "".join(parts)


def _evidence_row(row: Evidence) -> str:
    kind = _KIND_CLASS.get(row.kind, "")
    return (
        f'<tr><td class="kind {kind}">{html.escape(row.kind)}</td>'
        f"<td>{html.escape(row.summary)}</td>"
        f'<td class="ref"><a href="#L{row.ref[1]}">:{row.ref[1]}</a></td></tr>\n'
    )


def _sourceline(ref: tuple[Path, int]) -> str:
    name = ref[0].name
    return (
        f'<a class="sourceline" href="#L{ref[1]}">'
        f"verbatim · {html.escape(name)}:{ref[1]} → jump to turn</a>\n"
    )


def _transcript_section(session: ParsedSession) -> str:
    parts = ["<h2>Transcript</h2>\n"]
    for turn in session.turns:
        role = html.escape(turn.role)
        time = (
            turn.timestamp.astimezone().strftime("%H:%M:%S")
            if turn.timestamp is not None
            else ""
        )
        parts.append(f'<article id="L{turn.line}" class="turn {role}">\n')
        parts.append(
            f'<header><span class="role">{role}</span><span class="time">{time}</span>'
            f'<span class="lineno">line {turn.line}</span></header>\n'
        )
        if turn.text:
            parts.append(f'<pre class="text">{html.escape(turn.text)}</pre>\n')
        for call in turn.tool_calls:
            parts.append(_tool_details(call.name, call.input))
        parts.append("</article>\n")
    return "".join(parts)


def _tool_details(name: str, tool_input: dict) -> str:
    summary = _tool_summary(tool_input)
    name = html.escape(name)
    summary = html.escape(summary)
    rendered = json.dumps(tool_input, ensure_ascii=False, indent=2)
    if len(rendered) > _MAX_TOOL_JSON_CHARS:
        rendered = rendered[:_MAX_TOOL_JSON_CHARS] + "\n… truncated — full input in the transcript"
    return (
        f'<details class="tool"><summary><span class="tool-name">{name}</span>'
        f" {summary}</summary>"
        f"<pre>{html.escape(rendered)}</pre></details>\n"
    )


def _tool_summary(tool_input: dict) -> str:
    for key in ("file_path", "notebook_path", "command", "pattern", "url", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return _shorten(value, 90)
    return "tool call"


def _short_home(path: str) -> str:
    home = str(Path.home())
    return path.replace(home, "~") if path.startswith(home) else path


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
