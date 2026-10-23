# strict-log-mcp

[![CI](https://github.com/michael-schilde/strict-log-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/michael-schilde/strict-log-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

An append-only [MCP](https://modelcontextprotocol.io) server for agent logs. It checks every entry against rules you declare and refuses the ones that break them.

## Why this exists

I run a team of AI agents that log their own work: what they finished, what a reviewer sent back, which files they changed. Those logs are the only reliable answer to "was this already done?", so they have to be correct.

For months the rules lived in the agents' instructions: never edit a log by hand, always take the timestamp from a real clock, quote commas in CSV, use only known agent names. The agents read those rules and broke them anyway. They extrapolated timestamps from earlier entries, so the log drifted into the future. They "fixed" old lines in place. They wrote unquoted commas that shifted CSV columns. A sandbox that saw the files through a cached mount mangled umlauts. Every time, the answer was a sharper rule, and the next run broke it again.

So I moved the rules out of the prompt and into code. The agent can no longer write a log file directly; it can only ask this server to append an entry. If the entry is invalid, the server rejects it, says why, and the file stays untouched. The agent has to fix the entry and try again.

## How it works

- **Declared logs only.** A JSON config lists every log (JSONL or CSV), where it lives and which rules each field must satisfy. Each log becomes one `log_add_<name>` tool, and nothing outside the config can be written.
- **Validate, then append.** Required fields, types, regex patterns, enums, length and range limits, unique values, and "not in the future" timestamps are checked before a byte is written.
- **Append-only.** There is no edit or delete tool. Before writing, the server checks that the file ends cleanly. Afterwards it confirms that exactly one line was added.
- **Contained paths.** Per-call CSV targets (for example one `CHANGELOG.csv` per project folder) must resolve inside the root, must have the configured file name and must already exist as a folder.
- **UTF-8 throughout.** Entries are stored verbatim (`ensure_ascii=False`), so umlauts survive.

A rejected call comes back as an MCP tool error with a list of reasons:

```json
{
  "success": false,
  "errors": [
    "FUTURE: ts=2999-01-01T00:00:00+00:00 lies in the future (now is 2026-10-23T12:20:30+00:00)",
    "VALUE: agent='x' is not one of ['planner', 'writer', 'reviewer']",
    "FORMAT: summary='y' does not match '^DONE: '"
  ]
}
```

## Installation

You need Python 3.10+ and [uv](https://docs.astral.sh/uv/) (or pipx).

```bash
uvx --from git+https://github.com/michael-schilde/strict-log-mcp strict-log-mcp --config path/to/config.json --check
```

`--check` validates the config and prints the tools it would expose. Then register the server with your MCP client, for example in Claude Desktop's `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "strict-log": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/michael-schilde/strict-log-mcp",
        "strict-log-mcp", "--config", "/absolute/path/to/config.json"
      ]
    }
  }
}
```

Instead of `--config` you can set the `STRICT_LOG_CONFIG` environment variable.

## Configuration

See [`examples/config.example.json`](examples/config.example.json) for a complete config with an activity log, a corrections log and per-folder changelogs. A minimal log looks like this:

```json
{
  "root": "./workspace",
  "logs": {
    "activity": {
      "format": "jsonl",
      "path": "logs/activity.jsonl",
      "timestamp_field": "ts",
      "allow_extra_fields": false,
      "fields": {
        "ts":      { "required": true, "not_in_future": 120 },
        "agent":   { "required": true, "enum": ["planner", "writer", "reviewer"] },
        "summary": { "required": true, "pattern": "^DONE: ", "maxlen": 500 },
        "task_id": { "unique": true }
      }
    }
  }
}
```

Relative paths in the config are resolved against the folder that contains the config file.

| Log key | Meaning |
|:--|:--|
| `format` | `jsonl` or `csv` |
| `path` | One fixed file, relative to `root` |
| `filename` | Alternative to `path`: any file with this name below `root`, chosen per call via a `path` argument |
| `columns` | CSV only: column names and their order; a header row is written to new files |
| `fields` | Rules per field or column (see below) |
| `allow_extra_fields` | `false` rejects fields that are not declared (default `true`) |
| `timestamp_field` | Field that `log_status` reports as the last timestamp |

| Field rule | Meaning |
|:--|:--|
| `required` | Field must be present and non-empty |
| `type` | `string` (default), `integer`, `number`, `boolean`; CSV values are always strings |
| `pattern` | Regex the value must contain a match for; anchor with `^`/`$` to match the whole value |
| `enum` | List of allowed values |
| `min`, `max`, `maxlen` | Numeric range and maximum string length |
| `unique` | Value must not already exist in that file |
| `not_in_future` | ISO date or datetime (with UTC offset) must not be in the future; `true` allows 60 s of clock skew, a number sets the tolerance in seconds |
| `description` | Shown to the agent in the tool schema |

## Tools

| Tool | Purpose |
|:--|:--|
| `log_add_<name>` | Validate and append one entry (`entry` object for JSONL, `line` string for CSV, plus `path` for per-call logs) |
| `log_read` | Return the last `limit` entries of a log (`0` = all) |
| `log_status` | Reachability, entry count and last timestamp of each fixed log |

## Limits

- **One writer.** Appends are serialised inside a single server process. Two server instances, or another program writing to the same file, can still race.
- **No corrections.** That is deliberate: a wrong entry stays, and you fix it by hand or with a follow-up entry. If your workflow needs edits, this is the wrong tool.
- **Full-file reads.** Uniqueness checks and line counting read the whole file on each append. That is fine for thousands of lines, not for millions.
- **Validation is only as good as the config.** The server enforces structure, not truth. An agent can still log a well-formed entry about work it never did.
- **Clock trust.** `not_in_future` catches guessed timestamps that run ahead. It cannot catch made-up ones that lie in the past.
- **Platforms.** I use it on Windows. CI runs the tests on Linux and Windows; macOS should work but is not tested.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## About

I built this with [Claude Code](https://claude.com/claude-code). It is the generalised version of a log server that has been running in my own agent setup every day since mid-2026. Issues and pull requests are welcome.

## License

[MIT](LICENSE) © Michael Schilde
