"""Unit tests for the validation value objects."""

from __future__ import annotations

from punt_lux.domain.validation import ValidationError, ValidationReport


class TestValidationError:
    def test_str_names_kind_and_id(self) -> None:
        err = ValidationError(
            element_id="sales",
            element_kind="table",
            message="row 1 is short",
        )
        assert str(err) == "[table 'sales'] row 1 is short"

    def test_to_dict_roundtrips_fields(self) -> None:
        err = ValidationError(
            element_id="t1",
            element_kind="table",
            message="bad cell",
        )
        assert err.to_dict() == {
            "element_id": "t1",
            "element_kind": "table",
            "message": "bad cell",
        }

    def test_is_frozen(self) -> None:
        err = ValidationError(element_id="a", element_kind="table", message="m")
        try:
            err.message = "changed"  # type: ignore[misc]  # frozen — must raise
        except AttributeError:
            return
        msg = "ValidationError must be immutable"
        raise AssertionError(msg)


class TestValidationReport:
    def test_empty_report_is_ok(self) -> None:
        report = ValidationReport()
        assert report.ok
        assert len(report) == 0

    def test_report_with_errors_is_not_ok(self) -> None:
        report = ValidationReport(
            (ValidationError(element_id="t", element_kind="table", message="x"),),
        )
        assert not report.ok
        assert len(report) == 1

    def test_describe_ok(self) -> None:
        assert ValidationReport().describe() == "no validation errors"

    def test_describe_lists_every_error(self) -> None:
        report = ValidationReport(
            (
                ValidationError(element_id="t", element_kind="table", message="first"),
                ValidationError(element_id="t", element_kind="table", message="second"),
            ),
        )
        described = report.describe()
        assert "2 validation error(s):" in described
        assert "first" in described
        assert "second" in described
        # Both errors are on separate bullet lines — nothing is dropped.
        assert described.count("  - ") == 2
