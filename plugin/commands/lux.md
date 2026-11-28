---
description: "Configure Lux integration and display preference"
argument-hint: "enable [project|local] | disable [project|local] | y | n"
allowed-tools: ["Bash", "mcp__plugin_lux_lux__enablement", "mcp__plugin_lux_lux__status", "mcp__plugin_lux_lux__scene_clear_all", "mcp__plugin_lux-dev_lux__enablement", "mcp__plugin_lux-dev_lux__status", "mcp__plugin_lux-dev_lux__scene_clear_all", "mcp__lux__enablement", "mcp__lux__status", "mcp__lux__scene_clear_all"]
---

# /lux command

Configure Lux for the main checkout, including when the session started in a
subdirectory or a linked git worktree.

## Usage

- `/lux enable [project|local]` — enable repository integration
- `/lux disable [project|local]` — disable repository integration
- `/lux y` / `/lux n` — change only the personal display preference
- `/lux` — show repository integration and the display preference

## Implementation

Parse `$ARGUMENTS`. Resolve `<repo>` from the first `worktree` record in
`git worktree list --porcelain` (the main checkout; do not use the daemon's
working directory). Always pass its absolute path, safely quoted in Bash.

For `enable` or `disable`, call the `enablement` MCP tool with `repo="<repo>"`,
`action="enable"` or `action="disable"` and `scope="local"` unless the user
explicitly says `project`. An explicit `--refresh`, `--clear-opt-out`, or
`--opt-out` maps to the corresponding boolean tool parameter. Report the
result; do not commit changes for the user.

For `y` or `n`, use the CLI: only a user action changes display preference
(DES-088). It does not grant permissions or turn repo integration on.

### `y`

Run `lux display mode on --repo <repo>`. Confirm: "Lux display preference: on."

### `n`

1. Run `lux display mode off --repo <repo>`.
2. If repo integration is enabled, call `scene_clear_all` to dismiss the window.
3. Confirm: "Lux display preference: off."

### No argument or unrecognized

Call `status` with `repo="<repo>"` and report its two lines.
