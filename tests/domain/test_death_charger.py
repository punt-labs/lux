"""DeathCharger -- each recorded death is charged to its dial's own ledger, once."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

import pytest

from punt_lux.domain.hub.crash_attribution import (
    ATTRIBUTION_THRESHOLD,
    CrashAttribution,
)
from punt_lux.domain.hub.death_charger import DeathCharger
from punt_lux.domain.hub.dial_death import DialDeath
from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord


@final
class _Deaths:
    """Hands over the deaths it was given, once each, and takes one back."""

    _deaths: list[DialDeath]
    __slots__ = ("_deaths",)

    def __new__(cls, *deaths: DialDeath) -> Self:
        self = super().__new__(cls)
        self._deaths = list(deaths)
        return self

    def take(self) -> DialDeath | None:
        return self._deaths.pop(0) if self._deaths else None

    def put_back(self, death: DialDeath) -> None:
        self._deaths.insert(0, death)


@final
class _Port:
    """Records quarantines."""

    quarantined: dict[SceneId, QuarantineRecord]
    __slots__ = ("quarantined",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.quarantined = {}
        return self

    def quarantine(self, scene_id: SceneId, record: QuarantineRecord) -> None:
        self.quarantined[scene_id] = record

    def is_quarantined(self, scene_id: SceneId) -> bool:
        return scene_id in self.quarantined

    def add_quarantine_cleared_observer(self, observer: object) -> None:
        """Unused."""


def _death(*scenes: str) -> DialDeath:
    return DialDeath(frozenset(SceneId(s) for s in scenes), "pair-1", "display")


def _charger(*deaths: DialDeath) -> tuple[DeathCharger, CrashAttribution, _Port]:
    port = _Port()
    attribution = CrashAttribution(port, lambda: 0.0)
    return DeathCharger(_Deaths(*deaths), attribution), attribution, port


class TestCharging:
    def test_a_death_switches_the_replicator_to_isolation(self) -> None:
        charger, attribution, _port = _charger(_death("s1"))

        charger.charge()

        assert attribution.mode == "isolating"

    def test_no_death_charges_nothing(self) -> None:
        charger, attribution, _port = _charger()

        charger.charge()

        assert attribution.mode == "batching"

    def test_every_scene_in_a_ledger_takes_a_strike_and_none_outside_it(self) -> None:
        deaths = [_death("a", "b") for _ in range(ATTRIBUTION_THRESHOLD)]
        charger, _attribution, port = _charger(*deaths)

        charger.charge()

        assert set(port.quarantined) == {SceneId("a"), SceneId("b")}

    def test_a_scene_outside_the_ledger_is_never_charged(self) -> None:
        deaths = [_death("a") for _ in range(ATTRIBUTION_THRESHOLD)]
        charger, _attribution, port = _charger(*deaths)

        charger.charge()

        assert set(port.quarantined) == {SceneId("a")}

    def test_a_death_is_charged_once_however_often_the_charger_looks(self) -> None:
        charger, _attribution, port = _charger(_death("a"))

        charger.charge()
        charger.charge()

        assert port.quarantined == {}  # one strike, not two

    def test_the_quarantine_record_says_which_display_ended_the_dial(self) -> None:
        deaths = [_death("a") for _ in range(ATTRIBUTION_THRESHOLD)]
        charger, _attribution, port = _charger(*deaths)

        charger.charge()

        record = port.quarantined[SceneId("a")]
        assert record.render_error == "the display at pair-1 ended the connection"


@final
class _FailingOnceAttribution:
    """An attribution whose first charge raises, as a store invariant can."""

    charged: list[frozenset[SceneId]]
    _raised: bool
    __slots__ = ("_raised", "charged")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.charged = []
        self._raised = False
        return self

    def attribute_death(
        self, suspects: frozenset[SceneId], *, render_error: str | None = None
    ) -> frozenset[SceneId]:
        del render_error
        if not self._raised:
            self._raised = True
            msg = "the store refused"
            raise RuntimeError(msg)
        self.charged.append(suspects)
        return frozenset()


class TestWhenChargingOneDeathRaises:
    def test_it_goes_back_at_the_head_and_is_charged_at_the_next_look(self) -> None:
        attribution = _FailingOnceAttribution()
        deaths = _Deaths(_death("a"), _death("b"))
        charger = DeathCharger(deaths, cast("CrashAttribution", attribution))

        with pytest.raises(RuntimeError, match="refused"):
            charger.charge()
        charger.charge()

        assert attribution.charged == [
            frozenset({SceneId("a")}),
            frozenset({SceneId("b")}),
        ]

    def test_the_error_that_stopped_it_is_not_swallowed(self) -> None:
        attribution = _FailingOnceAttribution()
        charger = DeathCharger(_Deaths(_death("a")), cast("CrashAttribution", attribution))

        with pytest.raises(RuntimeError, match="the store refused"):
            charger.charge()
