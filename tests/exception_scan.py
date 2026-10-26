"""ExceptionScan -- which exception classes the imported package defines are frozen."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from types import ModuleType

__all__ = ["ExceptionScan"]


@final
class ExceptionScan:
    """Finds, by running the import system, every package exception that is frozen.

    A syntax scan cannot follow an imported base class; the live class hierarchy
    can, so every module is imported and every ``BaseException`` subclass defined
    in it is inspected where it stands.
    """

    _classes: dict[str, type[BaseException]]
    __slots__ = ("_classes",)

    def __new__(cls, package: ModuleType) -> Self:
        self = super().__new__(cls)
        self._classes = {}
        for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
            if info.name.rsplit(".", 1)[-1] == "__main__":
                continue
            module = importlib.import_module(info.name)
            for value in vars(module).values():
                if (
                    isinstance(value, type)
                    and issubclass(value, BaseException)
                    and value.__module__ == module.__name__
                ):
                    self._classes[f"{value.__module__}.{value.__qualname__}"] = value
        return self

    def exceptions(self) -> list[type[BaseException]]:
        """Every exception class the package defines, in name order."""
        return [self._classes[name] for name in sorted(self._classes)]

    def frozen_exceptions(self) -> list[str]:
        """The name of each frozen dataclass that is an exception class."""
        return [
            name
            for name, found in sorted(self._classes.items())
            if "__dataclass_params__" in vars(found)
            and vars(found)["__dataclass_params__"].frozen
        ]
