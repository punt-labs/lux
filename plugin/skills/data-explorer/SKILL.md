---
name: data-explorer
description: >
  Display an interactive data explorer in the Lux window with filterable tables,
  search inputs, and detail panels. Use when the user asks to "explore data",
  "browse results", "filter a table", "search through records", "show me the
  data", or wants to interactively navigate tabular data. Also triggered by
  "data viewer", "record browser", "filterable table", or "drill into the data".
allowed-tools:
  - mcp__plugin_lux_lux__scene_show
  - mcp__plugin_lux_lux__scene_update
  - mcp__plugin_lux_lux__topic_recv
  - mcp__plugin_lux_lux__set_theme
  - mcp__plugin_lux-dev_lux__scene_show
  - mcp__plugin_lux-dev_lux__scene_update
  - mcp__plugin_lux-dev_lux__topic_recv
  - mcp__plugin_lux-dev_lux__set_theme
  - mcp__lux__scene_show
  - mcp__lux__scene_update
  - mcp__lux__topic_recv
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

**Prefer the packaged `scene_table` filters** — the Hub composes a search box, status combos, the grid, and a selection-bound detail panel from primitives and filters Hub-side (the packaged default): the grid always shows exactly the rows the Hub holds, and a selection hidden by a filter reappears when the filter is cleared. Use separate filter elements + `topic_recv()`/`scene_update()` only when you need custom logic the packaged filters can't handle (e.g., numeric ranges, cross-field filters, external lookups).

### Built-in Filters (preferred)

Add a `filters` array to the `table` element. Two types are available:

| Data pattern | Filter type | Config |
|-------------|------------|--------|
| Free-text search (name, title, description) | `search` | `column: [0, 1]` — which columns to search |
| Categorical field (status, type, category) | `combo` | `column: 2, items: ["All", "open", "closed"]` |

**Rules:**

- 1-3 filters is ideal. More than 4 overwhelms the UI.
- Always include a text search if the data has a name/title/description field.
- Include only values that exist in the data for combo items.
- The first combo item should be "All" (no filter).

### Built-in Detail Panel (preferred)

Pass a `detail` object to `scene_table` for drill-down (the basic `table`
element is just a grid — `scene_table` composes the detail panel as a sibling
element). The Hub binds the composed panel to the grid's selection: click a
row and the Hub patches the panel with that row's fields and body text.

### Separate Filter Elements (advanced)

For filters that built-in types can't handle (numeric ranges, sliders, cross-field logic), use separate elements and the `topic_recv()`/`scene_update()` loop:

| Data pattern | Element kind |
|-------------|-------------|
| Boolean field (active, archived) | `checkbox` |
| Numeric range (score, price) | `slider` |
| Custom compound filter | `input_text` + custom logic |

## Phase 3: Compose the Layout

Build the element tree following the data explorer pattern.

### Pattern: `scene_table` with Filters + Detail

Call the `scene_table` tool with `columns`/`rows`/`filters`/`detail`. The Hub
composes a search box, status combos, the grid, and a selection-bound detail
panel from primitives and wires the Hub-side filter and detail handlers — search,
filter, row selection, and detail all work without your `topic_recv()`/`scene_update()` loop.
(Pass `filters`/`detail` to `scene_table`, not to a raw `table` element in
`scene_show()`: the basic `table` element is a grid alone; the chrome is composed.)

### Reference Example

This is the canonical form — a searchable, filterable list of issues with
drill-down detail. Adapt freely to any tabular data: search results, log entries,
test cases, inventory, API responses.

```python
scene_table(
    scene_id="data-explorer",
    title="Issue Explorer",
    columns=["ID", "Title", "Status", "Priority", "Assignee"],
    rows=[
        ["ISS-001", "Fix login timeout", "Open", "P1", "alice"],
        ["ISS-002", "Add dark mode", "In Progress", "P2", "bob"],
        ["ISS-003", "Update API docs", "Open", "P3", "carol"],
        ["ISS-004", "Memory leak in worker", "Open", "P0", "alice"],
        ["ISS-005", "Refactor auth module", "Closed", "P2", "bob"],
    ],
    filters=[
        {"type": "search", "column": [0, 1], "hint": "Filter by ID or title..."},
        {"type": "combo", "column": 2, "items": ["All", "Open", "In Progress", "Closed"], "label": "Status"},
        {"type": "combo", "column": 3, "items": ["All", "P0", "P1", "P2", "P3"], "label": "Priority"},
    ],
    detail={
        "fields": ["ID", "Status", "Priority", "Assignee", "Created"],
        "rows": [
            ["ISS-001", "Open", "P1", "alice", "2026-03-01"],
            ["ISS-002", "In Progress", "P2", "bob", "2026-03-02"],
            ["ISS-003", "Open", "P3", "carol", "2026-03-03"],
            ["ISS-004", "Open", "P0", "alice", "2026-03-04"],
            ["ISS-005", "Closed", "P2", "bob", "2026-03-05"],
        ],
        "body": [
            "The login flow times out after 30s on slow connections...",
            "Add system-wide dark mode toggle with persistent preference.",
            "API docs are outdated after the v2 migration.",
            "Worker process leaks ~10MB/hour under sustained load.",
            "Auth module has accumulated tech debt — extract into clean service.",
        ],
    },
)
```

### Layout Adaptations

- **No categorical fields**: Skip combo filters, use only text search
- **Many categories**: Use `tab_bar` with one tab per major category instead of a combo filter
- **Large data sets** (50+ rows): the grid scrolls natively — no pager needed; a Display-side clipper draws only the visible rows
- **Hierarchical data**: Use `tree` elements instead of a flat table
- **Side-by-side detail**: Use `group` with `layout: "columns"` to place the table and detail panel next to each other instead of stacked

## Phase 4: Display

Call `set_theme("imgui_colors_light")` before showing — light themes work best for data-dense views. Then call `scene_show()` with the composed element tree.

## Phase 5: Interaction

With the packaged `scene_table` filters and detail, the data explorer is fully interactive without any `topic_recv()`/`scene_update()` loop. Tell the user:

- **Search** and **filter dropdowns** filter the grid Hub-side (the grid shows exactly the rows that match)
- **Click any row** to see its full details in the side panel
- A selection hidden by a filter reappears when the filter is cleared

### When recv/update IS needed

Use the `topic_recv()`/`scene_update()` loop only for operations that require LLM orchestration:

- **Actions on selected row** — "Close this issue", "Assign to me" (requires external API calls)
- **Data refresh** — re-reading from a changing data source (add a "Refresh" button)
- **Custom filter logic** — numeric ranges, cross-field filters, or external lookups that built-in filters can't handle

```json
{
  "scene_id": "data-explorer",
  "patches": [
    {"id": "data-table", "set": {"rows": [/* refreshed data */]}}
  ]
}
```

## Phase 6: Refresh (Optional)

If the underlying data can change (live logs, query results), add a `button` with `id: "refresh"` in the filters row. When clicked, re-read the data source and recompute the filtered view.
