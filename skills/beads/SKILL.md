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

Display beads issues in a filterable list/detail table in the Lux window.

## Step 1: Render the board

If `.beads/` does not exist, tell the user: "No beads database found. Run `bd init` to set up beads for this project." and stop.

Otherwise, run this **single Bash command**. It reads the JSONL, builds the table payload, and sends it to the lux display server. No manual data munging needed.

For open issues only (default):

```bash
~/.local/share/uv/tools/punt-lux/bin/python3 -c "
import json, os
from punt_lux.client import LuxClient
from punt_lux.protocol import element_from_dict

issues = [json.loads(l) for l in open('.beads/issues.jsonl')]
issues = [i for i in issues if i.get('status') in ('open', 'in_progress')]
issues.sort(key=lambda i: (i.get('priority', 4), i.get('updated_at', '')))

rows, dr, bodies, statuses, types = [], [], [], set(), set()
for i in issues:
    s, p, t = i.get('status','open'), i.get('priority',4), i.get('issue_type','task')
    statuses.add(s); types.add(t)
    rows.append([i['id'], i.get('title',''), s, f'P{p}', t])
    dr.append([i['id'], s, f'P{p}', t, i.get('assignee',''), i.get('owner',''), i.get('created_at','')[:10], i.get('updated_at','')[:10]])
    bodies.append(i.get('description','') or 'No description.')

table = element_from_dict({
    'kind': 'table', 'id': 'beads-list',
    'columns': ['ID', 'Title', 'Status', 'P', 'Type'],
    'rows': rows,
    'filters': [
        {'type': 'search', 'column': [0, 1], 'hint': 'Filter by ID or title...'},
        {'type': 'combo', 'column': 2, 'items': ['All'] + sorted(statuses), 'label': 'Status'},
        {'type': 'combo', 'column': 4, 'items': ['All'] + sorted(types), 'label': 'Type'},
    ],
    'detail': {'fields': ['ID','Status','Priority','Type','Claimed By','Owner','Created','Updated'], 'rows': dr, 'body': bodies},
    'flags': ['borders', 'row_bg'],
})

name = os.path.basename(os.getcwd())
client = LuxClient()
client.connect()
ack = client.show('beads-board', [table], title=f'Beads: {name}')
print(f'ack:{ack.scene_id}' if ack else 'timeout')
client.close()
"
```

For all issues (including closed), change the filter line to:

```python
issues = [json.loads(l) for l in open('.beads/issues.jsonl')]
# Remove the status filter — keep all issues
```

## Step 2: Tell the user

After the command prints `ack:beads-board`, tell the user the board is live:

- Search and filter dropdowns work instantly (no round trips)
- Click any row to see its full details in the side panel
- The result count updates automatically as filters narrow the view

## Refreshing

If the user asks to refresh, or after running any `bd` command (close, update, etc.), re-run the same Bash command from Step 1.

## Notes

- The Python path `~/.local/share/uv/tools/punt-lux/bin/python3` is the standard location for uv tool installations. If it doesn't exist, try `python3` directly (works when running inside the lux project).
- The script connects to the lux display server via Unix socket (auto-spawned on first connection).
- Epic issues are included — they provide context for child issues.
