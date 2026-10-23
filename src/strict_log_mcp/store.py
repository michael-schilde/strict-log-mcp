"""Append-only access to the configured log files.

The store never rewrites or truncates a file. It validates first, appends one
line, and then checks that exactly one line was added.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path
from typing import Any

from .config import Config, LogSpec
from .validation import validate_entry


class StoreError(Exception):
    """A request that cannot be served; the message is returned to the caller."""


class LogStore:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._lock = threading.Lock()

    # ── public API ───────────────────────────────────────────────────────────

    def append(self, log: str, payload: Any, path: str | None = None) -> dict[str, Any]:
        """Validate `payload` and append it. Never raises for bad input."""
        try:
            spec = self._spec(log)
            target = self._resolve(spec, path)
            entry = self._parse_payload(spec, payload)
        except StoreError as exc:
            return _fail(str(exc))

        errors = validate_entry(entry, spec.fields, allow_extra_fields=spec.allow_extra_fields)
        if errors:
            return _fail(*errors)

        with self._lock:
            errors = self._check_unique(spec, target, entry)
            if errors:
                return _fail(*errors)
            try:
                line_count = self._append_line(spec, target, entry)
            except StoreError as exc:
                return _fail(str(exc))

        return {"success": True, "file": self._display(target), "line_count": line_count, "errors": []}

    def read(self, log: str, limit: int = 50, path: str | None = None) -> list[Any]:
        """Return the last `limit` entries (0 = all)."""
        spec = self._spec(log)
        target = self._resolve(spec, path)
        records = self._records(spec, target)
        limit = max(int(limit), 0)
        return records[-limit:] if limit else records

    def status(self) -> dict[str, Any]:
        """Health check for every log with a fixed path."""
        result: dict[str, Any] = {}
        for name, spec in self.config.logs.items():
            if spec.path is None:
                result[name] = {"mode": "per-call", "filename": spec.filename}
                continue
            info: dict[str, Any] = {"file": self._display(spec.path), "reachable": spec.path.exists()}
            if info["reachable"]:
                records = self._records(spec, spec.path)
                info["entries"] = len(records)
                if spec.timestamp_field and records and isinstance(records[-1], dict):
                    info["last_timestamp"] = records[-1].get(spec.timestamp_field, "")
            result[name] = info
        return result

    # ── internals ────────────────────────────────────────────────────────────

    def _spec(self, log: str) -> LogSpec:
        spec = self.config.logs.get(log)
        if spec is None:
            raise StoreError(f"UNKNOWN_LOG: {log!r}; configured logs are {sorted(self.config.logs)}")
        return spec

    def _resolve(self, spec: LogSpec, path: str | None) -> Path:
        if spec.path is not None:
            if path:
                raise StoreError(f"PATH: log {spec.name!r} has a fixed file; do not pass a path")
            return spec.path
        if not path:
            raise StoreError(f"PATH: log {spec.name!r} needs a path relative to the root")

        root = self.config.root
        target = (root / path).resolve()
        if not target.is_relative_to(root):
            raise StoreError("PATH_TRAVERSAL: path resolves outside the root")
        if target.name != spec.filename:
            raise StoreError(f"PATH: file must be named {spec.filename!r}")
        if not target.parent.is_dir():
            raise StoreError("PATH: parent folder does not exist; the server does not create folders")
        return target

    def _parse_payload(self, spec: LogSpec, payload: Any) -> dict[str, Any]:
        if spec.format == "jsonl":
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except json.JSONDecodeError as exc:
                    raise StoreError(f"JSON: entry is not valid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise StoreError("JSON: entry must be an object")
            return payload

        if not isinstance(payload, str) or not payload.strip():
            raise StoreError("CSV: line must be a non-empty string")
        if "\n" in payload.strip("\r\n"):
            raise StoreError("CSV: exactly one line is allowed per call")
        try:
            cells = next(csv.reader([payload.strip("\r\n")]))
        except csv.Error as exc:
            raise StoreError(f"CSV: cannot parse line: {exc}") from exc
        if len(cells) != len(spec.columns):
            raise StoreError(
                f"CSV: expected {len(spec.columns)} columns ({','.join(spec.columns)}), got {len(cells)}. "
                "Quote values that contain commas."
            )
        return dict(zip(spec.columns, (c.strip() for c in cells), strict=True))

    def _check_unique(self, spec: LogSpec, target: Path, entry: dict[str, Any]) -> list[str]:
        unique_fields = [f for f, rules in spec.fields.items() if rules.get("unique") and entry.get(f)]
        if not unique_fields or not target.exists():
            return []
        existing = [r for r in self._records(spec, target) if isinstance(r, dict)]
        return [
            f"DUPLICATE: {f}={entry[f]!r} already exists"
            for f in unique_fields
            if any(r.get(f) == entry[f] for r in existing)
        ]

    def _append_line(self, spec: LogSpec, target: Path, entry: dict[str, Any]) -> int:
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if existing and not existing.endswith("\n"):
            raise StoreError("FILE_STATE: file does not end with a newline; refusing to append")
        before = _count_lines(existing)

        if spec.format == "jsonl":
            text = json.dumps(entry, ensure_ascii=False) + "\n"
        else:
            buf = io.StringIO()
            writer = csv.writer(buf, lineterminator="\n")
            if not existing:
                # A new file gets the header first; count it as already present.
                writer.writerow(spec.columns)
                before = 1
            writer.writerow([entry[c] for c in spec.columns])
            text = buf.getvalue()

        with open(target, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

        after = _count_lines(target.read_text(encoding="utf-8"))
        if after != before + 1:
            raise StoreError(f"LINE_COUNT_GUARD: expected {before + 1} lines after append, found {after}")
        return after

    def _records(self, spec: LogSpec, target: Path) -> list[Any]:
        if not target.exists():
            return []
        text = target.read_text(encoding="utf-8")
        if spec.format == "csv":
            return list(csv.DictReader(io.StringIO(text)))
        records: list[Any] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({"_raw": line, "_error": "invalid JSON"})
        return records

    def _display(self, path: Path) -> str:
        return path.relative_to(self.config.root).as_posix()


def _count_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.strip())


def _fail(*errors: str) -> dict[str, Any]:
    return {"success": False, "errors": list(errors)}
