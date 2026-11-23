"""The applet name format the Hub reads back — the coupling both halves stand on.

The writer sits on :meth:`AppletIdentity.for_session` and the reader on
:func:`session_pid_from_name` here. Both share this module's constants, so a
change to the format lands both halves at once, and the round-trip test in
``tests/applets/test_identity.py`` pins the pair.
"""

from __future__ import annotations

from punt_lux.domain.hub.applet_name_format import format_name, session_pid_from_name


class TestFormatName:
    """What the applet ``name`` field reads as."""

    def test_reads_as_tool_repo_hex_pid_and_program(self) -> None:
        assert format_name("lux", 0x2A, "lux-beads") == "lux · lux · #2a · lux-beads"

    def test_a_larger_pid_still_reads_as_lowercase_hex(self) -> None:
        assert format_name("lux", 0xDEADBEEF, "beads").endswith("#deadbeef · beads")


class TestSessionPidFromName:
    """What the Hub reads back off a declared name."""

    def test_recovers_the_pid_the_format_embedded(self) -> None:
        name = format_name("lux", 12345, "lux-beads")
        assert session_pid_from_name(name) == 12345

    def test_a_name_that_does_not_match_the_four_part_shape_has_no_pid(self) -> None:
        assert session_pid_from_name("not-four-parts") is None

    def test_a_non_hex_pid_part_has_no_pid(self) -> None:
        assert session_pid_from_name("lux · lux · #xyz · lux-beads") is None

    def test_a_missing_program_part_has_no_pid(self) -> None:
        assert session_pid_from_name("lux · lux · #4b97") is None
