"""Field-level validation of a single log entry.

All functions are pure: they take an entry and its rules and return a list of
human-readable errors. An empty list means the entry is accepted.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

DEFAULT_FUTURE_TOLERANCE_S = 60


def validate_entry(
    entry: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    *,
    allow_extra_fields: bool = True,
    now: datetime | None = None,
) -> list[str]:
    errors: list[str] = []

    if not allow_extra_fields:
        extra = sorted(set(entry) - set(fields))
        if extra:
            errors.append(f"UNKNOWN_FIELDS: {extra} are not declared")

    for name, rules in fields.items():
        value = entry.get(name)
        if value is None or value == "":
            if rules.get("required"):
                errors.append(f"MISSING: {name} is required")
            continue
        errors.extend(validate_value(name, value, rules, now=now))
    return errors


def validate_value(name: str, value: Any, rules: dict[str, Any], *, now: datetime | None = None) -> list[str]:
    type_error = _check_type(name, value, rules.get("type", "string"))
    if type_error:
        # Further checks would only produce noise on a wrongly typed value.
        return [type_error]

    errors: list[str] = []
    if "enum" in rules and value not in rules["enum"]:
        errors.append(f"VALUE: {name}={value!r} is not one of {rules['enum']}")
    if "pattern" in rules and isinstance(value, str) and not re.search(rules["pattern"], value):
        errors.append(f"FORMAT: {name}={value!r} does not match {rules['pattern']!r}")
    if "maxlen" in rules and isinstance(value, str) and len(value) > rules["maxlen"]:
        errors.append(f"LENGTH: {name} has {len(value)} characters, max is {rules['maxlen']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "min" in rules and value < rules["min"]:
            errors.append(f"RANGE: {name}={value} is below {rules['min']}")
        if "max" in rules and value > rules["max"]:
            errors.append(f"RANGE: {name}={value} is above {rules['max']}")
    if rules.get("not_in_future"):
        tolerance = rules["not_in_future"]
        tolerance_s = DEFAULT_FUTURE_TOLERANCE_S if tolerance is True else int(tolerance)
        errors.extend(_check_not_in_future(name, value, tolerance_s, now))
    return errors


def _check_type(name: str, value: Any, ftype: str) -> str | None:
    ok = {
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }[ftype]
    return None if ok else f"TYPE: {name} must be {ftype}, got {type(value).__name__}"


def _check_not_in_future(name: str, value: Any, tolerance_s: int, now: datetime | None) -> list[str]:
    """Reject timestamps that lie in the future.

    Agents that cannot read a clock tend to extrapolate timestamps from earlier
    entries. Those guesses drift ahead of real time and ruin the log as a
    timeline, so they are refused instead of stored.
    """
    if not isinstance(value, str):
        return [f"FORMAT: {name} must be an ISO 8601 date or datetime string"]
    now = now or datetime.now(timezone.utc)

    if len(value) == 10:
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return [f"FORMAT: {name}={value!r} is not an ISO 8601 date"]
        today = now.astimezone().date()
        return [f"FUTURE: {name}={value} is after today ({today})"] if day > today else []

    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return [f"FORMAT: {name}={value!r} is not an ISO 8601 datetime"]
    if moment.tzinfo is None:
        return [f"FORMAT: {name}={value!r} needs a UTC offset (e.g. +02:00)"]
    if moment > now + timedelta(seconds=tolerance_s):
        return [f"FUTURE: {name}={value} lies in the future (now is {now.isoformat(timespec='seconds')})"]
    return []
