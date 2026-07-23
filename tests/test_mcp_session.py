"""Tests for punt_lux.mcp_session -- the streamable-HTTP session lifecycle."""

from __future__ import annotations

from punt_lux.mcp_session import SessionRegistry


class TestSessionRegistry:
    def test_starts_empty(self):
        assert SessionRegistry().count == 0

    def test_add_counts_a_session(self):
        registry = SessionRegistry()
        registry.add("sess-a")
        assert registry.count == 1

    def test_add_is_idempotent(self):
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.add("sess-a")
        assert registry.count == 1

    def test_discard_removes_a_session(self):
        registry = SessionRegistry()
        registry.add("sess-a")
        registry.discard("sess-a")
        assert registry.count == 0

    def test_discard_absent_is_a_noop(self):
        SessionRegistry().discard("never-added")  # must not raise
