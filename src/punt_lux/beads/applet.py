"""The Beads applet: one program, one session, one entry in the Lux menu.

``lux-beads`` is started by the plugin's session-start hook and runs for the life
of that Claude Code session. It exists because luxd cannot do this itself: launchd
starts luxd with no ``PATH``, no repository working directory, and no repository
credentials, while the session has all three. So the session's own program owns
the entry, loads the issues from the session's shell, and pushes the board.

What it is assembled from is the same for any applet — a claim on the session, a
leg to serve it on, and a watch that ends it — so the living of that life belongs
to :class:`~punt_lux.applets.program.AppletProgram`. What is Beads' own is the
service the leg carries.
"""

from __future__ import annotations

import typer

from punt_lux.beads.launch import BeadsApplet

__all__ = ["BeadsApplet", "app"]

app = typer.Typer(
    name="lux-beads",
    help="The Beads applet: this session's board, one click away.",
    add_completion=False,
)


app.command()(BeadsApplet.main)


if __name__ == "__main__":
    app()
