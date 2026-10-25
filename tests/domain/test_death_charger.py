"""DeathCharger -- each recorded death is charged to its dial's own ledger, once."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.crash_attribution import (
    ATTRIBUTION_THRESHOLD,
    CrashAttribution,
)
from punt_lux.domain.hub.death_charger import DeathCharger
from punt_lux.domain.hub.dial_death import DialDeath
from punt_lux.domain.ids import SceneId
from tests.dial_double import fake_dial

if TYPE_CHECKING:
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord
    from punt_lux.domain.hub.replicator_ports import ClientProvider


@final
class _Clients:
    """Hands over the deaths it was given, once."""

    _deaths: list[DialDeath]
    __slots__ = ("_deaths",)

    def __new__(cls, *deaths: DialDeath) -> Self:
        self = super().__new__(cls)
        self._deaths = list(deaths)
        return self

    def take_deaths(self) -> tuple[DialDeath, ...]:
        taken, self._deaths = tuple(self._deaths), []
        return taken


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
    return DialDeath(fake_dial(), frozenset(SceneId(s) for s in scenes), "pair-1")


def _charger(*deaths: DialDeath) -> tuple[DeathCharger, CrashAttribution, _Port]:
    port = _Port()
    attribution = CrashAttribution(port, lambda: 0.0)
    clients = cast("ClientProvider", _Clients(*deaths))
    return DeathCharger(clients, attribution), attribution, port


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
