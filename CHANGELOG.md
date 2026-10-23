# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-10-23

### Added

- Config-driven logs in JSONL or CSV, each exposed as a `log_add_<name>` tool.
- Field rules: `required`, `type`, `pattern`, `enum`, `min`, `max`, `maxlen`, `unique`, `not_in_future`.
- Append-only writes with a trailing-newline check and a line-count guard.
- Per-call CSV targets with root containment and a fixed file name.
- `log_read` and `log_status` tools, and a `--check` CLI flag.
