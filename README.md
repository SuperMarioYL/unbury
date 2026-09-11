**English** | [简体中文](./README.zh-CN.md)

<div align="center">

<img src="assets/icons/terminal-2.svg" width="64" alt="" />

# unbury

*One-command answer cards for finished coding agent sessions.*

<img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&size=22&pause=1300&color=58A6FF&center=true&vCenter=true&width=640&lines=your+agent+fixed+the+bug%E2%80%A6;then+buried+the+answer;unbury+it+%E2%80%94+one+command%2C+zero+config" alt="typing: your agent fixed the bug, then buried the answer — unbury it, one command, zero config" />

Your coding agent just fixed the bug — then buried the answer under a thousand lines of reasoning and raw tool output. `unbury` reads the finished **Claude Code** or **Codex** session and renders a one-screen answer card with jump-links into the transcript evidence, so you stop scrolling — or paying to re-ask a question the agent already answered.

<p>
<a href="https://github.com/SuperMarioYL/unbury/actions/workflows/ci.yml"><img src="https://github.com/SuperMarioYL/unbury/actions/workflows/ci.yml/badge.svg" alt="CI status" /></a>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12+" /></a>
<a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-3fb950" alt="MIT license" /></a>
<img src="https://img.shields.io/badge/zero_config-no_API_key-2ea043" alt="zero config, no API key" />
<img src="https://img.shields.io/badge/lint-ruff-261230" alt="linted with ruff" />
</p>

</div>

## <img src="assets/icons/player-play.svg" width="22" alt="" /> Demo — the whole pitch in 22 seconds

<p align="center">
<img src="assets/demo-unbury-card.gif" width="880" alt="Terminal recording: a wall of raw session JSONL scrolls by, then unbury prints a one-screen answer card — verbatim conclusion plus evidence rows with line refs — and writes the linked HTML view" />
</p>

This is a real recording, not a mock: the tape drove the actual `unbury` binary over a real finished Claude Code session on a real project — 53 turns, 426 KB of JSONL. The recorded commands and facts live in [`docs/demo-results.json`](docs/demo-results.json); the recipe that renders the GIF is [`docs/demo.tape`](docs/demo.tape).

What you see, in order:

1. `unbury list` — the finished sessions recorded for that directory, across both agents.
2. The transcript as it exists on disk — the answer is in there, somewhere.
3. `unbury --session 82ed5a79` — one command, one screen: the conclusion, quoted verbatim, plus evidence rows (files edited, commands run, decisions made), each ending in a `:line` ref into that JSONL.
4. `unbury --html` — the same card plus `unbury-answer.html`: the full transcript with a stable anchor on every turn, and every card row deep-linked to the exact turn it came from. Click a row, land on the line.

## <img src="assets/icons/file-search.svg" width="22" alt="" /> Why

A finished coding-agent session is a strange artifact. The work is done and the conclusion exists — but it is one untyped sentence floating between tool calls, in a transcript written for the *model*, not for you. Until now your recovery options were the terminal scrollback (minutes of squinting) or re-asking the agent (duplicate tokens for an answer it already produced, and a summary that can drift from what it actually said).

unbury's place among the alternatives:

| You want… | Reach for | Why not unbury |
| --- | --- | --- |
| The *next* session to lead with the answer | prompt-rule / output-format skills | Those work at generation time; unbury cannot change what already happened |
| History compressed so the model can continue | built-in summaries (`/compact` and friends) | Aimed at the model's context budget: lossy in the dimensions a human needs, no evidence links |
| To browse a transcript interactively | transcript viewers | You still have to find the answer yourself |
| The conclusion of a finished session, with proof | **unbury** | One command, any finished Claude Code or Codex session, every claim linked to its line |

Two decisions worth stating outright:

- **Verbatim, not re-summarized.** The conclusion is the agent's final answer, extracted as-is by heuristics. No model call, no API key, works entirely offline — and no summary drift.
- **Jump-links are the product, not garnish.** A card that misstates the conclusion is worse than scrollback. That is why every row carries its `path:line`, and why `--html` turns each into a click.

## <img src="assets/icons/cpu.svg" width="22" alt="" /> How it works

One process, four stages, no network:

```
~/.claude/projects/**/*.jsonl    ~/.codex/sessions/**/*.jsonl     (logs the agents already write)
                 \                 /
              discover — the newest finished session for this directory
                              |
              parsers — claude · codex: dialect JSONL → normalized turns
                              |
              extract — conclusion + evidence → AnswerCard
                              |
      render — one-screen card        htmlview — linked transcript (anchors)
```

The core primitive is the **AnswerCard** — a typed, provenance-linked conclusion over a finished session:

```python
SessionRef { agent, path, turns }
Evidence   { kind: "file" | "command" | "decision",
             summary, ref: (path, line) }
AnswerCard { session: SessionRef,
             conclusion: str,          # final assistant answer, verbatim
             evidence: list[Evidence] } # ordered, deduped
```

Parsers normalize each agent's dialect into shared turns, so extraction and rendering never know which agent produced a session. Two dialect details worth knowing:

- **Finished, not live.** A Claude Code session counts as finished when no running process owns it (checked by pid). A Codex rollout counts as finished after its file has been quiet for five minutes. Either way, unbury never cards the session you are currently in.
- **Codex hides its edits.** Current Codex sessions record file edits only as JS strings inside `exec` tool-call inputs (`tools.apply_patch('…')`); there are no structured apply_patch calls to read. The codex parser decodes those string literals to recover file-edit evidence.

## <img src="assets/icons/bolt.svg" width="22" alt="" /> Quickstart

Under a minute, nothing to configure:

```bash
uv tool install git+https://github.com/SuperMarioYL/unbury   # or: pipx install git+https://github.com/SuperMarioYL/unbury
```

Then, in the directory where you ran the agent:

```bash
unbury          # the answer card for its newest finished session
unbury --html   # same card, plus unbury-answer.html with jump-links
```

No API key, no settings file, no daemon — unbury only reads the session logs Claude Code (`~/.claude/projects/`) and Codex (`~/.codex/sessions/`) already write to disk.

To hack on it instead:

```bash
git clone https://github.com/SuperMarioYL/unbury && cd unbury
uv tool install .        # or: pip install -e .
pytest                   # parser/extraction/view suites, synthetic fixtures
```

## <img src="assets/icons/terminal-2.svg" width="22" alt="" /> Usage

The entire tuning surface is one command and three flags:

```bash
unbury                        # answer card: newest finished session in this directory
unbury list                   # the finished sessions recorded for this directory
unbury --session 82ed5a79     # pick one: session id (see list), unique prefix, or transcript path
unbury --agent claude         # only claude | codex; default: both
unbury --html                 # also write unbury-answer.html (linked transcript view)
```

`--session` reaches across directories, so the backlog of sessions you finished weeks ago is still one prefix away — run `unbury list` inside the project to see what is there. That is the whole interface; anything harder belongs in an issue, not a config file.

## <img src="assets/icons/robot.svg" width="22" alt="" /> Supported agents

| Agent | Sessions read from | Finished means | Notes |
| --- | --- | --- | --- |
| Claude Code | `~/.claude/projects/<project>/<id>.jsonl` | no live process owns it | session titles, tool calls, human-vs-injected message filtering |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` | file quiet ≥ 5 min, not a subagent thread | file edits recovered from `apply_patch` strings inside `exec` inputs |

More agents ride the same seam: a parser is one module that turns a dialect JSONL file into `unbury.parsers`' normalized turns (`parse_session(path) -> ParsedSession`). Discovery, extraction, and both renderers stay agent-agnostic.

## <img src="assets/icons/list-check.svg" width="22" alt="" /> Limitations

- Extraction is heuristic, not model-backed — that is what keeps unbury zero-config and offline, and why the conclusion is quoted verbatim rather than rewritten.
- Agent log formats are undocumented and change without notice. Parsers are fixture-tested per dialect, and unparseable lines are counted and skipped, never fatal.
- The card shows the rows that fit and says how many more exist; the full evidence table is always in the HTML view.

## <img src="assets/icons/map.svg" width="22" alt="" /> Roadmap

- **More parsers** — Astra, Gemini CLI, Cursor — each a small module over the parser interface, with a fixture format contributors can record from their own sessions.
- **A parser contribution guide** — the recorded-fixture pattern the test suite uses, written down for new agents.
- **Explicitly not planned:** LLM-backed summarization. Zero config — no key, offline, verbatim — is the product.

## <img src="assets/icons/scale.svg" width="22" alt="" /> License

[MIT](./LICENSE) © 2026 SuperMarioYL. Section icons are from [Tabler Icons](https://tabler.io/icons) (MIT).

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
