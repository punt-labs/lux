"""Centralized read/write for .lux/config.md YAML frontmatter.

Python components that need config (e.g. server, CLI) import from here.
Shell hooks (e.g. ``hooks/*.sh``) read the same file via their own
bash-based reader.  The canonical path is ``.lux/config.md`` in the
repo root.  All fields return safe defaults when the file is missing.

Only the YAML frontmatter block (between the first ``---`` and the
next ``---``) is parsed.  Markdown body content is ignored.
"""

from __future__ import annotations

import functools
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(".lux/config.md")

ALLOWED_CONFIG_KEYS: frozenset[str] = frozenset({"display"})

_FIELD_RE = re.compile(r'^([a-z_]+):\s*"?([^"\n]*)"?\s*$', re.MULTILINE)


def _extract_frontmatter(text: str) -> str:
    """Extract YAML frontmatter block from text.

    Returns the text between the first ``---`` and the next ``---``,
    or empty string if no valid frontmatter is found.
    """
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end == -1:
        return ""
    return text[3:end]


@functools.lru_cache(maxsize=1)
def resolve_config_path() -> Path:
    """Resolve .lux/config.md at the main repo root (worktree-safe).

    Uses ``git rev-parse --git-common-dir`` to find the shared git
    directory, then resolves to its parent.  Falls back to cwd-relative
    ``.lux/config.md`` when git is unavailable or not in a repo.

    Result is cached for the process lifetime.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        git_common = result.stdout.strip()
        if git_common:
            return Path(git_common).resolve().parent / ".lux" / "config.md"
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pass
    return DEFAULT_CONFIG_PATH


@dataclass(frozen=True)
class LuxConfig:
    """Snapshot of all config fields from .lux/config.md."""

    display: str  # "y" | "n"


def read_field(
    field: str,
    config_path: Path | None = None,
) -> str | None:
    """Read a single YAML frontmatter field.  Returns None if absent."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    frontmatter = _extract_frontmatter(text)
    if not frontmatter:
        return None
    pattern = re.compile(
        rf"^{re.escape(field)}:\s*\"?([^\"\n]*)\"?\s*$",
        re.MULTILINE,
    )
    match = pattern.search(frontmatter)
    if match and match.group(1).strip():
        return match.group(1).strip()
    return None


def read_config(config_path: Path | None = None) -> LuxConfig:
    """Read all config fields.  Returns defaults when file is missing."""
    path = config_path or DEFAULT_CONFIG_PATH
    fields: dict[str, str] = {}
    if path.exists():
        text = path.read_text(encoding="utf-8")
        frontmatter = _extract_frontmatter(text)
        for match in _FIELD_RE.finditer(frontmatter):
            key = match.group(1)
            val = match.group(2).strip()
            if val:
                fields[key] = val

    display = fields.get("display", "n")
    if display not in ("y", "n"):
        display = "n"

    return LuxConfig(display=display)


def write_field(
    key: str,
    value: str,
    config_path: Path | None = None,
) -> None:
    """Write a single YAML frontmatter field to .lux/config.md.

    Updates the field in-place if present, or inserts it before the
    closing ``---`` if absent.  Creates the file with minimal
    frontmatter if it does not exist.  Only operates within the
    frontmatter block — markdown body is preserved.
    """
    if key not in ALLOWED_CONFIG_KEYS:
        allowed = ", ".join(sorted(ALLOWED_CONFIG_KEYS))
        msg = f"Unknown config key '{key}'. Allowed: {allowed}"
        raise ValueError(msg)

    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    replacement = f'{key}: "{value}"'

    if not path.exists():
        path.write_text(
            f"---\n{replacement}\n---\n",
            encoding="utf-8",
        )
        return

    text = path.read_text(encoding="utf-8")

    if not text.startswith("---"):
        logger.warning("Malformed config (no opening ---): %s", path)
        text = f"---\n{replacement}\n---\n"
        path.write_text(text, encoding="utf-8")
        return

    # Find the closing fence (first \n--- after the opening ---)
    end = text.find("\n---", 3)
    if end == -1:
        logger.warning("Malformed config (no closing ---): %s", path)
        text = f"---\n{replacement}\n---\n"
        path.write_text(text, encoding="utf-8")
        return

    frontmatter = text[3:end]
    body = text[end + 4 :]  # after "\n---"

    field_re = re.compile(
        rf"^{re.escape(key)}:\s*\"?[^\"\n]*\"?\s*$",
        re.MULTILINE,
    )

    if field_re.search(frontmatter):
        frontmatter = field_re.sub(replacement, frontmatter)
    else:
        frontmatter = frontmatter.rstrip("\n") + f"\n{replacement}"

    text = f"---{frontmatter}\n---{body}"
    if not text.endswith("\n"):
        text += "\n"

    path.write_text(text, encoding="utf-8")
    logger.info("Config: set %s = %r in %s", key, value, path)
