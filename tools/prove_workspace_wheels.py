"""Install built wheels into clean, disjoint environments and prove isolation."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


def run(command: list[str]) -> None:
    """Run an acceptance command without inheriting the source checkout as cwd."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    subprocess.run(command, check=True, cwd=Path.home(), env=env, timeout=300)


def prove(wheels: Path, output: Path) -> None:
    """Install only local artifacts for the three synchronized distributions."""
    built = {}
    for name in ("punt_lux", "punt_lux_client", "punt_service"):
        matches = list(wheels.glob(f"{name}-*.whl"))
        if len(matches) != 1:
            raise ValueError(f"Expected one {name} wheel, found {len(matches)}")
        built[name] = matches[0].resolve()
    output.mkdir(parents=True, exist_ok=True)
    for label, names in (
        ("client", ("punt_lux_client",)),
        ("service", ("punt_service",)),
        ("full", ("punt_lux", "punt_lux_client", "punt_service")),
    ):
        environment = output / label
        if environment.exists():
            raise ValueError(f"Proof environment must be fresh: {environment}")
        run(["uv", "venv", "--python", "3.13", str(environment)])
        python = environment / "bin/python"
        run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                *[str(built[n]) for n in names],
            ]
        )
        if label == "client":
            run(
                [
                    str(python),
                    "-I",
                    "-c",
                    """
import importlib.metadata as metadata
import importlib.util
import sys
import punt_lux.client
import punt_lux.wire.model
import punt_lux.wire.operations
import punt_lux.applets
import punt_lux.kernel
forbidden = ('punt_lux.hub', 'punt_lux.display', 'punt_lux.pty',
             'punt_lux.beads', 'punt_lux.service', 'punt_service',
             'fastapi', 'starlette', 'mcp', 'mcp_types', 'fastmcp')
assert not any(n == p or n.startswith(p + '.') for n in sys.modules for p in forbidden)
assert not any(importlib.util.find_spec(n) is not None for n in forbidden)
installed = {d.metadata['Name'].lower() for d in metadata.distributions()}
assert not installed.intersection({
    'punt-lux', 'punt-service', 'fastapi', 'starlette', 'mcp', 'fastmcp'})
print('CLIENT-ONLY: client, wire, kernel and helpers import; '
      'forbidden modules absent: PASS')
""",
                ]
            )
        elif label == "service":
            run(
                [
                    str(python),
                    "-I",
                    "-c",
                    """
import importlib.metadata as metadata
import sys
from punt_service import ServiceManager, ServiceSpec
assert not any(n == 'punt_lux' or n.startswith('punt_lux.') for n in sys.modules)
installed = {d.metadata['Name'].lower() for d in metadata.distributions()}
assert installed == {'punt-service'}
print('SERVICE-ONLY: ServiceManager and ServiceSpec import; '
      'no Lux or third-party distributions: PASS')
""",
                ]
            )
        else:
            run([str(environment / "bin/lux"), "--version"])
            run([str(python), "-I", "-P", "-m", "punt_lux.cli", "--help"])
            print(
                "FULL: local wheels provide lux --version and "
                "python -P -m punt_lux.cli --help: PASS",
                flush=True,
            )


def main() -> None:
    """Run the wheel acceptance proof against a built artifact directory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheels", type=Path, default=Path("dist"))
    parser.add_argument("--output", type=Path, default=Path(".tmp/wheel-proof"))
    args = parser.parse_args()
    prove(args.wheels.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
