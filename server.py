"""
MCP HTTP/SSE server for Fantasy PL with plain FastAPI + sse_starlette.

Endpoints:
  GET  /sse    — Server-Sent Events stream (MCP-style messages).
  POST /mcp    — JSON-RPC: {"method": "get_players"|"get_fixtures", "params": {...}}
  GET  /health — Health check.
"""

import asyncio
import json
import os
from typing import Any, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent  # type: ignore

app = FastAPI(title="Fantasy PL MCP Server")


# Placeholder tool implementations
async def get_players() -> List[Dict[str, Any]]:
    # TODO: replace with real FPL API calls
    return [{"id": 1, "name": "Placeholder Player"}]


async def get_fixtures() -> List[Dict[str, Any]]:
    # TODO: replace with real FPL API calls
    return [{"id": 1, "event": 1, "kickoff_time": "2026-08-17T15:00:00Z"}]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sse")
async def sse_endpoint(request: Request) -> EventSourceResponse:
    """
    SSE stream that periodically sends MCP-style messages.
    For now, it sends a simple heartbeat; you can extend this to push updates.
    """

    async def event_generator():
        while True:
            # Send a simple MCP-like message every 10 seconds
            msg = {"jsonrpc": "2.0", "method": "ping", "params": {}}
            yield ServerSentEvent(data=json.dumps(msg), event="message")
            await asyncio.sleep(10)

    return EventSourceResponse(event_generator())


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    """
    Simple JSON-RPC handler for MCP tools.
    Body: {"method": "get_players"|"get_fixtures", "params": {...}, "id": 1}
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status_code=400,
        )

    method = body.get("method")
    call_id = body.get("id", 1)

    if method == "get_players":
        result = await get_players()
        return JSONResponse({"jsonrpc": "2.0", "result": result, "id": call_id})
    elif method == "get_fixtures":
        result = await get_fixtures()
        return JSONResponse({"jsonrpc": "2.0", "result": result, "id": call_id})
    else:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": call_id},
            status_code=404,
        )


def main():
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
