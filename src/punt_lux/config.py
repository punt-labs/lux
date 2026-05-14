"""Centralized read/write for .punt-labs/lux.md YAML frontmatter.

Python components that need config (e.g. server, CLI) import from here.
Shell hooks (e.g. ``hooks/*.sh``) read the same file via their own
bash-based reader.  The canonical path is ``.punt-labs/lux.md`` in the
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
from typing import Self

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(".punt-labs/lux.md")

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
    """Resolve .punt-labs/lux.md at the main repo root (worktree-safe).

    Uses ``git rev-parse --git-common-dir`` to find the shared git
    directory, then resolves to its parent.  Falls back to cwd-relative
    ``.punt-labs/lux.md`` when git is unavailable or not in a repo.

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
            return Path(git_common).resolve().parent / ".punt-labs" / "lux.md"
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pass
    return DEFAULT_CONFIG_PATH


@dataclass(frozen=True, slots=True)
class LuxConfig:
    """Snapshot of all config fields from .punt-labs/lux.md."""

    display: str  # "y" | "n"


class ConfigManager:
    """Read and write .punt-labs/lux.md YAML frontmatter fields."""

    _config_path: Path

    def __new__(cls, config_path: Path | None = None) -> Self:
        self = super().__new__(cls)
        self._config_path = config_path or resolve_config_path()
        return self

    @property
    def path(self) -> Path:
        """Return the resolved config file path."""
        return self._config_path

    def read(self) -> LuxConfig:
        """Read all config fields. Return defaults when file is missing."""
        fields: dict[str, str] = {}
        if self._config_path.exists():
            text = self._config_path.read_text(encoding="utf-8")
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

    def read_field(self, field: str) -> str | None:
        """Read a single YAML frontmatter field. Return None if absent."""
        if not self._config_path.exists():
            return None
        text = self._config_path.read_text(encoding="utf-8")
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

    def write_field(self, key: str, value: str) -> None:
        """Write a single YAML frontmatter field to the config file.

        Update the field in-place if present, or insert it before the
        closing ``---`` if absent. Create the file with minimal
        frontmatter if it does not exist. Only operate within the
        frontmatter block -- markdown body is preserved.
        """
        if key not in ALLOWED_CONFIG_KEYS:
            allowed = ", ".join(sorted(ALLOWED_CONFIG_KEYS))
            msg = f"Unknown config key '{key}'. Allowed: {allowed}"
            raise ValueError(msg)

        path = self._config_path
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
