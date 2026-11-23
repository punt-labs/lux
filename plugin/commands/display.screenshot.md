---
description: "Capture the display's next painted frame to a PNG"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__display_screenshot", "mcp__plugin_lux-dev_lux__display_screenshot", "mcp__lux__display_screenshot"]
---

# /lux:display.screenshot

Ask the display for a capture of the frame it paints next. The tool returns the path of a PNG on the display's host; open it with the Read tool to see the rendered pixels. A second capture requested while one is still waiting for its frame is refused.

## Usage

- `/lux:display.screenshot` — capture the next frame and report its path

## Implementation

Call the `display_screenshot` MCP tool with no arguments and report the result verbatim.
