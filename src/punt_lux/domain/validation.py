"""Validation value objects — one error, and a report that collects many.

These are the *result* types of self-validation. An element's
``validate()`` returns a tuple of :class:`ValidationError`; the
tree walk in :mod:`punt_lux.domain.validation_walk` accumulates every
element's errors into a single :class:`ValidationReport`.

The design follows two prior-art surfaces:

- Immediate-mode GUI (ImGui) puts the precondition check on the widget
  call itself — validation is *component-appropriate*, owned by the thing
  being drawn. We keep that placement but reject ImGui's fail-fast
  ``IM_ASSERT`` behavior.
- Retained-mode form frameworks (Django ``Form.full_clean`` / WTForms)
  walk every field, call each field's own validators, and *aggregate*
  all errors into one collection returned to the caller — the user sees
  every problem at once and the invalid form is never committed. The
  report below is that aggregate; ``describe()`` is its rendered form.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ValidationError", "ValidationReport"]


@dataclass(frozen=True, slots=True)
class ValidationError:
    """One thing wrong with one element, in terms the agent can act on.

    Carries the offending element's identity (``element_id`` /
    ``element_kind``) alongside a human-readable ``message`` so the agent
    that submitted the tree can locate and fix the problem without
    guessing which element the message refers to.
    """

    element_id: str
    element_kind: str
    message: str

    def __str__(self) -> str:
        return f"[{self.element_kind} '{self.element_id}'] {self.message}"

    def to_dict(self) -> dict[str, str]:
        """Return the JSON-compatible wire representation."""
        return {
            "element_id": self.element_id,
            "element_kind": self.element_kind,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The collected outcome of validating an element tree.

    Empty ``errors`` means the tree is valid and may be rendered. A
    non-empty report means the tree must be rejected and every error
    handed back to the agent at once.
    """

    errors: tuple[ValidationError, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        """Whether the tree passed validation (no errors collected)."""
        return not self.errors

    def __len__(self) -> int:
        return len(self.errors)

    def describe(self) -> str:
        """Render the report as an agent-facing, multi-line summary."""
        if self.ok:
            return "no validation errors"
        header = f"{len(self.errors)} validation error(s):"
        body = "\n".join(f"  - {error}" for error in self.errors)
        return f"{header}\n{body}"
