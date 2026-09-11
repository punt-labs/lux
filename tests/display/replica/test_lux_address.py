"""Unit tests for LuxAddress/Rung — value types for the Rung-3 identity path."""

from __future__ import annotations

import pytest

from punt_lux.display.replica.lux_address import LuxAddress, Rung
from punt_lux.domain.id_separator import ID_SEPARATOR


def _address(
    *,
    hub_key: str = "pembroke\x1f123",
    hub_label: str = "pembroke",
    connection_key: str = "vox-session",
    connection_label: str = "lux",
    leaf_key: str = "music-player",
    leaf_label: str = "Vox",
) -> LuxAddress:
    return LuxAddress(
        hub=Rung(hub_key, hub_label),
        connection=Rung(connection_key, connection_label),
        leaf=Rung(leaf_key, leaf_label),
    )


class TestHiddenId:
    def test_joins_every_rungs_key_on_the_unit_separator(self) -> None:
        addr = _address(hub_key="h", connection_key="c", leaf_key="l")
        assert addr.hidden_id == "h\x1fc\x1fl"

    def test_never_elides_a_rung_from_the_hidden_id(self) -> None:
        addr = _address(hub_key="h", connection_key="c", leaf_key="l")
        # Even though title() would drop both higher rungs when unambiguous,
        # the hidden id always carries all three -- it is never a display
        # decision.
        assert addr.hidden_id.count("\x1f") == 2

    def test_two_addresses_with_the_same_keys_are_equal(self) -> None:
        assert _address() == _address()

    def test_two_addresses_differing_only_in_leaf_key_are_not_equal(self) -> None:
        assert _address(leaf_key="a") != _address(leaf_key="b")


class TestTitle:
    def test_shows_only_the_leaf_when_nothing_is_ambiguous(self) -> None:
        addr = _address(leaf_label="Vox")
        title = addr.title(hub_ambiguous=False, connection_ambiguous=False)
        assert title == "Vox"

    def test_prefixes_the_connection_label_when_connection_is_ambiguous(self) -> None:
        addr = _address(connection_label="lux (2)", leaf_label="Vox")
        title = addr.title(hub_ambiguous=False, connection_ambiguous=True)
        assert title == "lux (2) :: Vox"

    def test_prefixes_both_higher_rungs_when_both_are_ambiguous(self) -> None:
        addr = _address(
            hub_label="pembroke", connection_label="lux (2)", leaf_label="Vox"
        )
        title = addr.title(hub_ambiguous=True, connection_ambiguous=True)
        assert title == "pembroke :: lux (2) :: Vox"

    def test_can_show_the_hub_alone_without_the_connection(self) -> None:
        addr = _address(hub_label="pembroke", leaf_label="Vox")
        title = addr.title(hub_ambiguous=True, connection_ambiguous=False)
        assert title == "pembroke :: Vox"

    def test_orders_rungs_outermost_first(self) -> None:
        addr = _address(hub_label="A", connection_label="B", leaf_label="C")
        title = addr.title(hub_ambiguous=True, connection_ambiguous=True)
        assert title == "A :: B :: C"


class TestSeparatorRejection:
    """An embedded separator would let two distinct triples collide."""

    def test_rejects_a_connection_key_carrying_the_separator(self) -> None:
        with pytest.raises(ValueError, match="connection"):
            _address(connection_key=f"c{ID_SEPARATOR}evil")

    def test_rejects_a_leaf_key_carrying_the_separator(self) -> None:
        with pytest.raises(ValueError, match="leaf"):
            _address(leaf_key=f"l{ID_SEPARATOR}evil")

    def test_the_hub_key_is_exempt_since_it_already_carries_the_separator(
        self,
    ) -> None:
        """HubId.wire_token joins hostname and pid with this same separator."""
        addr = _address(hub_key=f"pembroke{ID_SEPARATOR}123")
        assert addr.hub.key == f"pembroke{ID_SEPARATOR}123"
