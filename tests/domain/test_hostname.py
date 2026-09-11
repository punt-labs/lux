"""Hostname -- the ASCII, lowercase-canonical host value type composed by HubId."""

from __future__ import annotations

import pytest

from punt_lux.domain.hostname import Hostname


def test_value_is_the_hostname_string() -> None:
    assert Hostname("pembroke").value == "pembroke"


def test_hostname_is_lowercased_at_construction() -> None:
    assert Hostname("HUB1.EXAMPLE.COM").value == "hub1.example.com"


def test_a_non_ascii_hostname_is_rejected() -> None:
    # Unicode-aware folding (str.casefold()) would be needed to compare a
    # non-ASCII hostname case-insensitively, and casefold collides distinct
    # strings ("faß" -> "fass") -- exactly the masquerade this rejection
    # exists to close instead of trading for.
    with pytest.raises(ValueError, match="must be ASCII"):
        Hostname("faß.example")


def test_is_frozen() -> None:
    # A Hostname is (composed into) a hashable registry key; a
    # post-construction write would corrupt an already-inserted key's hash.
    hostname = Hostname("pembroke")
    with pytest.raises(AttributeError):
        hostname.value = "other"  # type: ignore[misc]  # proving frozen=True raises


class TestCaseInsensitiveIdentity:
    """A declared-hostname case difference must never mint two distinct hosts."""

    def test_two_hostnames_differing_only_in_case_are_equal(self) -> None:
        assert Hostname("HUB1.EXAMPLE.COM") == Hostname("hub1.example.com")

    def test_two_hostnames_differing_only_in_case_hash_equal(self) -> None:
        assert hash(Hostname("HUB1.EXAMPLE.COM")) == hash(Hostname("hub1.example.com"))

    def test_two_distinct_hostnames_are_not_equal(self) -> None:
        assert Hostname("pembroke") != Hostname("otherhost")
