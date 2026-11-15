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

## Permission Rules

`lux enable` writes these rules into the project's `.claude/settings.json`,
and `lux disable` removes them.

Allowed without a prompt:

- `Bash(lux:*)`
- `mcp__plugin_lux_lux__*`
- `Skill(lux:*)`

Claude Code asks before running:

- `Bash(lux -*)`
- `lux install`, `uninstall`, `enable`, `disable`, and `hook`
- `lux hub install`, `uninstall`, `start`, `stop`, `restart`, and `doctor`
- `lux display install`, `uninstall`, `start`, `stop`, `restart`, `doctor`,
  `serve`, and `mode`

Each command in the last three items is written as a `Bash(<command>:*)`
rule, for example `Bash(lux hub restart:*)`.
