---
description: "List the Hub-owned menu bar and its items"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__menu_ls", "mcp__plugin_lux-dev_lux__menu_ls", "mcp__lux__menu_ls"]
---

# /lux:menu.ls

Read the Hub's menu registry — every menu label, every item, every registered callback — with no display-side reach-around.

## Usage

- `/lux:menu.ls` — print the current menu bar

## Implementation

Call the `menu_ls` MCP tool with no arguments and report the result verbatim.
