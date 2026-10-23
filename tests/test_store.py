from __future__ import annotations

import json

from conftest import activity, read_lines

from strict_log_mcp.config import Config
from strict_log_mcp.store import LogStore


def test_valid_entry_is_appended(store: LogStore, config: Config) -> None:
    result = store.append("activity", activity())
    assert result == {"success": True, "file": "logs/activity.jsonl", "line_count": 1, "errors": []}
    assert json.loads(read_lines(config.root / "logs/activity.jsonl")[0])["agent"] == "writer"


def test_invalid_entry_is_rejected_and_file_untouched(store: LogStore, config: Config) -> None:
    result = store.append("activity", activity(agent="intern", summary="finished"))
    assert result["success"] is False
    assert len(result["errors"]) == 2
    assert not (config.root / "logs/activity.jsonl").exists()


def test_entry_as_json_string(store: LogStore) -> None:
    assert store.append("activity", json.dumps(activity()))["success"]
    assert store.append("activity", "{not json")["errors"][0].startswith("JSON")


def test_umlauts_are_stored_verbatim(store: LogStore, config: Config) -> None:
    store.append("activity", activity(summary="DONE: Größenprüfung für Übersicht"))
    raw = (config.root / "logs/activity.jsonl").read_text(encoding="utf-8")
    assert "Größenprüfung für Übersicht" in raw


def test_duplicate_unique_field(store: LogStore) -> None:
    assert store.append("activity", activity(task_id="2026-01-15-001"))["success"]
    again = store.append("activity", activity(task_id="2026-01-15-001"))
    assert again["errors"] == ["DUPLICATE: task_id='2026-01-15-001' already exists"]


def test_future_timestamp_rejected(store: LogStore) -> None:
    result = store.append("activity", activity(ts="2999-01-01T00:00:00+00:00"))
    assert result["errors"][0].startswith("FUTURE")


def test_refuses_to_append_to_file_without_trailing_newline(store: LogStore, config: Config) -> None:
    target = config.root / "logs/activity.jsonl"
    target.write_text('{"half": "written"', encoding="utf-8")
    result = store.append("activity", activity())
    assert result["errors"][0].startswith("FILE_STATE")
    assert target.read_text(encoding="utf-8") == '{"half": "written"'


def test_csv_creates_header_and_quotes(store: LogStore, config: Config) -> None:
    line = '2026-01-15,writer,notes.md,edit,"typo fixed, wording tightened"'
    result = store.append("changelog", line, path="project-a/CHANGELOG.csv")
    assert result["success"], result
    assert read_lines(config.root / "project-a/CHANGELOG.csv") == [
        "date,agent,file,action,reason",
        '2026-01-15,writer,notes.md,edit,"typo fixed, wording tightened"',
    ]
    assert store.read("changelog", path="project-a/CHANGELOG.csv")[0]["reason"] == "typo fixed, wording tightened"


def test_csv_unquoted_comma_is_rejected(store: LogStore) -> None:
    line = "2026-01-15,writer,notes.md,edit,typo fixed, wording tightened"
    result = store.append("changelog", line, path="project-a/CHANGELOG.csv")
    assert "expected 5 columns" in result["errors"][0]


def test_csv_rejects_multiple_lines(store: LogStore) -> None:
    lines = "2026-01-15,a,b,c,d\n2026-01-15,a,b,c,d"
    assert store.append("changelog", lines, path="project-a/CHANGELOG.csv")["errors"][0].startswith("CSV")


def test_path_traversal_blocked(store: LogStore) -> None:
    result = store.append("changelog", "2026-01-15,a,b,c,d", path="../../CHANGELOG.csv")
    assert result["errors"][0].startswith("PATH_TRAVERSAL")


def test_wrong_filename_blocked(store: LogStore) -> None:
    result = store.append("changelog", "2026-01-15,a,b,c,d", path="project-a/notes.md")
    assert "must be named" in result["errors"][0]


def test_missing_folder_is_not_created(store: LogStore, config: Config) -> None:
    result = store.append("changelog", "2026-01-15,a,b,c,d", path="new-folder/CHANGELOG.csv")
    assert "does not exist" in result["errors"][0]
    assert not (config.root / "new-folder").exists()


def test_fixed_log_rejects_path_argument(store: LogStore) -> None:
    assert store.append("activity", activity(), path="elsewhere.jsonl")["errors"][0].startswith("PATH")


def test_unknown_log(store: LogStore) -> None:
    assert store.append("secrets", {})["errors"][0].startswith("UNKNOWN_LOG")


def test_read_limit_and_status(store: LogStore) -> None:
    for i in range(3):
        store.append("activity", activity(ts=f"2026-01-15T10:0{i}:00+01:00"))
    assert len(store.read("activity", limit=2)) == 2
    assert len(store.read("activity", limit=0)) == 3

    status = store.status()
    assert status["activity"]["entries"] == 3
    assert status["activity"]["last_timestamp"] == "2026-01-15T10:02:00+01:00"
    assert status["corrections"]["reachable"] is False
    assert status["changelog"] == {"mode": "per-call", "filename": "CHANGELOG.csv"}
