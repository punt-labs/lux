# Risk Register

Identified before Phase 1 implementation. Each risk includes spike evidence where available.

## RISK-001: imgui-bundle Cross-Platform Rendering

**Severity:** High
**Status:** MITIGATED (Spike A)

ImGui rendering depends on platform-specific OpenGL backends. Differences between macOS (Metal via SDL), Linux (OpenGL/Vulkan via SDL), and CI (headless, no GPU) could cause failures.

**Evidence:**

- Spike A confirmed macOS ARM64 works: imgui-bundle 1.6.0 renders, textures upload via PyOpenGL.
- Pre-built wheels exist for macOS ARM64, Linux x86-64/ARM64, Windows (Python 3.11-3.14).
- CI (ubuntu-latest) has no display server — ImGui window creation will fail in headless CI.

**Mitigation:**

- Unit and integration tests do not import imgui-bundle (test protocol and data, not rendering).
- E2E tests requiring a display are marked `@pytest.mark.e2e` and excluded from CI.
- Linux testing deferred to a contributor with a Linux desktop or a CI runner with Xvfb.

**Residual risk:** First Linux user may hit rendering issues not caught on macOS.

## RISK-002: Unix Domain Socket IPC Reliability

**Severity:** Medium
**Status:** MITIGATED (Spike B)

The display server and MCP client communicate over `AF_UNIX SOCK_STREAM`. Risks: message framing errors, partial reads, connection drops, socket path discovery across platforms.

**Evidence:**

- Spike B demonstrated zero drops at 100-message burst, ~10-21ms RTT on macOS.
- Length-prefixed framing (4-byte big-endian + JSON) is implemented and tested in `protocol.py`.
- Socket discovery uses `$XDG_RUNTIME_DIR/lux/display.sock` with `/tmp/lux-$USER/` fallback.

**Mitigation:**

- Protocol encode/decode has unit tests with edge cases (incomplete header, incomplete payload, oversized message).
- Integration tests use real socket pairs to verify multi-message and bidirectional flows.
- `MAX_MESSAGE_SIZE` (16 MiB) enforced in both encode and decode paths.

**Residual risk:** Long-running connections may accumulate partial reads under load. Needs a buffering `FrameReader` class (Phase 1).

## RISK-003: MCP stdio Transport + Display Process Lifecycle

**Severity:** High
**Status:** OPEN

The MCP server runs as a stdio subprocess of Claude Code. The display is a separate persistent process with a GUI window. Coordinating their lifecycles is the hardest integration:

- Who spawns the display? The MCP server? The user?
- What happens when the MCP server exits (Claude Code session ends)?
- What happens when the display window is closed while the MCP server is waiting?
- How does the MCP server discover a running display?

**Mitigation plan (Phase 1):**

- `lux display` is a standalone CLI command that starts the display process.
- The MCP server connects to the display socket on first `lux.show()` call. If no display is running, it auto-spawns one.
- Display sends a `window.closed` event when the user closes the window. MCP server handles gracefully.
- PID file at the socket path + `.pid` for process discovery and stale socket cleanup.

**Residual risk:** Race conditions between auto-spawn and connection. Zombie display processes if MCP server crashes without cleanup.

## RISK-004: OpenGL Texture Lifecycle

**Severity:** Medium
**Status:** MITIGATED (Spike A)

Images must be uploaded to GPU as OpenGL textures. Risks: texture leaks (never freed), stale textures (file changed on disk), texture ID reuse after deletion.

**Evidence:**

- Spike A demonstrated texture upload via `glGenTextures` / `glTexImage2D` (~10 lines via PyOpenGL).
- `imgui.image()` requires `ImTextureRef(tex_id)` wrapper, not raw int — discovered and fixed in Spike A.

**Mitigation plan (Phase 1):**

- Texture cache keyed by (file path, mtime). Reloads when mtime changes.
- LRU eviction: textures not referenced in the current scene are freed after N frames.
- All OpenGL calls on the main thread (ImGui constraint, not a choice).

**Residual risk:** Large images (4K+) may cause GPU memory pressure. No budget enforcement in v1.

## RISK-005: ImPlot Initialization

**Severity:** Low
**Status:** MITIGATED (Spike D)

ImPlot requires explicit context creation at application startup. If a scene contains `plot` elements but ImPlot was not initialized, rendering will crash or silently fail.

**Evidence:**

- Spike D confirmed: `immapp.run(runner_params, addons)` with `addons.with_implot = True` initializes ImPlot correctly.
- Plot elements with line/scatter/bar data rendered successfully.

**Mitigation:**

- Display server always initializes ImPlot at startup (zero cost if unused).
- Renderer skips plot elements with a warning if ImPlot context is somehow missing.

**Residual risk:** None — this is fully mitigated.

## RISK-006: Code-on-Demand Security

**Severity:** High
**Status:** ACCEPTED (Spike E)

The `render_function` element runs arbitrary Python code in the display process. Python has no reliable in-process sandbox.

**Evidence:**

- Spike E confirmed: `RestrictedPython` can be bypassed. `seccomp` is Linux-only. PyPy sandbox is abandoned.
- AST warning scanner flags suspicious patterns but is not a security boundary.
- Consent modal UX works well in ImGui.

**Mitigation:**

- User consent gate (modal dialog showing full code) required before execution.
- AST scanner provides yellow warnings for suspicious patterns (imports of `os`, `subprocess`, etc.).
- Code compiled once, `render(ctx)` called per frame. Errors caught and displayed in-window.
- Hot-reload: new code triggers new consent prompt.

**Residual risk:** Accepted. Follows the same trust model as Claude Code's Bash tool. The user is the security boundary, not the sandbox.

## Summary

| Risk | Severity | Status | Phase |
|------|----------|--------|-------|
| RISK-001: Cross-platform rendering | High | Mitigated | 0 |
| RISK-002: Socket IPC reliability | Medium | Mitigated | 0 |
| RISK-003: Process lifecycle | High | Open | 1 |
| RISK-004: Texture lifecycle | Medium | Mitigated | 1 |
| RISK-005: ImPlot init | Low | Mitigated | 0 |
| RISK-006: Code-on-demand security | High | Accepted | 4 |
