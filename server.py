"""
FastAPI HTTP/SSE wrapper for fantasy-pl-mcp to run on Render.

This creates a minimal MCP server using the mcp library and registers
FPL tools/resources by wrapping the fpl_mcp.fpl.api functions.

Endpoints:
  GET  /sse    — Server-Sent Events stream for MCP clients that support SSE.
  POST /mcp    — JSON-RPC style endpoint for Streamable HTTP MCP clients.
  GET  /health — Health check (useful for keep-alive pings).
"""

import asyncio
import json
import os
from typing import AsyncGenerator, Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from mcp.server import Server  # type: ignore
from mcp.types import Tool, Resource  # type: ignore

# Import FPL API functions
from fpl_mcp.fpl.api import FplApi  # type: ignore[attr-defined]

app = FastAPI(title="Fantasy PL MCP Server")

# Create MCP server instance
mcp_server = Server(name="fantasy-pl")

# Initialize FPL API (handles auth internally)
fpl_api = FplApi()


# Register simple tools
@mcp_server.tool(
    name="get_players",
    description="Get all FPL players with stats",
)
async def get_players() -> List[Dict[str, Any]]:
    return await fpl_api.get_players()


@mcp_server.tool(
    name="get_fixtures",
    description="Get FPL fixtures",
)
async def get_fixtures() -> List[Dict[str, Any]]:
    return await fpl_api.get_fixtures()


@mcp_server.tool(
    name="get_gameweeks",
    description="Get FPL gameweek status",
)
async def get_gameweeks() -> List[Dict[str, Any]]:
    return await fpl_api.get_gameweeks()


# Register resources
@mcp_server.resource(
    uri="fpl://players",
    name="FPL Players",
    description="All FPL players",
)
async def players_resource() -> List[Dict[str, Any]]:
    return await fpl_api.get_players()


@mcp_server.resource(
    uri="fpl://fixtures",
    name="FPL Fixtures",
    description="All FPL fixtures",
)
async def fixtures_resource() -> List[Dict[str, Any]]:
    return await fpl_api.get_fixtures()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sse")
async def sse_endpoint(request: Request) -> StreamingResponse:
    """
    Server-Sent Events endpoint for MCP clients that expect an SSE stream.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        async with mcp_server.sse_stream() as stream:
            async for event in stream:
                yield f"event: message\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    """
    JSON-RPC style endpoint for Streamable HTTP MCP clients.
    """
    body = await request.json()
    result = await mcp_server.handle_json_rpc(body)
    return JSONResponse(result)


def main():
    import uvicorn

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
