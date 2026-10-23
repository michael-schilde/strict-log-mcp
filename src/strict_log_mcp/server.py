"""MCP stdio server: one append tool per configured log, plus read and status."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

from . import __version__
from .config import Config, ConfigError, LogSpec, load_config
from .store import LogStore, StoreError

APPEND_PREFIX = "log_add_"
JSON_TYPES = {"string": "string", "integer": "integer", "number": "number", "boolean": "boolean"}


def tool_definitions(config: Config) -> list[dict[str, Any]]:
    """Describe the tools as plain dicts (name, description, inputSchema)."""
    tools = [_append_tool(spec) for spec in config.logs.values()]
    tools.append(
        {
            "name": "log_read",
            "description": "Read the most recent entries of a log.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "log": {"type": "string", "enum": sorted(config.logs)},
                    "limit": {"type": "integer", "minimum": 0, "default": 50, "description": "0 returns all entries"},
                    "path": {"type": "string", "description": "Only for logs without a fixed file"},
                },
                "required": ["log"],
            },
        }
    )
    tools.append(
        {
            "name": "log_status",
            "description": "Health check: reachability, entry count and last timestamp of each log.",
            "inputSchema": {"type": "object", "properties": {}},
        }
    )
    return tools


def _append_tool(spec: LogSpec) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []

    if spec.format == "jsonl":
        entry_props: dict[str, Any] = {}
        for name, rules in spec.fields.items():
            prop: dict[str, Any] = {"type": JSON_TYPES[rules["type"]]}
            if "description" in rules:
                prop["description"] = rules["description"]
            if "enum" in rules:
                prop["enum"] = rules["enum"]
            entry_props[name] = prop
        properties["entry"] = {
            "type": "object",
            "properties": entry_props,
            "required": [n for n, r in spec.fields.items() if r.get("required")],
        }
        required.append("entry")
        what = "Validates an entry and appends it as one JSON line."
    else:
        properties["line"] = {"type": "string", "description": "One CSV line: " + ",".join(spec.columns)}
        required.append("line")
        what = f"Validates one CSV line ({','.join(spec.columns)}) and appends it."

    if spec.path is None:
        properties["path"] = {
            "type": "string",
            "description": f"Path relative to the root; the file must be named {spec.filename}",
        }
        required.append("path")

    description = f"{spec.description} {what} Invalid entries are rejected with a list of errors.".strip()
    return {
        "name": APPEND_PREFIX + spec.name,
        "description": description,
        "inputSchema": {"type": "object", "properties": properties, "required": required},
    }


def call_tool(store: LogStore, name: str, arguments: dict[str, Any]) -> Any:
    """Dispatch a tool call. Returns a JSON-serialisable result."""
    try:
        if name.startswith(APPEND_PREFIX):
            log = name[len(APPEND_PREFIX) :]
            spec = store.config.logs.get(log)
            payload = arguments.get("entry") if spec is None or spec.format == "jsonl" else arguments.get("line")
            return store.append(log, payload, arguments.get("path"))
        if name == "log_read":
            return store.read(arguments.get("log", ""), arguments.get("limit", 50), arguments.get("path"))
        if name == "log_status":
            return store.status()
    except StoreError as exc:
        return {"success": False, "errors": [str(exc)]}
    return {"success": False, "errors": [f"UNKNOWN_TOOL: {name}"]}


def is_rejection(result: Any) -> bool:
    return isinstance(result, dict) and result.get("success") is False


def serve(config: Config) -> None:
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    store = LogStore(config)
    tools = [
        types.Tool(name=t["name"], description=t["description"], input_schema=t["inputSchema"])
        for t in tool_definitions(config)
    ]

    async def on_list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=tools)

    async def on_call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        result = call_tool(store, params.name, dict(params.arguments or {}))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            # A rejected entry is reported as a tool error so the agent cannot
            # mistake it for a successful write.
            is_error=is_rejection(result),
        )

    server: Server[Any] = Server(
        "strict-log-mcp",
        version=__version__,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )

    async def run() -> None:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="strict-log-mcp", description=__doc__)
    parser.add_argument(
        "--config",
        default=os.environ.get("STRICT_LOG_CONFIG"),
        help="Path to the JSON config (default: $STRICT_LOG_CONFIG)",
    )
    parser.add_argument("--check", action="store_true", help="Validate the config, print the tools and exit")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)

    if not args.config:
        parser.error("no config given; pass --config or set STRICT_LOG_CONFIG")
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"strict-log-mcp: {exc}", file=sys.stderr)
        return 2

    if args.check:
        for tool in tool_definitions(config):
            print(tool["name"])
        return 0

    serve(config)
    return 0
