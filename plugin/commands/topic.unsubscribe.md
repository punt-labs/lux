---
description: "Drop this session's subscription to a topic"
argument-hint: "<topic>"
allowed-tools: ["mcp__plugin_lux_lux__topic_unsubscribe", "mcp__plugin_lux-dev_lux__topic_unsubscribe", "mcp__lux__topic_unsubscribe"]
---

# /lux:topic.unsubscribe

Drop this session's subscription to a topic. No-op if the session was not subscribed.

## Usage

- `/lux:topic.unsubscribe openTicket` — stop receiving `openTicket` events

## Implementation

Parse `$ARGUMENTS` as one topic name. Call the `topic_unsubscribe` MCP tool.
