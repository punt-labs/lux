# T4: Dialog Button Click End-to-End

Verifies the D21 thin-slice: dialog modal button clicks reach the wire
layer via `RemoteEventHandlerInvocation`, the Hub fires the real handler,
the dialog dismisses, and a confirmation scene renders.

Automated counterpart: `tests/regression/test_dialog_interaction_trace.py`

## Prerequisites

```bash
make restart   # build, install, restart both luxd and display
```

Both processes running (luxd + display PIDs printed).

## Steps

### 1. Show a dialog with OK/Cancel buttons

```bash
lux show scene_id=dialog-test title="Dialog Button Test" elements=[
  {"kind": "dialog", "id": "dlg1", "title": "Confirm Action", "children": [
    {"kind": "button", "id": "btn-ok", "label": "OK", "click": "confirm", "publish": ["dialog.confirmed"]},
    {"kind": "button", "id": "btn-cancel", "label": "Cancel", "click": "cancel"}
  ]}
]
```

**Expected:** Scene acked. Modal popup visible in the Lux window with OK
and Cancel buttons.

### 2. Verify the scene rendered

```bash
lux inspect_scene scene_id=dialog-test
```

**Expected:** Element tree contains one dialog with two button children.

### 3. Check for errors

```bash
lux list_errors
```

**Expected:** Empty errors list.

### 4. Click OK in the modal

Operator clicks the OK button in the Lux window.

### 5. Verify the click reached the wire layer

```bash
lux list_recent_events count=5
```

**Expected:** Event with `element_id: "btn-ok"`, `action: "btn-ok"`,
`value: true`.

### 6. Verify the dialog dismissed

```bash
lux inspect_scene scene_id=dialog-test
```

**Expected:** `elements: []` — the Hub fired `model.confirm()` which
called `mark_removed()`, and the Hub re-pushed an empty scene.

### 7. Send confirmation scene

```bash
lux show scene_id=dialog-test title="Dialog Button Test" elements=[
  {"kind": "text", "id": "confirm-msg", "content": "Action confirmed.", "style": "heading", "color": "#00CC66"}
]
```

**Expected:** "Action confirmed." visible in the Lux window.

## Pass criteria

All seven steps produce their expected output. The critical gate is
step 5: the click event appearing in `list_recent_events` proves the
full `ButtonRenderer.fire(ButtonClicked)` -> `remote_dispatch` ->
`RemoteEventHandlerInvocation` -> Hub dispatch -> `model.confirm()` ->
`mark_removed()` -> scene re-push chain is intact.
