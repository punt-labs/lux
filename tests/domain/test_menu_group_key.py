"""MenuGroupKey — the submenu one connection contributes to (DES-067).

An applet connection groups by ``(repo, session_pid)``; every other kind is
its own group keyed by connection id. Two applet connections in one session
compare equal; two applet connections in different sessions do not; two
identical labels across different kinds are not one submenu either. Headless
applets (``repo=None``) group across siblings in one session and stay
distinct across sessions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.applet_name_format import format_name
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.menu_group_key import MenuGroupKey
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    import pytest


def _applet(
    pid: int,
    program: str,
    *,
    # None models the headless applet path: ClientIdentity allows the absence,
    # and MenuGroupKey.of substitutes "" so siblings in one headless session
    # still share a key.
    repo: str | None = "/w/lux",
) -> ClientIdentity:
    repo_name = repo.rsplit("/", 1)[-1] if repo else "lux"
    return ClientIdentity(
        kind="applet", name=format_name(repo_name, pid, program), repo=repo
    )


class TestApplet:
    """Applet connections in one session share a submenu."""

    def test_two_applets_in_one_session_share_a_key(self) -> None:
        beads = _applet(12345, "lux-beads")
        vox = _applet(12345, "vox-panel")

        assert MenuGroupKey.of(ConnectionId("a"), beads) == MenuGroupKey.of(
            ConnectionId("b"), vox
        )

    def test_two_applets_in_different_sessions_do_not_share(self) -> None:
        first = _applet(111, "lux-beads")
        second = _applet(222, "lux-beads")

        assert MenuGroupKey.of(ConnectionId("a"), first) != MenuGroupKey.of(
            ConnectionId("b"), second
        )

    def test_the_key_is_hashable(self) -> None:
        beads = _applet(12345, "lux-beads")
        vox = _applet(12345, "vox-panel")

        siblings = {
            MenuGroupKey.of(ConnectionId("a"), beads),
            MenuGroupKey.of(ConnectionId("b"), vox),
        }
        assert len(siblings) == 1


class TestNonApplet:
    """Every non-applet is its own submenu, whatever its label."""

    def test_two_mcp_sessions_are_two_keys_even_at_the_same_label(self) -> None:
        first = ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")
        second = ClientIdentity(kind="mcp-session", name="claude", repo="/w/lux")

        assert MenuGroupKey.of(ConnectionId("a"), first) != MenuGroupKey.of(
            ConnectionId("b"), second
        )

    def test_a_daemon_is_its_own_key(self) -> None:
        voxd = ClientIdentity(kind="app", name="voxd")

        assert MenuGroupKey.of(ConnectionId("a"), voxd) != MenuGroupKey.of(
            ConnectionId("b"), voxd
        )


class TestHeadlessApplet:
    """A headless applet (``repo=None``) still groups by session across siblings.

    ``menu_label`` falls back to the four-part ``name`` when ``repo`` is
    absent, and the name carries the program token — so two siblings would
    read as two different labels and split. Keying on ``repo`` directly
    (empty string for absent) keeps them under one submenu.
    """

    def test_two_headless_applets_in_one_session_share_a_key(self) -> None:
        beads = _applet(12345, "lux-beads", repo=None)
        vox = _applet(12345, "vox-panel", repo=None)

        assert MenuGroupKey.of(ConnectionId("a"), beads) == MenuGroupKey.of(
            ConnectionId("b"), vox
        )

    def test_two_headless_applets_in_different_sessions_do_not_share(self) -> None:
        first = _applet(111, "lux-beads", repo=None)
        second = _applet(222, "lux-beads", repo=None)

        assert MenuGroupKey.of(ConnectionId("a"), first) != MenuGroupKey.of(
            ConnectionId("b"), second
        )

    def test_a_headless_and_a_repo_applet_do_not_share(self) -> None:
        """A headless session and a repo session don't accidentally merge."""
        headless = _applet(12345, "lux-beads", repo=None)
        repoed = _applet(12345, "lux-beads", repo="/w/lux")

        assert MenuGroupKey.of(ConnectionId("a"), headless) != MenuGroupKey.of(
            ConnectionId("b"), repoed
        )


class TestDes064StillFiresForDifferentSessions:
    """Two DIFFERENT sessions in the same repo remain two distinct keys.

    DES-067 stops the collision-numbering for two applets in ONE session;
    it does not touch the case DES-064 was designed for. Session A's beads
    and session B's beads still ask the roster for two names — the numbering
    is what tells them apart.
    """

    def test_same_program_different_sessions_are_two_keys(self) -> None:
        session_a = _applet(0xAAAA, "lux-beads")
        session_b = _applet(0xBBBB, "lux-beads")

        assert MenuGroupKey.of(ConnectionId("a"), session_a) != MenuGroupKey.of(
            ConnectionId("b"), session_b
        )


class TestFallbackWarning:
    """A malformed applet name that bypasses model validation surfaces in the log.

    The ClientIdentity model validator rejects a malformed applet name at
    construction, so in production this path only fires when a caller bypassed
    pydantic (test fixture via ``model_construct``, a legacy wire payload
    decoded outside the model). It falls back to per-connection grouping and
    logs a warning so the failure shows up in luxd's log instead of a silent
    misgrouping.
    """

    def test_a_malformed_applet_name_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        malformed = ClientIdentity.model_construct(
            kind="applet", name="not-four-parts", repo="/w/lux"
        )
        logger_name = "punt_lux.domain.hub.menu_group_key"
        with caplog.at_level(logging.WARNING, logger=logger_name):
            MenuGroupKey.of(ConnectionId("a"), malformed)

        assert any(
            "unparseable applet name" in record.message
            and record.levelno == logging.WARNING
            for record in caplog.records
        )

    def test_a_malformed_applet_falls_back_to_per_connection_grouping(self) -> None:
        malformed = ClientIdentity.model_construct(
            kind="applet", name="not-four-parts", repo="/w/lux"
        )
        assert MenuGroupKey.of(ConnectionId("a"), malformed) != MenuGroupKey.of(
            ConnectionId("b"), malformed
        )
