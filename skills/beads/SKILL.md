---
name: beads
description: >
  Display a beads issue board in the Lux window with filterable table and detail
  panel. Use when the user asks to "show beads", "show the board", "show issues",
  "beads board", "beads UI", "display backlog", "show my work", or wants to
  visually browse project issues. Also triggered by "issue board", "task board",
  "kanban", "backlog view", or "bd ready in lux".
allowed-tools:
  - Bash
  - mcp__plugin_lux_lux__show
  - mcp__plugin_lux_lux__update
  - mcp__plugin_lux_lux__recv
  - mcp__plugin_lux-dev_lux__show
  - mcp__plugin_lux-dev_lux__update
  - mcp__plugin_lux-dev_lux__recv
  - mcp__lux__show
  - mcp__lux__update
  - mcp__lux__recv
---

# /lux:beads — Beads Issue Board

You are composing a beads issue board in the Lux display window. This displays the project's beads issues in a filterable list/detail table using built-in filtering (DES-018) and built-in detail panels (DES-019).

## Phase 1: Read Beads Data

Run `bd list --status=open --limit 0` to get all open issues. If the user asked for all issues (including closed), use `bd list --all --limit 0`.

Then parse the `.beads/issues.jsonl` file directly to get structured data. Each line is a JSON object with fields:

- `id` — issue ID (e.g., "lux-b42")
- `title` — issue title
- `status` — "open", "in_progress", "closed", "deferred"
- `priority` — integer 0-4 (0=critical, 4=backlog)
- `issue_type` — "task", "feature", "bug", "epic"
- `description` — full description text (may be empty)
- `owner` — owner email
- `assignee` — who claimed the bead (set by `bd update --assignee` or `bd update --claim`; absent or empty when unclaimed)
- `created_at` — ISO timestamp
- `updated_at` — ISO timestamp
- `dependencies` — list of dependency objects (optional)

Read the JSONL and filter to the relevant status set. Sort by priority (ascending), then by updated_at (descending).

## Phase 2: Build the Table

Map beads fields to table columns and detail data.

### Table Columns (list view)

| Column | Source | Notes |
|--------|--------|-------|
| ID | `id` | Short identifier |
| Title | `title` | Primary display field |
| Status | `status` | open, in_progress, closed |
| P | `priority` | Display as P0-P4 |
| Type | `issue_type` | task, feature, bug, epic |

### Filters

Three built-in filters cover the main exploration paths:

1. **Search** — `type: "search"`, columns `[0, 1]` (ID and title), hint "Filter by ID or title..."
2. **Status** — `type: "combo"`, column 2, items `["All", "open", "in_progress", "closed", "deferred"]`. Only include statuses that exist in the data.
3. **Type** — `type: "combo"`, column 4, items `["All", "task", "feature", "bug", "epic"]`. Only include types that exist in the data.

### Detail Data

For each row, the detail panel shows:

**Fields** (2-column grid): ID, Status, Priority, Type, Claimed By, Owner, Created, Updated

Note: Title is NOT included in the detail fields — it is already rendered as the detail panel's banner heading. The "Claimed By" field comes from `assignee` — show the value when present, leave empty when the bead is unclaimed.

**Body**: The `description` field. If empty, show "No description."

## Phase 3: Compose and Display

Build the element tree and call `show()`:

```json
{
  "scene_id": "beads-board",
  "title": "Beads: <project-name>",
  "elements": [
    {
      "kind": "table", "id": "beads-list",
      "columns": ["ID", "Title", "Status", "P", "Type"],
      "rows": [/* sorted bead rows */],
      "filters": [/* search + status + type */],
      "detail": {
        "fields": ["ID", "Status", "Priority", "Type", "Claimed By", "Owner", "Created", "Updated"],
        "rows": [/* detail rows with all fields */],
        "body": [/* description per row */]
      },
      "flags": ["borders", "row_bg"]
    }
  ]
}
```

The project name for the title comes from the directory name or `pyproject.toml` project name.

## Phase 4: Interaction

After displaying, tell the user the board is live with built-in filters. The filters, row selection, and detail panel all work at 60fps without round trips.

If the user asks to perform actions on an issue (close, update status, change priority), use `bd` CLI commands directly — these are not handled through the Lux UI. After any `bd` command, re-read the data and call `update()` to refresh the table.

### Refreshing

If the user says "refresh" or you detect that beads data has changed (after running `bd close`, `bd update`, etc.), re-read the JSONL and send an `update()` patch with the new rows.

## Notes

- Beads is a punt-labs standard issue tracker. The `.beads/` directory exists in any project that uses it.
- If no `.beads/` directory exists, tell the user: "No beads database found. Run `bd init` to set up beads for this project."
- Epic issues are included in the list — they provide context for child issues.
- Dependencies are not shown in the table but could be mentioned in the detail body if present.
