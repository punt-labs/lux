"""Synchronize all published manifests and internal dependency pins at release time."""

from __future__ import annotations

import argparse
import re
import tomllib
from pathlib import Path


def synchronize(root: Path, version: str | None = None) -> list[Path]:
    """Prepare every manifest before writing any change; leave locking to uv."""
    paths = [
        root / "pyproject.toml",
        *(
            root / "packages" / name / "pyproject.toml"
            for name in ("punt-lux-client", "punt-service")
        ),
    ]
    texts = {path: path.read_text() for path in paths}
    projects = {path: tomllib.loads(text)["project"] for path, text in texts.items()}
    target = version or projects[paths[0]]["version"]
    if not isinstance(target, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?", target
    ):
        raise ValueError(f"Invalid release version: {target}")
    prepared = {}
    for path, text in texts.items():
        current = projects[path]["version"]
        text, count = re.subn(
            r'(?m)^version = "' + re.escape(current) + '"$',
            f'version = "{target}"',
            text,
        )
        if count != 1:
            raise ValueError(f"Expected one static project version: {path}")
        if path == paths[0]:
            for name in ("punt-lux-client", "punt-service"):
                text, count = re.subn(
                    r'"' + name + r'==[^\"]+"', f'"{name}=={target}"', text
                )
                if count != 1:
                    raise ValueError(f"Expected one synchronized pin for {name}")
        prepared[path] = text
    changed = []
    for path, text in prepared.items():
        if text != texts[path]:
            path.write_text(text)
            changed.append(path)
    return changed


def main() -> None:
    """Synchronize with the root's bumped version, or supply a new version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", nargs="?")
    args = parser.parse_args()
    for path in synchronize(Path(__file__).resolve().parents[1], args.version):
        print(path)


if __name__ == "__main__":
    main()
