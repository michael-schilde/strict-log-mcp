from __future__ import annotations

from datetime import datetime, timezone

from strict_log_mcp.validation import validate_entry, validate_value

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def test_missing_required_field() -> None:
    assert validate_entry({}, {"ts": {"required": True, "type": "string"}}) == ["MISSING: ts is required"]


def test_empty_string_counts_as_missing() -> None:
    assert validate_entry({"ts": ""}, {"ts": {"required": True, "type": "string"}})


def test_optional_field_may_be_absent() -> None:
    assert validate_entry({}, {"note": {"type": "string", "maxlen": 3}}) == []


def test_pattern_enum_and_length() -> None:
    rules = {"type": "string", "pattern": "^DONE: ", "maxlen": 10}
    assert validate_value("summary", "DONE: ok", rules) == []
    assert any(e.startswith("FORMAT") for e in validate_value("summary", "done: ok", rules))
    assert any(e.startswith("LENGTH") for e in validate_value("summary", "DONE: far too long", rules))
    assert validate_value("agent", "ghost", {"type": "string", "enum": ["writer"]})[0].startswith("VALUE")


def test_type_rules_reject_bool_as_number() -> None:
    assert validate_value("n", True, {"type": "integer"})[0].startswith("TYPE")
    assert validate_value("n", 1.5, {"type": "integer"})[0].startswith("TYPE")
    assert validate_value("n", 1.5, {"type": "number"}) == []


def test_numeric_range() -> None:
    rules = {"type": "integer", "min": 0, "max": 600}
    assert validate_value("effort", 30, rules) == []
    assert validate_value("effort", -1, rules)[0].startswith("RANGE")
    assert validate_value("effort", 601, rules)[0].startswith("RANGE")


def test_unknown_fields_rejected_when_closed() -> None:
    errors = validate_entry({"x": 1}, {}, allow_extra_fields=False)
    assert errors == ["UNKNOWN_FIELDS: ['x'] are not declared"]
    assert validate_entry({"x": 1}, {}, allow_extra_fields=True) == []


def test_future_datetime_rejected() -> None:
    rules = {"type": "string", "not_in_future": 60}
    assert validate_value("ts", "2026-01-15T12:00:30+00:00", rules, now=NOW) == []
    assert validate_value("ts", "2026-01-15T13:30:00+00:00", rules, now=NOW)[0].startswith("FUTURE")
    # Same instant expressed in another offset is still in the future.
    assert validate_value("ts", "2026-01-15T14:30:00+01:00", rules, now=NOW)[0].startswith("FUTURE")


def test_future_needs_offset() -> None:
    errors = validate_value("ts", "2026-01-15T10:00:00", {"type": "string", "not_in_future": True}, now=NOW)
    assert "UTC offset" in errors[0]


def test_future_date_rejected() -> None:
    rules = {"type": "string", "not_in_future": True}
    assert validate_value("date", "2026-01-14", rules, now=NOW) == []
    assert validate_value("date", "2026-02-01", rules, now=NOW)[0].startswith("FUTURE")
    assert validate_value("date", "2026-13-01", rules, now=NOW)[0].startswith("FORMAT")
