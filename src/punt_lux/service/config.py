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

from punt_lux.service.repo_activation import PERSONAL, Checkout

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = PERSONAL / "display.local.md"
LEGACY_CONFIG_PATH = Path(".punt-labs/lux.md")

ALLOWED_CONFIG_KEYS: frozenset[str] = frozenset({"display"})

_FIELD_RE = re.compile(r'^([a-z_]+):\s*"?([^"\n]*)"?\s*$', re.MULTILINE)


def resolve_config_path() -> Path:
    """Resolve the display preference in the main checkout."""
    try:
        return Checkout.resolve(Path.cwd(), main=True).root / DEFAULT_CONFIG_PATH
    except ValueError:
        return DEFAULT_CONFIG_PATH


@dataclass(frozen=True, slots=True)
class LuxConfig:
    """Snapshot of the display preference."""

    display: Literal["y", "n"]


class ConfigManager:
    """Read and write a display preference in YAML frontmatter."""

    _config_path: Path

    def __new__(cls, config_path: Path | None = None) -> Self:
        """Bind the configuration path, resolving the default when omitted."""
        self = super().__new__(cls)
        self._config_path = config_path or resolve_config_path()
        return self

    @property
    def path(self) -> Path:
        """Return the resolved config file path."""
        return self._config_path

    @classmethod
    def for_display(cls, root: Path, *, main: Path | None = None) -> Self:
        """Prefer the main checkout's local preference, then legacy files."""
        main = root if main is None else main
        local = main / DEFAULT_CONFIG_PATH
        legacy = root / LEGACY_CONFIG_PATH
        return cls(
            next(
                (path for path in (local, legacy) if path.exists()),
                main / LEGACY_CONFIG_PATH,
            )
        )

    @staticmethod
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

    def read(self) -> LuxConfig:
        """Read all config fields. Return defaults when file is missing."""
        fields: dict[str, str] = {}
        if self._config_path.exists():
            text = self._config_path.read_text(encoding="utf-8")
            frontmatter = self._extract_frontmatter(text)
            for match in _FIELD_RE.finditer(frontmatter):
                key = match.group(1)
                val = match.group(2).strip()
                if val:
                    fields[key] = val

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
        path.parent.mkdir(parents=True, exist_ok=True)

        replacement = f'{key}: "{value}"'

        if not path.exists():
            path.write_text(
                f"---\n{replacement}\n---\n",
                encoding="utf-8",
            )
            return

        original = path.read_text(encoding="utf-8")
        text = original

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

        if text != original:
            path.write_text(text, encoding="utf-8")
            logger.info("Config: set %s = %r in %s", key, value, path)
