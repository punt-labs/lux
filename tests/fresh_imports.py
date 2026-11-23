"""Fresh-process package imports and removed-path assertions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"


def package_modules(package: str) -> list[str]:
    modules = sorted(
        ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
        for path in _SRC.joinpath(*package.split(".")).rglob("*.py")
    )
    assert modules, f"No Python modules found for {package}"
    return modules


def assert_importable(module: str) -> None:
    _assert_fresh_code(f"import importlib; importlib.import_module({module!r})")


def assert_not_importable(module: str) -> None:
    _assert_fresh_code(
        "import importlib\n"
        "try:\n"
        f"    importlib.import_module({module!r})\n"
        "except ModuleNotFoundError as exc:\n"
        f"    if exc.name != {module!r}:\n"
        "        raise\n"
        "else:\n"
        f"    raise AssertionError('Removed module still imports: ' + {module!r})\n"
    )


def assert_isolated(module: str, forbidden: tuple[str, ...]) -> None:
    _assert_fresh_code(
        "import importlib, sys\n"
        f"importlib.import_module({module!r})\n"
        f"prefixes = {forbidden!r}\n"
        "loaded = sorted(name for name in sys.modules if any(\n"
        "    name == prefix or name.startswith(prefix + '.')\n"
        "    for prefix in prefixes))\n"
        "assert not loaded, f'Forbidden modules loaded: {loaded}'\n"
    )


def _assert_fresh_code(code: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
