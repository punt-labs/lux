---
description: "List the Hub's sessions — connections and their scopes"
argument-hint: ""
allowed-tools: ["mcp__plugin_lux_lux__session_ls", "mcp__plugin_lux-dev_lux__session_ls", "mcp__lux__session_ls"]
---

# /lux:session.ls

Print every Hub-side session — every connection the Hub is holding, with its scope. The Display has only one socket client (luxd itself); the meaningful client list is the set of Hub sessions.

## Usage

- `/lux:session.ls` — print the current session table

## Implementation

Call the `session_ls` MCP tool with no arguments and report the result verbatim.
