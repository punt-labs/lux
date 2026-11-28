"""Read/write the local Lux display preference.

Only the YAML frontmatter block (between the first ``---`` and the
next ``---``) is parsed.  Markdown body content is ignored.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

logger = logging.getLogger(__name__)

ALLOWED_CONFIG_KEYS: frozenset[str] = frozenset({"display"})

_FRONTMATTER_RE = re.compile(r"^---(.*?)\n---", re.DOTALL)
_FIELD_RE = re.compile(r'^([a-z_]+):\s*"?([^"\n]*)"?\s*$', re.MULTILINE)


@dataclass(frozen=True, slots=True)
class LuxConfig:
    """Snapshot of the display preference."""

    display: Literal["y", "n"]


class ConfigManager:
    """Read and write a display preference in YAML frontmatter."""

    _config_path: Path

    def __new__(cls, config_path: Path) -> Self:
        """Bind the configuration path."""
        self = super().__new__(cls)
        self._config_path = config_path
        return self

    @property
    def path(self) -> Path:
        """Return the resolved config file path."""
        return self._config_path

    def _ensure_parent(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> LuxConfig:
        """Read the display setting, defaulting to off."""
        try:
            text = self._config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return LuxConfig(display="n")
        match = _FRONTMATTER_RE.match(text)
        frontmatter = match[1] if match else ""
        fields = {
            entry[1]: value
            for entry in _FIELD_RE.finditer(frontmatter)
            if (value := entry[2].strip())
        }
        return LuxConfig(display="y" if fields.get("display") == "y" else "n")

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
        self._ensure_parent()

        replacement = f'{key}: "{value}"'

        if not path.exists():
            path.write_text(
                f"---\n{replacement}\n---\n",
                encoding="utf-8",
            )
            return

        original = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(original)
        if match is None:
            logger.warning("Malformed config frontmatter: %s", path)
            path.write_text(f"---\n{replacement}\n---\n", encoding="utf-8")
            return

        frontmatter = match[1]
        body = original[match.end() :]

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

        if text != original:
            path.write_text(text, encoding="utf-8")
            logger.info("Config: set %s = %r in %s", key, value, path)
