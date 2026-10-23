from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from strict_log_mcp.config import Config, load_config
from strict_log_mcp.store import LogStore

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "config.example.json"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """The shipped example config, pointed at an empty temporary workspace."""
    shutil.copy(EXAMPLE, tmp_path / "config.json")
    (tmp_path / "workspace" / "logs").mkdir(parents=True)
    (tmp_path / "workspace" / "project-a").mkdir()
    return load_config(tmp_path / "config.json")


@pytest.fixture
def store(config: Config) -> LogStore:
    return LogStore(config)


def read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def activity(**overrides: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "ts": "2026-01-15T10:00:00+01:00",
        "agent": "writer",
        "summary": "DONE: drafted the release notes",
    }
    entry.update(overrides)
    return entry


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)
