---
name: dashboard
description: >
  Display a dashboard in the Lux window with metrics cards, charts, and status
  tables. Use when the user asks to "show a dashboard", "display metrics",
  "visualize status", "show KPIs", "monitor progress", or wants a visual
  overview of data. Also triggered by "build a dashboard", "metric cards",
  or "status overview".
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

# /lux:dashboard — Visual Dashboard Composer

You are composing a dashboard in the Lux display window. A dashboard is a single-glance overview: metric cards at the top, charts in the middle, detail table at the bottom. Adapt the layout to the data — don't force structure where it doesn't fit.

## Phase 1: Gather Data

Determine what to display. Look at `$ARGUMENTS` and conversation context:

- If the user specified data (e.g., "show a dashboard of test results"), use it directly
- If the user pointed to a file or command output, read/parse that first
- If vague ("show me a dashboard"), ask what metrics matter — don't guess

You need at minimum **one** of:

- Key-value metrics (numbers with labels)
- Time series or categorical data (for charts)
- Tabular data (rows and columns)

## Phase 2: Compose the Layout

Build the element tree following the dashboard pattern. Adapt to what you have — not every dashboard needs all three sections.

### Pattern: Metric Cards → Chart → Detail Table

**Metric cards** — Use a `group` with `layout: "columns"` containing `text` elements. Each card shows a label and a value. Use 2-5 cards; more than 5 loses the single-glance property.

**Charts** — Use `plot` elements for trends, comparisons, or distributions. Pick the right series type:

- `line` for time series and trends
- `bar` for comparisons and categories
- `scatter` for correlations
- Multiple series on one plot for comparisons

**Detail table** — Use `table` for the full data behind the metrics. Add `flags: ["borders", "row_bg"]` for readability. Keep columns to what fits — 3-6 columns is the sweet spot.

### Reference Example

This is the canonical form. Adapt freely — fewer metrics, different chart types, extra sections, tabs for categories. The structure is a suggestion, not a constraint.

```json
{
  "scene_id": "dashboard",
  "title": "Project Status",
  "elements": [
    {
      "kind": "group", "id": "metrics", "layout": "columns",
      "children": [
        {"kind": "text", "id": "m1", "content": "Tests Passing\n142 / 150"},
        {"kind": "text", "id": "m2", "content": "Coverage\n94.7%"},
        {"kind": "text", "id": "m3", "content": "Open Issues\n7"},
        {"kind": "text", "id": "m4", "content": "Build Time\n2.3s"}
      ]
    },
    {"kind": "separator"},
    {
      "kind": "plot", "id": "trend",
      "title": "Test Results (last 7 days)",
      "x_label": "Day", "y_label": "Count",
      "series": [
        {"label": "Passing", "type": "line", "x": [1,2,3,4,5,6,7], "y": [130,135,138,140,139,141,142]},
        {"label": "Failing", "type": "line", "x": [1,2,3,4,5,6,7], "y": [20,15,12,10,11,9,8]}
      ]
    },
    {"kind": "separator"},
    {
      "kind": "table", "id": "details",
      "columns": ["Test Suite", "Pass", "Fail", "Skip", "Time"],
      "rows": [
        ["unit", 95, 3, 2, "0.8s"],
        ["integration", 38, 4, 1, "1.2s"],
        ["e2e", 9, 1, 0, "0.3s"]
      ],
      "flags": ["borders", "row_bg"]
    }
  ]
}
```

### Layout Adaptations

- **Metrics only** (no chart data): Skip the plot, expand metric cards
- **Single category**: Flat layout, no tabs
- **Multiple categories**: Use `tab_bar` with one tab per category, each containing its own metrics + chart + table
- **Live monitoring**: Add a `button` with `id: "refresh"` and a `spinner` for loading state — then use `recv()` to detect clicks and `update()` to refresh values
- **Comparison view**: Use `group` with `layout: "columns"` to place two chart panels side by side

## Phase 3: Display

Call `set_theme("imgui_colors_light")` before showing the dashboard — light themes work best for data-dense views with tables and charts. Then call `show()` with the composed element tree. Use a descriptive `scene_id` (e.g., `"test-dashboard"`, `"sales-metrics"`).

## Phase 4: Interaction (Optional)

If the dashboard has interactive elements (refresh button, filter combo, tab switches):

1. Tell the user what interactions are available
2. Use `recv()` to listen for events when the user indicates they've interacted
3. Use `update()` to patch changed values — don't re-send the entire scene

For auto-refresh patterns, the user must trigger each refresh cycle (e.g., "refresh the dashboard") — there is no background polling.
