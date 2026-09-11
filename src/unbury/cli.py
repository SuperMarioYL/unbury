"""The ``unbury`` command line.

The whole surface is one command and three flags — zero config is the
product:

::

    unbury                       # answer card for the newest finished session
                                 # recorded for this directory
    unbury list                  # the finished sessions to choose from
    unbury --session <id|path>   # pick a specific session (ids: unbury list)
    unbury --agent claude        # only consider one agent (claude | codex)
    unbury --html                # also write unbury-answer.html with
                                 # jump-links into the full transcript

No API key, no settings file, no daemon: it only reads the session logs
Claude Code and Codex already write to disk.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from unbury import __version__, discover, extract, htmlview, render

app = typer.Typer(
    add_completion=False,
    help="One-command answer cards for finished coding agent sessions.",
)

# How much of a session id `unbury list` shows — enough to select it with
# `--session <prefix>`, short enough to keep the table on one line.
_SESSION_ID_WIDTH = 12


class Agent(StrEnum):
    """The agents with a session parser."""

    claude = "claude"
    codex = "codex"


def _version(value: bool) -> None:
    if value:
        typer.echo(f"unbury {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    session: Annotated[
        str | None,
        typer.Option(
            help="Session to unbury: a session id from `unbury list`, a unique id "
            "prefix, or a transcript path. Default: the newest finished session "
            "recorded for this directory."
        ),
    ] = None,
    agent: Annotated[
        Agent | None,
        typer.Option(help="Only consider sessions from this agent. Default: both."),
    ] = None,
    html: Annotated[
        bool,
        typer.Option(
            "--html",
            help="Also write unbury-answer.html — the card with jump-links into "
            "the full transcript.",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version, is_eager=True, help="Show version and exit."
        ),
    ] = False,
) -> None:
    """Print the answer card for a finished coding agent session."""
    if ctx.invoked_subcommand is not None:
        return
    raise typer.Exit(_card(session, agent, html))


@app.command("list")
def list_(
    agent: Annotated[
        Agent | None,
        typer.Option(help="Only list sessions from this agent. Default: both."),
    ] = None,
) -> None:
    """List the finished sessions recorded for this directory, newest first."""
    rows = discover.list_sessions(Path.cwd(), agents=_agents(agent))
    if not rows:
        _fail(f"no finished sessions found for {Path.cwd()}")
    table = Table(box=None, header_style="bold", pad_edge=False)
    table.add_column("agent", style="cyan", no_wrap=True)
    table.add_column("session", style="bold", no_wrap=True)
    table.add_column("turns", justify="right")
    table.add_column("last write", style="dim")
    for row in rows:
        table.add_row(
            row.agent,
            row.session_id[:_SESSION_ID_WIDTH],
            str(row.turns),
            _when(row.modified_at),
        )
    Console().print(table)


def _card(session: str | None, agent: Agent | None, html: bool) -> int:
    agents = _agents(agent)
    if session is not None:
        info = discover.select_session(session, agents=agents)
        if info is None:
            _fail(f"no finished session matches {session!r} — try `unbury list`")
    else:
        info = discover.latest_finished(Path.cwd(), agents=agents)
        if info is None:
            _fail(f"no finished sessions found for {Path.cwd()}")
    parsed = discover.open_session(info)
    card = extract.build_card(parsed)
    render.print_card(card)
    if html:
        out = htmlview.write_html_view(card, parsed)
        Console().print(f"linked transcript → {out}", style="dim")
    return 0


def _agents(agent: Agent | None) -> tuple[str, ...]:
    if agent is None:
        return discover.DEFAULT_AGENTS
    return (agent.value,)


def _when(moment: datetime) -> str:
    return moment.astimezone().strftime("%b %d %H:%M")


def _fail(message: str) -> None:
    Console(stderr=True).print(message, style="red")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
