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
            parts = _EOL.split(original)
            ends = _EOL.findall(original)
            lines = [part + end for part, end in zip(parts, [*ends, b""], strict=True)]
            imports, open_fence = self._scan(parts)
            matches = {i for i in imports if parts[i] == self.line}
            if add and not matches:
                self._insert(lines, parts, ends, imports, open_fence=open_fence)
            elif not add and matches:
                lines = [line for i, line in enumerate(lines) if i not in matches]
            else:
                yield None
                return
            yield b"".join(lines)

    @staticmethod
    def _scan(parts: list[bytes]) -> tuple[list[int], bool]:
        imports: list[int] = []
        fence = b""
        for i, content in enumerate(parts):
            delim = _FENCE.match(content)
            if delim is not None:
                run = delim[1]
                if not fence:
                    fence = run
                elif run[:1] == fence[:1] and len(run) >= len(fence):
                    fence = b""
            elif not fence and _IMPORT.fullmatch(content):
                imports.append(i)
        return imports, bool(fence)

    def _insert(
        self,
        lines: list[bytes],
        parts: list[bytes],
        ends: list[bytes],
        imports: list[int],
        *,
        open_fence: bool,
    ) -> None:
        if open_fence:
            msg = f"{self.host.path} ends inside an unclosed code fence"
            raise ValueError(msg)
        eol = ends[0] if ends else b"\n"
        default = imports[-1] + 1 if imports else len(lines)
        index = next((i for i in imports if parts[i] > self.line), default)
        if index and lines[index - 1] and not lines[index - 1].endswith((b"\r", b"\n")):
            lines[index - 1] += eol
        lines.insert(index, self.line + eol)
