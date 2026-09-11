#!/usr/bin/env bash
# Stage the demo environment for docs/demo.tape. Source it — it cds and
# exports into the recording shell.
#
# By default the tape renders against the bundled synthetic example sessions
# (examples/demo-session*.jsonl), so it reproduces on any machine, including
# a fresh CI runner. To record against your own finished sessions instead,
# point UNBURY_DEMO_PROJECT at a project directory that has them:
#
#     UNBURY_DEMO_PROJECT=~/code/myproject vhs docs/demo.tape
#
# In that mode the transcript, the listing and the card in the GIF are your
# real sessions.

# The session the tape selects with `unbury --session`.
DEMO_SESSION_REF=82ed5a79

if [ -n "$UNBURY_DEMO_PROJECT" ]; then
    cd "$UNBURY_DEMO_PROJECT" || exit 1
    export UNBURY_TRANSCRIPT="$(
        ls -t "$HOME"/.claude/projects/*/"$DEMO_SESSION_REF"*.jsonl 2>/dev/null | head -1
    )"
    if [ -z "$UNBURY_TRANSCRIPT" ]; then
        echo "demo-env: no transcript for session $DEMO_SESSION_REF under ~/.claude/projects" >&2
        exit 1
    fi
else
    # Stage the synthetic example sessions into a throwaway HOME.
    repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    demo_home="$(mktemp -d /tmp/unbury-demo-home.XXXXXX)"
    mkdir -p "$demo_home/.claude/projects/-tmp-unbury-demo" /tmp/unbury-demo
    cp "$repo_root/examples/demo-session.jsonl" \
       "$demo_home/.claude/projects/-tmp-unbury-demo/82ed5a79-0000-4000-8000-000000000001.jsonl"
    mkdir -p "$demo_home/.codex/sessions/2026/09/11"
    cp "$repo_root/examples/demo-session-codex.jsonl" \
       "$demo_home/.codex/sessions/2026/09/11/rollout-2026-09-11T07-00-00-01a0demo0.jsonl"
    export HOME="$demo_home"
    export UNBURY_TRANSCRIPT="$demo_home/.claude/projects/-tmp-unbury-demo/82ed5a79-0000-4000-8000-000000000001.jsonl"
    cd /tmp/unbury-demo || exit 1
fi

# A quiet, reproducible prompt for the recording (vhs's Wait expects a
# prompt ending in ">").
export PS1='\W > '
clear
