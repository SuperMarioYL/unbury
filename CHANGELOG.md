# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [0.1.0] — 2026-09-11

Initial release: one-command answer cards for finished coding agent sessions.

### m1 — answer card

- `unbury` prints a one-screen answer card for the newest finished Claude Code
  session in the current directory: the agent's final answer, extracted
  verbatim, plus evidence rows (files edited, commands run, decisions made),
  each with a `path:line` reference into the session transcript
  (`src/unbury/{parsers/claude,extract,render}.py`).

### m2 — linked evidence

- `unbury --html` writes `unbury-answer.html`: the full transcript with a
  stable `#L<line>` anchor on every turn, every card row deep-linked to the
  exact turn it came from (`src/unbury/htmlview.py`). Self-contained HTML —
  no JavaScript, no external assets.
- `unbury list` and `--session <id|prefix|path>` select sessions across both
  agents (`src/unbury/discover.py`).

### m3 — codex parser

- Finished Codex rollout sessions are auto-discovered and parsed into the same
  card (`src/unbury/parsers/codex.py`), recovering file-edit evidence from
  `tools.apply_patch('…')` strings inside `exec` tool-call inputs — current
  sessions carry no structured apply_patch calls.
- `--agent claude|codex` restricts discovery to one agent.
- Demo GIF recorded with vhs from the real CLI on a real finished session
  (`assets/demo-unbury-card.gif`, recipe in `docs/demo.tape`).

### Packaging

- Python 3.12+, `rich` + `typer`, zero configuration, MIT.
