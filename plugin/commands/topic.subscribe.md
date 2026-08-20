---
description: "Subscribe this session to a business-event topic"
argument-hint: "<topic>"
allowed-tools: ["mcp__plugin_lux_lux__topic_subscribe", "mcp__plugin_lux-dev_lux__topic_subscribe", "mcp__lux__topic_subscribe"]
---

# /lux:topic.subscribe

Subscribe the calling session to a business-event topic in its own scope. The first subscribe (or publish) for a name in this scope declares the topic. Subscriptions never cross sessions.

## Usage

- `/lux:topic.subscribe openTicket` — start receiving `openTicket` events on this session

## Implementation

Parse `$ARGUMENTS` as one topic name. Call the `topic_subscribe` MCP tool. Report `"subscribed:<topic>"` on success.
