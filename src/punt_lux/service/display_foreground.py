"""Launch the display executable in the caller's foreground process."""

from __future__ import annotations

import importlib
import os
import sys
from typing import ClassVar, Never, final


@final
class DisplayForeground:
    """Keep renderer imports out of lifecycle clients and retain their process ID."""

    __slots__ = ()
    _dependencies: ClassVar[frozenset[str]] = frozenset(
        {"imgui_bundle", "numpy", "PIL.Image", "OpenGL.GL"}
    )

    @classmethod
    def is_dependency(cls, module: str) -> bool:
        """Whether a missing module belongs to the optional display extra."""
        return module.split(".")[0] in {dep.split(".")[0] for dep in cls._dependencies}

    @classmethod
    def serve(cls, socket: str | None, *, test_auto_click: bool = False) -> Never:
        """Replace this process with the display using the same Python environment."""
        for module in sorted(cls._dependencies):
            importlib.import_module(module)
        args = [sys.executable, "-P", "-m", "punt_lux.display"]
        if socket is not None:
            args.append(f"--socket={socket}")
        if test_auto_click:
            args.append("--test-auto-click")
        os.execv(sys.executable, args)  # noqa: S606 -- fixed interpreter/module, argv-only options, no shell
