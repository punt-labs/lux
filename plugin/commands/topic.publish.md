---
description: "Fan a payload out to subscribers of a topic in this scope"
argument-hint: "<topic> [<payload-json>]"
allowed-tools: ["mcp__plugin_lux_lux__topic_publish", "mcp__plugin_lux-dev_lux__topic_publish", "mcp__lux__topic_publish"]
---

# /lux:topic.publish

Publish a payload to every in-scope subscriber of a topic. Publishing with no subscribers is a no-op that returns `"delivered:0"`.

## Usage

- `/lux:topic.publish openTicket` — publish an event with an empty payload
- `/lux:topic.publish openTicket {"id":"T-42","assignee":"alice"}` — publish an event with a payload

## Implementation

Parse `$ARGUMENTS` as a topic name and an optional JSON payload. Call the `topic_publish` MCP tool. Report `"delivered:<count>"` — the number of in-scope subscribers that received the message.
