"""Standardized call-tracing decorator for Lux."""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable

__all__ = ["trace"]


def trace[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Log method name and arguments at DEBUG on entry.

    Uses the caller's module logger so tracing output respects the
    per-module log hierarchy.  Adding or removing ``@trace`` is a
    one-line change with zero impact on method signatures.
    """
    _logger = logging.getLogger(func.__module__)

    @functools.wraps(func)
    def _wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        _logger.debug(
            "%s called args=%s kwargs=%s",
            func.__qualname__,
            args,
            kwargs,
        )
        return func(*args, **kwargs)

    return _wrapper
