"""The applet name format the Hub reads back — the coupling both halves stand on.

The writer sits on :class:`AppletIdentity.for_session` and the reader on
:func:`session_pid_of` here. Both share this module's constants, so a change
to the format lands both halves at once, and the round-trip test in
``tests/applets/test_identity.py`` pins the pair.
"""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.applet_name_format import format_name, session_pid_of
from punt_lux.domain.hub.client_identity import ClientIdentity


class TestFormatName:
    """What the applet ``name`` field reads as."""

    def test_reads_as_tool_repo_hex_pid_and_program(self) -> None:
        assert format_name("lux", 0x2A, "lux-beads") == "lux · lux · #2a · lux-beads"

    def test_a_larger_pid_still_reads_as_lowercase_hex(self) -> None:
        assert format_name("lux", 0xDEADBEEF, "beads").endswith("#deadbeef · beads")


class TestSessionPidOf:
    """What the Hub reads back off a declared identity."""

    def test_recovers_the_pid_the_format_embedded(self) -> None:
        client = ClientIdentity(
            kind="applet",
            name=format_name("lux", 12345, "lux-beads"),
            repo="/w/lux",
        )
        assert session_pid_of(client) == 12345

    def test_a_non_applet_has_no_pid(self) -> None:
        for kind in ("mcp-session", "cli", "app"):
            client = ClientIdentity(kind=kind, name="not-an-applet")
            assert session_pid_of(client) is None

    def test_a_malformed_applet_name_is_rejected(self) -> None:
        malformed = ClientIdentity(kind="applet", name="not-four-parts", repo="/w/lux")
        with pytest.raises(ValueError, match="malformed applet name"):
            session_pid_of(malformed)

    def test_a_non_hex_pid_is_rejected(self) -> None:
        malformed = ClientIdentity(
            kind="applet",
            name="lux · lux · #xyz · lux-beads",
            repo="/w/lux",
        )
        with pytest.raises(ValueError, match="malformed applet name"):
            session_pid_of(malformed)
