# Lux User Guide

This guide covers details that the [README](../README.md) summarizes: how a
Claude Code session connects to Lux, how session menu entries work, and which
permission rules `lux enable` writes.

## How a Session Connects

The Lux plugin connects Claude Code directly to `luxd`, the Hub service, at
its MCP endpoint. No extra process runs per session in that path:

```json
{
  "mcpServers": {
    "lux": { "type": "http", "url": "http://127.0.0.1:8430/mcp" }
  }
}
```

`luxd` listens only on loopback (`127.0.0.1`), so only programs on the same
machine can reach it. The Hub sends scenes to the Lux window, and the window
sends clicks and value changes back to the Hub. Restarting the window does not
lose scenes, because the Hub holds them.

To configure a session by hand and check the connection, see
[Connecting to `luxd`'s MCP endpoint directly](library.md#connecting-to-luxds-mcp-endpoint-directly).

## Session Menus and Applets

The menu bar has one submenu per Claude Code session. A session's own MCP
connection cannot receive menu clicks, so menu entries belong to **applets**:
small programs that keep a persistent connection to `luxd` and handle clicks
on their entries.

`lux-beads` is the applet that ships with Lux. The plugin's session-start hook
starts one for each session, in that session's repository. It:

- registers the session's "Beads" menu entry
- loads the repository's issue board when the entry is registered, and shows
  that board immediately when the entry is clicked
- reloads the board after each click and replaces it in place, without taking
  focus
- keeps showing the last board if a reload fails, and writes the reason to its
  log
- shows "Loading issues…" only if no board has loaded yet
- checks every few seconds whether its session's process still exists, and
  exits when it does not

`luxd` refuses `callback_register` from a connection that has no persistent
listener, because that connection could never receive the click. This is why
the MCP tools a session uses cannot own menu entries. An agent can still add
its own menus with `menu_set`; those items raise one of the agent's frames or
send a `lux.menu` event that the agent reads with `topic_recv`.

## Repository Integration

Run `lux enable` in a git checkout to turn Lux on for yourself. It writes an
ignored marker and guide under `.punt-labs/local/lux/` and imports the guide in
`CLAUDE.local.md`. The repository must have the Punt Labs gitignore baseline
covering these directories, `CLAUDE.local.md`, `.claude/settings.local.json`
and sibling `.*.punt-import.lock` files.

Use `lux enable --scope project` to enable Lux for everyone and commit the
marker, guide, import, and settings in a reviewed change. Use
`lux enable --refresh` (and the appropriate scope) to update a pinned guide;
starting a session or upgrading Lux never rewrites it.

Personal `lux disable` turns off Lux in your checkout, even when it is
enabled for the project. It cannot unload the shared guide or withdraw shared
permissions. Use `lux disable --scope project --opt-out` to record a repo-wide
opt-out, and `lux enable --scope project --clear-opt-out` to undo it. Use
`lux status` or `lux doctor` to see which file decides the current state.

When integration is off, Lux hooks do not run applets and repo-bound MCP tools
are dormant apart from status and enablement. The personal display preference
is independent: `/lux y` and `/lux n` write
`.punt-labs/local/lux/display.local.md` in the main checkout. Lux reads the
old `.punt-labs/lux.md` preference if no local preference exists; enabling
copies the old value without changing the legacy file.

## Permission Rules

`lux enable` adds these rules to the checkout's `.claude/settings.local.json`,
or to `.claude/settings.json` with `--scope project`. `lux disable` removes
only the Lux entries in the matching scope.

Allowed without a prompt:

- `Bash(lux:*)`
- `mcp__plugin_lux_lux__*`
- `Skill(lux:*)`

Claude Code asks before running:

- `lux install`, `uninstall`, `enable`, `disable`, and `hook`
- `lux hub install`, `uninstall`, `start`, `stop`, `restart`, and `doctor`
- `lux display install`, `uninstall`, `start`, `stop`, `restart`, `doctor`,
  and `serve`

Each command is written as a `Bash(<command>:*)` rule, for example
`Bash(lux hub restart:*)`. A command that starts with an option, such as
`lux --version`, does not prompt. Both commands also remove `Bash(lux -*)`,
which earlier versions added.
