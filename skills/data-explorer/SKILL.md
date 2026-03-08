---
name: data-explorer
description: >
  Display an interactive data explorer in the Lux window with filterable tables,
  search inputs, and detail panels. Use when the user asks to "explore data",
  "browse results", "filter a table", "search through records", "show me the
  data", or wants to interactively navigate tabular data. Also triggered by
  "data viewer", "record browser", "filterable table", or "drill into the data".
allowed-tools:
  - mcp__plugin_lux_lux__show
  - mcp__plugin_lux_lux__update
  - mcp__plugin_lux_lux__recv
  - mcp__plugin_lux_lux__set_theme
  - mcp__plugin_lux-dev_lux__show
  - mcp__plugin_lux-dev_lux__update
  - mcp__plugin_lux-dev_lux__recv
  - mcp__plugin_lux-dev_lux__set_theme
  - mcp__lux__show
  - mcp__lux__update
  - mcp__lux__recv
  - mcp__lux__set_theme
---

# /lux:data-explorer — Interactive Data Explorer

You are composing an interactive data explorer in the Lux display window. A data explorer lets the user filter, search, and drill into tabular data. The layout is: filter controls at the top, data table in the middle, detail panel at the bottom. Interaction is the core — the user changes filters, the table updates.

## Phase 1: Identify the Data

Determine what to explore. Look at `$ARGUMENTS` and conversation context:

- If the user specified a data source (e.g., "explore the test results"), read/parse it
- If the user pointed to a file, command output, or API response, extract rows and columns
- If vague ("let me explore the data"), ask what data set — don't guess

You need:

- **Rows** — a list of records (dicts or arrays)
- **Columns** — field names for the table headers (3-6 columns is the sweet spot; more than 8 becomes unreadable)

## Phase 2: Design the Filters

Choose filter controls based on the data shape. Use the fewest filters that cover the most common exploration paths.

| Data pattern | Filter control | Element kind |
|-------------|---------------|-------------|
| Categorical field (status, type, category) | Dropdown | `combo` with `items` list |
| Boolean field (active, archived, passing) | Toggle | `checkbox` |
| Free-text search (name, description, title) | Search box | `input_text` with `hint` |
| Numeric range (score, count, price) | Range display | `text` showing current range + `slider` |

**Rules:**

- 1-3 filters is ideal. More than 4 overwhelms the UI.
- Always include a text search if the data has a name/title/description field.
- Put the most selective filter first (the one that reduces the most rows).
- Every filter element needs a unique `id` — you will match on these IDs when handling events.

## Phase 3: Compose the Layout

Build the element tree following the data explorer pattern.

### Pattern: Filters → Table → Detail

**Filters** — Use a `group` with `layout: "columns"` containing the filter controls. This places them in a horizontal row at the top.

**Result count** — Use a `text` element showing the count of visible rows (e.g., "Showing 12 of 45 records"). Update this when filters change.

**Data table** — Use `table` with `flags: ["borders", "row_bg"]` for readability. Include all rows initially (no pre-filtering). Use `column_widths` if some columns need more space than others.

**Detail panel** — Use a `collapsing_header` at the bottom containing `text` elements with the full record details. Start collapsed. When the user selects a row, update this panel with that row's details.

### Reference Example

This is the canonical form — a searchable, filterable list of issues. Adapt freely to any tabular data: search results, log entries, test cases, inventory, API responses.

```json
{
  "scene_id": "data-explorer",
  "title": "Issue Explorer",
  "elements": [
    {
      "kind": "group", "id": "filters", "layout": "columns",
      "children": [
        {"kind": "input_text", "id": "search", "label": "Search", "hint": "Filter by title...", "value": ""},
        {"kind": "combo", "id": "status-filter", "label": "Status", "items": ["All", "Open", "Closed", "In Progress"], "selected": 0},
        {"kind": "combo", "id": "priority-filter", "label": "Priority", "items": ["All", "P0", "P1", "P2", "P3"], "selected": 0}
      ]
    },
    {"kind": "separator"},
    {"kind": "text", "id": "result-count", "content": "Showing 24 of 24 issues"},
    {
      "kind": "table", "id": "data-table",
      "columns": ["ID", "Title", "Status", "Priority", "Assignee"],
      "rows": [
        ["ISS-001", "Fix login timeout", "Open", "P1", "alice"],
        ["ISS-002", "Add dark mode", "In Progress", "P2", "bob"],
        ["ISS-003", "Update API docs", "Open", "P3", "carol"],
        ["ISS-004", "Memory leak in worker", "Open", "P0", "alice"],
        ["ISS-005", "Refactor auth module", "Closed", "P2", "bob"]
      ],
      "flags": ["borders", "row_bg"]
    },
    {"kind": "separator"},
    {
      "kind": "collapsing_header", "id": "detail-panel", "label": "Details",
      "children": [
        {"kind": "text", "id": "detail-content", "content": "Select a row to see details."}
      ]
    }
  ]
}
```

### Layout Adaptations

- **No categorical fields**: Skip combo filters, use only text search
- **Many categories**: Use `tab_bar` with one tab per major category instead of a combo filter
- **Large data sets** (50+ rows): Paginate — show first N rows, add "Next" / "Previous" buttons
- **Hierarchical data**: Use `tree` elements instead of a flat table
- **Side-by-side detail**: Use `group` with `layout: "columns"` to place the table and detail panel next to each other instead of stacked

## Phase 4: Display

Call `set_theme("imgui_colors_light")` before showing — light themes work best for data-dense views. Then call `show()` with the composed element tree.

## Phase 5: Interaction Loop

This is the core of the data explorer. Tell the user the filters are live, then handle interactions as they report them.

### Handling Filter Changes

When the user says they changed a filter (or you call `recv()` and get an event):

1. **Parse the event** — `recv()` returns strings like `interaction:element=search,action=changed,value=fix` or `interaction:element=status-filter,action=selected,value=1`
2. **Apply all active filters** to the full data set to compute the visible rows
3. **Update the table** via `update()` — patch `data-table` with new `rows` and `result-count` with new count text

```json
{
  "scene_id": "data-explorer",
  "patches": [
    {"id": "data-table", "set": {"rows": [["ISS-001", "Fix login timeout", "Open", "P1", "alice"]]}},
    {"id": "result-count", "set": {"content": "Showing 1 of 24 issues"}}
  ]
}
```

### Handling Row Selection

If the data table has selectable rows, update the detail panel when a row is selected:

```json
{
  "scene_id": "data-explorer",
  "patches": [
    {"id": "detail-content", "set": {"content": "ISS-001: Fix login timeout\n\nStatus: Open\nPriority: P1\nAssignee: alice\nCreated: 2026-03-01\n\nThe login flow times out after 30s on slow connections..."}}
  ]
}
```

### Interaction Flow

For each `recv()` event:

- `element=search` → re-filter rows where title/name contains the search text (case-insensitive)
- `element=<combo-filter>` → re-filter rows where the field matches the selected item (skip if "All")
- `element=<checkbox-filter>` → include/exclude rows based on boolean field

Always apply **all** active filters together (AND logic), not just the one that changed. Recompute from the full data set each time.

## Phase 6: Refresh (Optional)

If the underlying data can change (live logs, query results), add a `button` with `id: "refresh"` in the filters row. When clicked, re-read the data source and recompute the filtered view.
