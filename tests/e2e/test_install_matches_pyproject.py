"""e2e: every ``[project.scripts]`` entry point exists after a real install.

Companion to ``test_make_restart.py``: parses ``pyproject.toml`` directly (no
hardcoded executable list to drift from the source of truth) and asserts every
declared console script is a real file under ``~/.local/bin``, and every
:class:`~punt_lux.service.ServiceSpec` resolves to an existing binary. This is
the class of defect lux-5i3n fixed for the display -- a spec whose
``binary_name`` names an executable ``[project.scripts]`` never declares.

Run via ``make test-e2e`` -- requires a prior real ``uv tool install``
(``make install`` or the sequence in ``test_make_restart.py``).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from punt_lux.service import DISPLAY_SPEC, HUB_SPEC

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _script_names() -> tuple[str, ...]:
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    scripts: dict[str, str] = data["project"]["scripts"]
    return tuple(scripts)


def test_every_pyproject_script_exists_after_install() -> None:
    """Every name in [project.scripts] resolves to a file in ~/.local/bin."""
    local_bin = Path.home() / ".local" / "bin"
    names = _script_names()
    assert names, "pyproject.toml declares no [project.scripts] entries"
    for name in names:
        path = local_bin / name
        assert path.exists(), (
            f"{name} declared in [project.scripts] but missing from {local_bin} "
            "-- run 'uv tool install --force <wheel>[display]'"
        )


def test_every_service_spec_binary_name_is_a_declared_script() -> None:
    """A ServiceSpec must name a binary [project.scripts] actually ships."""
    names = _script_names()
    for spec in (HUB_SPEC, DISPLAY_SPEC):
        assert spec.binary_name in names, (
            f"{spec.display_name}'s binary_name {spec.binary_name!r} is not a "
            f"[project.scripts] entry point: {names}"
        )


def test_every_service_spec_resolves_to_an_existing_binary() -> None:
    """resolve_exec_args() must find the real, installed binary on disk."""
    for spec in (HUB_SPEC, DISPLAY_SPEC):
        args = spec.resolve_exec_args()
        assert Path(args[0]).exists(), (
            f"{spec.display_name}'s resolved binary {args[0]} does not exist"
        )
