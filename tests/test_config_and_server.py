from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import activity

from strict_log_mcp.config import Config, ConfigError, parse_config
from strict_log_mcp.server import call_tool, main, tool_definitions
from strict_log_mcp.store import LogStore


def minimal(**log: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {"format": "jsonl", "path": "a.jsonl"}
    spec.update(log)
    return {"logs": {"a": spec}}


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ({}, "non-empty 'logs'"),
        (minimal(format="xml"), "format must be"),
        (minimal(filename="x.jsonl"), "exactly one of"),
        (minimal(path="../outside.jsonl"), "inside root"),
        (minimal(fields={"x": {"type": "date"}}), "type must be"),
        (minimal(fields={"x": {"pattern": "("}}), "not a valid regex"),
        (minimal(fields={"x": {"requird": True}}), "unknown rules"),
        (minimal(colour="blue"), "unknown keys"),
        ({"logs": {"Bad-Name": {"format": "jsonl", "path": "a.jsonl"}}}, "name must match"),
    ],
)
def test_bad_configs_are_rejected(tmp_path: Path, raw: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(raw, base_dir=tmp_path)


def test_tools_are_generated_from_config(config: Config) -> None:
    tools = {t["name"]: t for t in tool_definitions(config)}
    assert set(tools) == {"log_add_activity", "log_add_corrections", "log_add_changelog", "log_read", "log_status"}

    entry_schema = tools["log_add_activity"]["inputSchema"]["properties"]["entry"]
    assert entry_schema["required"] == ["ts", "agent", "summary"]
    assert entry_schema["properties"]["agent"]["enum"] == ["planner", "writer", "reviewer"]
    assert tools["log_add_changelog"]["inputSchema"]["required"] == ["line", "path"]


def test_call_tool_dispatch(store: LogStore) -> None:
    assert call_tool(store, "log_add_activity", {"entry": activity()})["success"]
    assert len(call_tool(store, "log_read", {"log": "activity"})) == 1
    assert call_tool(store, "log_read", {"log": "nope"})["errors"][0].startswith("UNKNOWN_LOG")
    assert call_tool(store, "log_delete", {})["errors"] == ["UNKNOWN_TOOL: log_delete"]
    json.dumps(call_tool(store, "log_status", {}))  # must be serialisable


def test_cli_check(config: Config, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--config", str(tmp_path / "config.json"), "--check"]) == 0
    assert "log_add_activity" in capsys.readouterr().out
    assert main(["--config", str(tmp_path / "missing.json"), "--check"]) == 2
