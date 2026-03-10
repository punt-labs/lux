---
name: beads
description: >
  Display a beads issue board in the Lux window with filterable table and detail
  panel. Use when the user asks to "show beads", "show the board", "show issues",
  "beads board", "beads UI", "display backlog", "show my work", or wants to
  visually browse project issues. Also triggered by "issue board", "task board",
  "kanban", "backlog view", or "bd ready in lux".
allowed-tools:
  - Read
  - mcp__plugin_lux_lux__show_table
  - mcp__plugin_lux-dev_lux__show_table
  - mcp__lux__show_table
---

# /lux:beads — Beads Issue Board

Display beads issues in a filterable list/detail table in the Lux window.

## Step 1: Read the data

Read `.beads/issues.jsonl` using the Read tool. If the file does not exist, tell the user: "No beads database found. Run `bd init` to set up beads for this project." and stop.

Each line is a JSON object that may include: `id`, `title`, `status`, `priority`, `issue_type`, `description`, `assignee`, `owner`, `created_at`, `updated_at`. Use these defaults for missing fields:

- `title`: `""`, `status`: `"open"`, `priority`: `3`, `issue_type`: `"task"`
- `description`, `assignee`, `owner`, `created_at`, `updated_at`: `""`

## Step 2: Build the table data

From the parsed issues, filter and sort:

1. **Filter**: Keep only issues where `status` is `"open"` or `"in_progress"` (default). If the user asks for all issues, skip this filter.
2. **Sort**: Primary sort by `priority` ascending (P1 first), secondary sort by `updated_at` descending (most recent first).

Build three parallel arrays (same length, same order):

**`rows`** — main table rows, one per issue:
`[id, title, status, "P{priority}", issue_type]`

**`detail.rows`** — detail panel fields for each issue:
`[id, status, "P{priority}", issue_type, assignee_or_empty, owner_or_empty, created_at[:10], updated_at[:10]]`
Truncate `created_at` and `updated_at` to the first 10 characters (date only, e.g. `"2026-03-09"`).

**`detail.body`** — description text for each issue:
`description or "No description."`

Collect unique `status` and `issue_type` values for combo filter items.

## Step 3: Call show_table

Call the `show_table` MCP tool with:

- **`scene_id`**: `"beads-board"`
- **`title`**: `"Beads"`
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
    "fields": ["ID", "Status", "Priority", "Type", "Claimed By", "Owner", "Created", "Updated"],
    "rows": detail_rows,
    "body": detail_bodies
  }
  ```

## Step 4: Tell the user

After the tool returns success, tell the user the board is live:

- Search and filter dropdowns work instantly (no round trips)
- Click any row to see its full details in the side panel
- The result count updates automatically as filters narrow the view

## Refreshing

If the user asks to refresh, or after running any `bd` command (close, update, etc.), re-read the JSONL and call `show_table` again.
