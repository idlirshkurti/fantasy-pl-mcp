"""
MCP HTTP/SSE server for Fantasy PL with plain FastAPI + sse_starlette.

Endpoints:
  GET  /sse    — Server-Sent Events stream (MCP-style messages).
  POST /mcp    — JSON-RPC: initialize, tools/list, tools/call, etc.
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


# Tool implementations
async def get_players() -> List[Dict[str, Any]]:
    # TODO: replace with real FPL API calls
    return [{"id": 1, "name": "Placeholder Player"}]


async def get_fixtures() -> List[Dict[str, Any]]:
    # TODO: replace with real FPL API calls
    return [{"id": 1, "event": 1, "kickoff_time": "2026-08-17T15:00:00Z"}]


# MCP tool definitions
TOOLS = [
    {
        "name": "get_players",
        "description": "Get all FPL players with stats",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_fixtures",
        "description": "Get FPL fixtures",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sse")
async def sse_endpoint(request: Request) -> EventSourceResponse:
    async def event_generator():
        while True:
            msg = {"jsonrpc": "2.0", "method": "ping", "params": {}}
            yield ServerSentEvent(data=json.dumps(msg), event="message")
            await asyncio.sleep(10)
    return EventSourceResponse(event_generator())


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status_code=400,
        )

    method = body.get("method")
    call_id = body.get("id", 1)
    params = body.get("params", {})

    # MCP handshake & tool discovery
    if method == "initialize":
        return JSONResponse({
            "jsonrpc": "2.0",
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "fantasy-pl", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
            "id": call_id,
        })

    if method == "tools/list":
        return JSONResponse({
            "jsonrpc": "2.0",
            "result": {"tools": TOOLS},
            "id": call_id,
        })

    if method == "tools/call":
        tool_name = params.get("name")
        if tool_name == "get_players":
            result = await get_players()
            return JSONResponse({
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
                "id": call_id,
            })
        elif tool_name == "get_fixtures":
            result = await get_fixtures()
            return JSONResponse({
                "jsonrpc": "2.0",
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
                "id": call_id,
            })
        else:
            return JSONResponse({
                "jsonrpc": "2.0",
                "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"},
                "id": call_id,
            }, status_code=400)

    # Fallback for unknown methods
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
