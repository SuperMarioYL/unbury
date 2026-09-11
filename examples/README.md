# Example sessions

Two small synthetic sessions — one Claude Code, one Codex — let you try
unbury without any agent history of your own. They are the same sessions
`docs/demo.tape` stages when it renders on a machine (like CI) with no real
`~/.claude` or `~/.codex` directories.

Using unbury on a real machine is three lines:

```bash
cd your-project        # where you ran the agent session
unbury                 # the answer card for its newest finished session
unbury --html          # same card, plus jump-links into the full transcript
```

To reproduce the card without installing anything, stage the examples into
a throwaway HOME:

```bash
demo=$(mktemp -d)
mkdir -p "$demo/.claude/projects/-tmp-unbury-demo" /tmp/unbury-demo
cp examples/demo-session.jsonl \
   "$demo/.claude/projects/-tmp-unbury-demo/82ed5a79-0000-4000-8000-000000000001.jsonl"
cd /tmp/unbury-demo && HOME="$demo" unbury --session 82ed5a79
```

- `demo-session.jsonl` — Claude Code dialect: a debugging session that finds
  a duplicated model id breaking `/v1/models`, fixes the loader, adds a
  regression test, and ends with a structured summary.
- `demo-session-codex.jsonl` — Codex dialect: a small release-chore session.
  File edits live inside `tools.apply_patch(...)` strings in exec tool-call
  inputs, the way current Codex sessions record them.
