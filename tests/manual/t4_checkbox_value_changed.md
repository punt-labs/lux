# T4: Checkbox Value Changed End-to-End

Verifies the second thin-slice: checkbox toggle reaches the wire
layer via `RemoteEventHandlerInvocation` with `event_kind="value_changed"`,
the Hub fires the real handler, and the scene re-pushes.

## Prerequisites

```bash
make restart
```

## Steps

### 1. Show a scene with a checkbox

```bash
lux show scene_id=checkbox-test title="Checkbox Test" elements=[
  {"kind": "checkbox", "id": "cb1", "label": "Enable feature", "value": false}
]
```

**Expected:** Scene acked. Checkbox visible in Lux window, unchecked.

### 2. Verify the scene rendered

```bash
lux inspect_scene scene_id=checkbox-test
```

**Expected:** Element tree contains one checkbox element.

### 3. Check for errors

```bash
lux list_errors
```

**Expected:** Empty errors list.

### 4. Toggle the checkbox

Operator clicks the checkbox in the Lux window.

### 5. Verify the toggle reached the wire layer

```bash
lux list_recent_events count=5
```

**Expected:** Event with `element_id: "cb1"`, `action: "changed"`,
`event_kind: "value_changed"`, `value: true`.

### 6. Verify the Hub updated state

```bash
lux inspect_scene scene_id=checkbox-test
```

**Expected:** Checkbox element shows `value: true`.

## Pass criteria

All six steps produce expected output. The critical gate is step 5:
the event appearing in `list_recent_events` with `event_kind="value_changed"`
proves the `CheckboxRenderer.fire(ValueChanged)` -> `remote_dispatch` ->
`RemoteEventHandlerInvocation` -> Hub dispatch -> handler chain is intact.

## Scope note

This manual test covers the state-mirroring slice: the checkbox toggles,
the Display emits `event_kind="value_changed"`, and the Hub updates the
authoritative checkbox value before re-pushing the scene.

Checkbox wire JSON also supports declarative `handlers` with
`event: "changed"` now. That behavior is covered by automated regression
tests rather than this manual smoke test.
