"""
Minimal MCP HTTP/SSE server using FastMCP.

This avoids importing fpl_mcp internals and just demonstrates the pattern works.
We can add real FPL tools once we confirm the server starts.

Endpoints:
  GET  /sse    — Server-Sent Events stream for MCP clients that support SSE.
  POST /mcp    — JSON-RPC style endpoint for Streamable HTTP MCP clients.
  GET  /health — Health check.
"""

import json
import os
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from mcp.server.fastmcp import FastMCP  # type: ignore

app = FastAPI(title="Fantasy PL MCP Server")

# Create FastMCP server
mcp = FastMCP(name="fantasy-pl")


@mcp.tool(name="get_players", description="Get FPL players (placeholder)")
async def get_players() -> List[Dict[str, Any]]:
    # Placeholder - will be replaced with real FPL API calls
    return [{"id": 1, "name": "Placeholder Player"}]


@mcp.tool(name="get_fixtures", description="Get FPL fixtures (placeholder)")
async def get_fixtures() -> List[Dict[str, Any]]:
    return [{"id": 1, "event": 1, "kickoff_time": "2026-08-17T15:00:00Z"}]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sse")
async def sse_endpoint(request: Request) -> StreamingResponse:
    async def event_generator():
        async with mcp.sse_stream() as stream:
            async for event in stream:
                yield f"event: message\ndata: {json.dumps(event)}\n\n"
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    body = await request.json()
    result = await mcp.handle_json_rpc(body)
    return JSONResponse(result)


def main():
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
