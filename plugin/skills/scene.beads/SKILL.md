---
name: scene.beads
description: >
  Display a beads issue board in the Lux window with filterable table and detail
  panel. Use when the user asks to "show beads", "show the board", "show issues",
  "beads board", "beads UI", "display backlog", "show my work", or wants to
  visually browse project issues. Also triggered by "issue board", "task board",
  "kanban", "backlog view", or "bd ready in lux".
allowed-tools:
  - Bash
  - mcp__plugin_lux_lux__scene_table
  - mcp__plugin_lux-dev_lux__scene_table
  - mcp__lux__scene_table
  - mcp__plugin_lux_lux__scene_show
  - mcp__plugin_lux-dev_lux__scene_show
  - mcp__lux__scene_show
  - mcp__plugin_lux_lux__session_identify
  - mcp__plugin_lux-dev_lux__session_identify
  - mcp__lux__session_identify
---

# /lux:scene.beads — Beads Issue Board

Display beads issues in a filterable list/detail table in the Lux window.

Beads belongs to this session, not to luxd: luxd runs under launchd with no
`PATH`, no repository credentials, and no repository working directory, so it
cannot run `bd`. This session has a repo shell, so it fetches the data.

The menu entry is not your job. The session's own `lux-beads` applet — the
same process serving these tools — already registered a "Beads" entry under this
session's submenu, and it services a click on that entry itself, in milliseconds,
without a turn of yours. Do not register a callback and do not poll for clicks;
just build the board when the user asks you for one.

## Step 1: Fetch the data

Run `bd list --status=open,in_progress --json` via the Bash tool to get live issue data from DoltDB. If the user asks for all issues, run `bd list --all --json` instead. If the command fails or returns empty output, tell the user: "No beads data available. Check that `bd` is configured for this project." and stop.

Parse the JSON array output. Each object has fields: `id`, `title`, `description`, `status`, `priority`, `issue_type`, `owner`, `created_at`, `updated_at`. Use these defaults for missing fields:

- `title`: `""`, `status`: `"open"`, `priority`: `4`, `issue_type`: `"task"`
- `description`, `owner`, `created_at`, `updated_at`: `""`

## Step 2: Build the table data

From the parsed issues, filter and sort:

1. **Filter**: Keep only issues where `status` is `"open"` or `"in_progress"` (default). If the user asks for all issues, skip this filter.
2. **Sort**: `in_progress` issues float to top, then by `priority` ascending (P1 first), then by `updated_at` descending (most recent first) within equal groups.

Build three parallel arrays (same length, same order):

**`rows`** — main table rows, one per issue:
`[id, title, status, "P{priority}", issue_type]`

**`detail.rows`** — detail panel fields for each issue:
`[id, status, "P{priority}", issue_type, owner_or_empty, created_at[:10], updated_at[:10]]`
Truncate `created_at` and `updated_at` to the first 10 characters (date only, e.g. `"2026-03-09"`).

**`detail.body`** — description text for each issue:
`description or "No description."`

Collect unique `status` and `issue_type` values for combo filter items.

## Step 3: Call scene_table

Call the `scene_table` MCP tool with:

- **`scene_id`**: `"beads-<project>"` where `<project>` is the current directory name (e.g. `"beads-lux"`, `"beads-quarry"`). This gives each project its own tab.
- **`title`**: `"Beads: <project>"` (e.g. `"Beads: lux"`)
- **`frame_id`**: `"beads-<project>"` — isolates the board in its own frame so it doesn't replace other content.
- **`frame_title`**: `"Beads: <project>"` — display title for the frame tab.
- **`columns`**: `["ID", "Title", "Status", "P", "Type"]`
- **`rows`**: the main table rows from Step 2
- **`filters`**:

  ```json
  [
    {"type": "search", "column": [0, 1], "hint": "Filter by ID or title..."},
    {"type": "combo", "column": 2, "items": ["All", "<status-1>", "<status-2>"], "label": "Status"},
    {"type": "combo", "column": 4, "items": ["All", "<type-1>", "<type-2>"], "label": "Type"}
  ]
  ```

  where the `"items"` arrays are `"All"` followed by the sorted unique `status` or `issue_type` values from the issues.

- **`detail`**:

  ```json
  {
    "fields": ["ID", "Status", "Priority", "Type", "Owner", "Created", "Updated"],
    "rows": detail_rows,
    "body": detail_bodies
  }
  ```

## Step 4: Tell the user

After `scene_table` returns a value starting with `ack:`, the board is live. If it returns `timeout`, tell the user the display server did not respond. Otherwise, tell the user:

- Search and filter dropdowns work instantly (no round trips)
- Click any row to see its full details in the side panel
- The result count updates automatically as filters narrow the view

## Refreshing

If the user asks to refresh, or after running any `bd` command (close, update, etc.), re-run `bd list --json` via the Bash tool and call `scene_table` again.
