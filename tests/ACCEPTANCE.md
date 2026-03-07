# Acceptance Criteria

How each phase is verified. Tests are written before implementation per METHOD.md.

## Criteria Categories

Every phase defines acceptance across three dimensions:

- **Functional**: what the system must do (tested by unit + integration tests)
- **Performance**: latency and throughput bounds (tested by benchmarks with assertions)
- **Error**: failure modes handled gracefully (tested by fault injection)

## Phase 0: Test Infrastructure

- [x] CI pipeline runs and passes with trivial application code
- [x] Unit, integration, and E2E test tiers produce output
- [x] Coverage tooling reports a baseline (70%)
- [x] Risk register exists and has been reviewed

## Phase 1: Walking Skeleton

### Functional

- [ ] `lux display` starts an ImGui window and listens on a Unix socket
- [ ] `lux show '{"type":"scene",...}'` sends a scene to the display and it renders
- [ ] Text, button, and separator elements render correctly
- [ ] Button clicks generate `interaction` events back to the client
- [ ] `lux clear` removes all content from the display
- [ ] Display sends `ready` message on client connection
- [ ] Display sends `ack` after receiving a scene

### Performance

- [ ] Scene send-to-render latency < 50ms (measured by ping/pong)
- [ ] Display maintains 30+ fps while rendering a 10-element scene
- [ ] Socket reconnection after display restart < 1 second

### Error

- [ ] Client handles display not running (clear error message, not crash)
- [ ] Display handles malformed JSON (logs warning, continues rendering)
- [ ] Display handles client disconnect (continues running, accepts new connections)
- [ ] Client handles display crash (detects closed socket, reports to caller)

## Phase 2: Scene Vocabulary

### Functional

- [ ] All display elements render: text (heading/body/code), separator, progress, spinner
- [ ] All interactive elements work: slider, checkbox, combo, input_text, radio, color_picker
- [ ] State persistence: widget values survive across scene updates
- [ ] `update` message patches individual elements without full scene replacement
- [ ] Layout modes work: rows, columns, grid

### Performance

- [ ] 50-element scene renders at 30+ fps
- [ ] Scene update (patch 1 element in 50) < 20ms round-trip

### Error

- [ ] Unknown element kinds render as red error text (not crash)
- [ ] Missing required fields on elements show warnings (not crash)
- [ ] Element ID collisions handled gracefully

## Phase 3: Data and Visualization

### Functional

- [ ] Table element renders with headers, rows, and column alignment
- [ ] Plot element renders line, scatter, and bar charts via ImPlot
- [ ] Draw element renders: line, rect, circle, text, bezier, polyline
- [ ] Image element displays PNG/JPEG from file path
- [ ] Image element displays base64-encoded inline images

### Performance

- [ ] 1000-row table renders at 30+ fps (ImGui clipping)
- [ ] Plot with 10,000 data points renders at 30+ fps
- [ ] Image texture upload < 100ms for a 1920x1080 PNG

### Error

- [ ] Missing image file shows placeholder (not crash)
- [ ] Invalid plot data shows error text (not crash)
- [ ] Texture upload failure logged and recovered

## Phase 4: Code-on-Demand

### Functional

- [ ] `render_function` element shows consent modal before execution
- [ ] User can Allow or Deny code execution
- [ ] Allowed code runs each frame with RenderContext (state, dt, dimensions)
- [ ] Code errors display in-window in red (not crash display)
- [ ] New code triggers new consent prompt (hot-reload)
- [ ] AST scanner flags suspicious patterns in the consent modal

### Performance

- [ ] Compiled render function adds < 1ms per frame overhead
- [ ] Consent modal renders at 60fps during code review

### Error

- [ ] Syntax errors in code caught at compile time, shown in modal
- [ ] Runtime errors caught per-frame, displayed without crashing
- [ ] Denied code shows "Execution denied" placeholder

## Phase 5: Image Generation

### Functional

- [ ] `lux generate "prompt"` calls OpenAI image generation and displays result
- [ ] Generated image appears in the display window
- [ ] MCP tool `lux.generate` works from Claude Code

### Performance

- [ ] Image generation request submitted < 500ms (network latency excluded)
- [ ] Generated image displayed within 1 second of API response

### Error

- [ ] Missing API key produces clear error message
- [ ] API rate limit handled with retry and user feedback
- [ ] Network timeout produces clear error (not hang)

## Phase 6: Polish and Distribution

### Functional

- [ ] `pip install punt-lux` installs CLI and MCP server
- [ ] `lux --version` prints version
- [ ] `lux doctor` checks environment (display availability, API keys)
- [ ] MCP server registers tools: show, update, clear, generate

### Performance

- [ ] CLI startup < 500ms
- [ ] MCP server ready < 1 second

### Error

- [ ] All CLI commands produce helpful error messages on failure
- [ ] MCP server handles tool call errors gracefully (returns error, not crash)

## Test Patterns

### Unit tests (`tests/test_*.py`, no markers)

Test pure functions and data models. No I/O, no sockets, no GUI.

```python
def test_encode_decode_roundtrip(simple_scene):
    frame = encode_frame(simple_scene)
    decoded, _ = decode_frame(frame)
    assert decoded == simple_scene
```

### Integration tests (`@pytest.mark.integration`)

Test socket IPC and protocol behavior with real sockets but no display.

```python
@pytest.mark.integration
def test_socket_send_receive(socket_pair, simple_scene):
    client, server = socket_pair
    client.sendall(encode_frame(simple_scene))
    data = server.recv(4096)
    decoded, _ = decode_frame(data)
    assert decoded == simple_scene
```

### E2E tests (`@pytest.mark.e2e`)

Test full stack with display process. Excluded from CI (requires GPU).

```python
@pytest.mark.e2e
def test_display_accepts_scene():
    proc = subprocess.Popen(["lux", "display", "--headless"])
    # connect, send scene, verify ack
```

### Performance tests (`@pytest.mark.slow`)

Benchmarks with assertions on latency/throughput bounds.

```python
@pytest.mark.slow
def test_ipc_latency(socket_pair):
    times = [measure_roundtrip(socket_pair) for _ in range(100)]
    assert statistics.median(times) < 0.050  # 50ms
```
