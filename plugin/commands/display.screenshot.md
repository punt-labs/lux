---
description: "Capture the display framebuffer (currently unsupported)"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__display_screenshot", "mcp__plugin_lux-dev_lux__display_screenshot", "mcp__lux__display_screenshot"]
---

# /lux:display.screenshot

Ask the display for a framebuffer capture. Today the call is a documented refusal — capture is unresolved below the message layer (DES-028) — and the tool returns `"error: screenshot capture is not supported by the display; see DES-028"`. Kept as an explicit verb rather than a missing one; will produce an image once DES-028 lands.

## Usage

- `/lux:display.screenshot` — attempt to capture a screenshot

## Implementation

Call the `display_screenshot` MCP tool with no arguments and report the result verbatim.
