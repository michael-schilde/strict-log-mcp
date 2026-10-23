"""Load and sanity-check the server configuration.

The configuration is a single JSON file. Every log the server is allowed to
write to is declared there, together with the rules each entry must satisfy.
Anything not declared cannot be written.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMATS = {"jsonl", "csv"}
FIELD_TYPES = {"string", "integer", "number", "boolean"}
FIELD_RULES = {
    "description",
    "required",
    "type",
    "pattern",
    "enum",
    "min",
    "max",
    "maxlen",
    "unique",
    "not_in_future",
}
LOG_KEYS = {
    "format",
    "description",
    "path",
    "filename",
    "columns",
    "fields",
    "allow_extra_fields",
    "timestamp_field",
}
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class ConfigError(ValueError):
    """Raised when the configuration file is missing or malformed."""


@dataclass(frozen=True)
class LogSpec:
    """One log the server may append to."""

    name: str
    format: str
    description: str
    fields: dict[str, dict[str, Any]]
    # Exactly one of `path` (a single fixed file) or `filename` (any file with
    # this name below the root, chosen per call) is set.
    path: Path | None
    filename: str | None
    columns: tuple[str, ...]
    allow_extra_fields: bool
    timestamp_field: str | None


@dataclass(frozen=True)
class Config:
    root: Path
    logs: dict[str, LogSpec]


def load_config(config_path: str | Path) -> Config:
    """Read a config file. Relative paths are resolved against its folder."""
    config_path = Path(config_path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config file is not valid JSON: {exc}") from exc
    return parse_config(raw, base_dir=config_path.resolve().parent)


def parse_config(raw: Any, base_dir: Path) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a JSON object")

    root = (base_dir / str(raw.get("root", "."))).resolve()
    if not root.is_dir():
        raise ConfigError(f"root is not an existing directory: {root}")

    logs_raw = raw.get("logs")
    if not isinstance(logs_raw, dict) or not logs_raw:
        raise ConfigError("config needs a non-empty 'logs' object")

    logs = {name: _parse_log(name, spec, root) for name, spec in logs_raw.items()}
    return Config(root=root, logs=logs)


def _parse_log(name: str, spec: Any, root: Path) -> LogSpec:
    where = f"logs.{name}"
    if not NAME_PATTERN.match(name):
        raise ConfigError(f"{where}: name must match {NAME_PATTERN.pattern}")
    if not isinstance(spec, dict):
        raise ConfigError(f"{where}: must be an object")

    unknown = set(spec) - LOG_KEYS
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")

    fmt = spec.get("format")
    if fmt not in FORMATS:
        raise ConfigError(f"{where}.format must be one of {sorted(FORMATS)}")

    has_path, has_filename = "path" in spec, "filename" in spec
    if has_path == has_filename:
        raise ConfigError(f"{where}: set exactly one of 'path' or 'filename'")

    path: Path | None = None
    filename: str | None = None
    if has_path:
        path = (root / str(spec["path"])).resolve()
        if not path.is_relative_to(root):
            raise ConfigError(f"{where}.path must stay inside root")
    else:
        filename = str(spec["filename"])
        if Path(filename).name != filename:
            raise ConfigError(f"{where}.filename must be a bare file name")

    columns: tuple[str, ...] = ()
    if fmt == "csv":
        cols = spec.get("columns")
        if not isinstance(cols, list) or not cols or not all(isinstance(c, str) for c in cols):
            raise ConfigError(f"{where}.columns must be a non-empty list of strings")
        columns = tuple(cols)
    elif "columns" in spec:
        raise ConfigError(f"{where}.columns is only valid for csv logs")

    fields_raw = spec.get("fields", {})
    if not isinstance(fields_raw, dict):
        raise ConfigError(f"{where}.fields must be an object")
    fields = {fname: _parse_field(f"{where}.fields.{fname}", rules, fmt) for fname, rules in fields_raw.items()}
    if columns:
        stray = set(fields) - set(columns)
        if stray:
            raise ConfigError(f"{where}.fields names unknown columns {sorted(stray)}")

    timestamp_field = spec.get("timestamp_field")
    if timestamp_field is not None and timestamp_field not in (columns or fields):
        raise ConfigError(f"{where}.timestamp_field must name a declared field")

    return LogSpec(
        name=name,
        format=fmt,
        description=str(spec.get("description", "")),
        fields=fields,
        path=path,
        filename=filename,
        columns=columns,
        allow_extra_fields=bool(spec.get("allow_extra_fields", True)),
        timestamp_field=timestamp_field,
    )


def _parse_field(where: str, rules: Any, fmt: str) -> dict[str, Any]:
    if not isinstance(rules, dict):
        raise ConfigError(f"{where}: must be an object")
    unknown = set(rules) - FIELD_RULES
    if unknown:
        raise ConfigError(f"{where}: unknown rules {sorted(unknown)}")

    ftype = rules.get("type", "string")
    if ftype not in FIELD_TYPES:
        raise ConfigError(f"{where}.type must be one of {sorted(FIELD_TYPES)}")
    if fmt == "csv" and ftype != "string":
        raise ConfigError(f"{where}.type: csv values are always strings")

    if "pattern" in rules:
        try:
            re.compile(rules["pattern"])
        except re.error as exc:
            raise ConfigError(f"{where}.pattern is not a valid regex: {exc}") from exc
    if "enum" in rules and (not isinstance(rules["enum"], list) or not rules["enum"]):
        raise ConfigError(f"{where}.enum must be a non-empty list")
    for key in ("min", "max", "maxlen"):
        if key in rules and (not isinstance(rules[key], (int, float)) or isinstance(rules[key], bool)):
            raise ConfigError(f"{where}.{key} must be a number")
    nif = rules.get("not_in_future")
    if nif is not None and not isinstance(nif, (bool, int)):
        raise ConfigError(f"{where}.not_in_future must be true/false or a tolerance in seconds")

    return dict(rules, type=ftype)
