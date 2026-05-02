# Copyright 2026 zoltan-alt — Licensed under Apache-2.0. See LICENSE.

"""mobile-design-verify MCP server.

Stdio transport. Tools added incrementally per the project plan §2:
  §2.1 (this file) — bootstrap with `ping`.
  §2.2 — `_run_maestro` shell-out helper.
  §2.3 — `screenshot`, `view_hierarchy`, then interaction tools.
"""

from __future__ import annotations

import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from config import SERVER_NAME

server: Server = Server(SERVER_NAME)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="ping",
            description=(
                "No-op tool that confirms the server is reachable. Returns 'pong'. "
                "Use to verify the MCP server is registered and running."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "ping":
        return [TextContent(type="text", text="pong")]
    raise ValueError(f"Unknown tool: {name}")


async def _run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
