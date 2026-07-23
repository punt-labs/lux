"""Tests for punt_lux.session_key -- the MCP session identity value class."""

from __future__ import annotations

from punt_lux.domain.ids import ConnectionId
from punt_lux.session_key import RESERVED_REST_CONNECTION, SessionKey


class TestSanitization:
    def test_strips_control_characters(self):
        """Control characters are removed so a key is safe to log and to key on."""
        assert SessionKey("evil\r\nINJECTED\x00tail").value == "evilINJECTEDtail"

    def test_caps_length(self):
        assert len(SessionKey("x" * 200).value) == 64

    def test_none_is_empty(self):
        assert SessionKey(None).value == ""


class TestFromRequest:
    def test_blank_defaults_to_random_handle(self):
        """A missing query value gets a random 8-char handle, never an empty id."""
        key = SessionKey.from_request("")
        assert len(key.value) == 8

    def test_blank_handles_are_distinct_per_request(self):
        """Each missing-key request gets its own handle, so an omitted key
        can never bind onto an existing session's scope."""
        first = SessionKey.from_request("")
        second = SessionKey.from_request("")
        assert first.value != second.value

    def test_present_value_is_kept(self):
        assert SessionKey.from_request("pid-1234").value == "pid-1234"

    def test_present_value_is_sanitized(self):
        assert SessionKey.from_request("pid\x001234").value == "pid1234"

    def test_control_chars_only_gets_a_random_handle(self):
        """A non-empty value that sanitizes to "" must still get a handle.

        Otherwise every control-chars-only key collapses onto the empty
        identity instead of the promised distinct random handle.
        """
        key = SessionKey.from_request("\x01\x02\x03")
        assert key.value != ""
        assert len(key.value) == 8

    def test_sanitizes_to_reserved_still_collides(self):
        """The handle default never masks a value that sanitizes to the
        reserved id — ``rest`` with a trailing NUL is still refused."""
        assert SessionKey.from_request("rest\x00").is_reserved

    def test_sanitizes_to_empty_is_not_reserved(self):
        assert not SessionKey.from_request("\x01\x02").is_reserved


class TestConnectionId:
    def test_connection_id_is_the_sanitized_value(self):
        assert SessionKey("pid-1234").connection_id == ConnectionId("pid-1234")


class TestReserved:
    def test_rest_key_is_reserved(self):
        assert SessionKey("rest").is_reserved

    def test_reserved_matches_the_constant(self):
        assert SessionKey("rest").connection_id == RESERVED_REST_CONNECTION

    def test_ordinary_key_is_not_reserved(self):
        assert not SessionKey("pid-1234").is_reserved

    def test_control_char_variant_still_collides(self):
        """A key that sanitizes to the reserved id is caught, not smuggled past."""
        assert SessionKey("rest\x00").is_reserved
