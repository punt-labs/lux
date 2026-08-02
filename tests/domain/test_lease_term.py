"""LeaseTerm — a lease either lapses after some length, or never lapses.

Two states, not one number with a magic value in it. Written as a float, "never"
is ``inf``, which pydantic serialises to ``null`` and then refuses to read back:
one permanent daemon cost every structured caller the whole client roster. These
tests hold the two states apart and prove both survive JSON.
"""

from __future__ import annotations

import math

import pytest
from pydantic import BaseModel, ValidationError

from punt_lux.domain.hub.lease_term import (
    ExpiringLease,
    LeaseTerm,
    LeaseTerms,
    PermanentLease,
)
from punt_lux.domain.hub.session_lease import SessionLease


class _Carried(BaseModel):
    """A model carrying a lease, standing in for any response that reports one."""

    lease: LeaseTerm


def _round_trip(term: LeaseTerm) -> LeaseTerm:
    """Serialise a carried lease the way a response does, and parse it back."""
    return _Carried.model_validate_json(_Carried(lease=term).model_dump_json()).lease


class TestWhereALengthBecomesAState:
    """The one place inf stops being a number: everything else gets a state."""

    def test_an_endless_length_is_the_permanent_state(self) -> None:
        assert LeaseTerms.of(math.inf) == PermanentLease()

    def test_any_finite_length_is_the_expiring_state(self) -> None:
        assert LeaseTerms.of(90.0) == ExpiringLease(seconds=90.0)

    def test_the_kind_lengths_the_hub_holds_map_onto_the_two_states(self) -> None:
        """The lease keeps the float it does arithmetic on; the roster gets a state."""
        assert LeaseTerms.of(SessionLease.for_kind("app", 0.0).ttl_seconds) == (
            PermanentLease()
        )
        assert LeaseTerms.of(SessionLease.for_kind("cli", 0.0).ttl_seconds) == (
            ExpiringLease(seconds=90.0)
        )


class TestHowALeaseReads:
    def test_a_lease_that_never_lapses_reads_as_permanent(self) -> None:
        assert PermanentLease().rendered() == "permanent"

    def test_an_expiring_lease_reads_as_the_span_it_runs(self) -> None:
        assert ExpiringLease(seconds=60.0).rendered() == "1m 00s"
        assert ExpiringLease(seconds=1800.0).rendered() == "30m 00s"

    def test_a_lease_of_no_length_is_refused(self) -> None:
        """A lease that lapses on arrival is a bad declaration, not a short one."""
        with pytest.raises(ValidationError):
            ExpiringLease(seconds=0.0)


class TestAcrossTheWire:
    """The failure this type exists to close: JSON must carry both states."""

    def test_a_permanent_lease_survives_the_round_trip(self) -> None:
        assert _round_trip(PermanentLease()) == PermanentLease()

    def test_an_expiring_lease_survives_the_round_trip_with_its_length(self) -> None:
        assert _round_trip(ExpiringLease(seconds=90.0)) == ExpiringLease(seconds=90.0)

    def test_the_two_states_are_discriminated_by_kind(self) -> None:
        assert _Carried(lease=PermanentLease()).model_dump() == {
            "lease": {"kind": "permanent"}
        }
        assert _Carried(lease=ExpiringLease(seconds=90.0)).model_dump() == {
            "lease": {"kind": "expiring", "seconds": 90.0}
        }

    def test_a_lease_naming_no_kind_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            _Carried.model_validate({"lease": {"seconds": 90.0}})
