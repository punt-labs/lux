"""Edit only Lux's canonical top-level import in a Claude Code host file."""

from __future__ import annotations

import re
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass

from punt_lux.service.activation_file import ActivationFile

_FENCE = re.compile(rb"^ {0,3}(`{3,}|~{3,})")
_IMPORT = re.compile(rb"@\.punt-labs/(?:local/)?[^/\s]+/CLAUDE\.md")
_EOL = re.compile(rb"\r\n|\r|\n")


@dataclass(frozen=True, slots=True)
class ClaudeImport:
    host: ActivationFile
    line: bytes

    def apply(self, *, add: bool) -> None:
        with self.prepare(add=add) as data:
            if data is not None:
                self.host.write(data)

    @contextmanager
    def prepare(self, *, add: bool) -> Generator[bytes | None]:
        if not add and self.host.read() is None:
            yield None
            return
        with self.host.locked():
            original = self.host.read() or b""
            yield self._edited(original, add=add)

    def _edited(self, original: bytes, *, add: bool) -> bytes | None:
        parts = _EOL.split(original)
        ends = _EOL.findall(original)
        lines = self._with_endings(parts, ends)
        imports, open_fence = self._scan(parts)
        matches = {i for i in imports if parts[i] == self.line}
        if add and not matches:
            if open_fence:
                msg = f"{self.host.path} ends inside an unclosed code fence"
                raise ValueError(msg)
            self._insert(lines, parts, ends, imports)
            return b"".join(lines)
        if not add and matches:
            return b"".join(line for i, line in enumerate(lines) if i not in matches)
        return None

    @staticmethod
    def _with_endings(parts: list[bytes], ends: list[bytes]) -> list[bytes]:
        return [part + end for part, end in zip(parts, [*ends, b""], strict=True)]

    @staticmethod
    def _scan(parts: list[bytes]) -> tuple[list[int], bool]:
        imports: list[int] = []
        fence = b""
        for i, content in enumerate(parts):
            delim = _FENCE.match(content)
            if delim is not None:
                run = delim[1]
                fence = ClaudeImport._fence_after(fence, run)
            elif not fence and _IMPORT.fullmatch(content):
                imports.append(i)
        return imports, bool(fence)

    @staticmethod
    def _fence_after(fence: bytes, delimiter: bytes) -> bytes:
        if not fence:
            return delimiter
        if delimiter[:1] == fence[:1] and len(delimiter) >= len(fence):
            return b""
        return fence

    def _insert(
        self,
        lines: list[bytes],
        parts: list[bytes],
        ends: list[bytes],
        imports: list[int],
    ) -> None:
        eol = ends[0] if ends else b"\n"
        default = imports[-1] + 1 if imports else len(lines)
        index = next((i for i in imports if parts[i] > self.line), default)
        if index:
            lines[index - 1] = self._terminated(lines[index - 1], eol)
        lines.insert(index, self.line + eol)

    @staticmethod
    def _terminated(line: bytes, eol: bytes) -> bytes:
        return line if not line or line.endswith((b"\r", b"\n")) else line + eol
