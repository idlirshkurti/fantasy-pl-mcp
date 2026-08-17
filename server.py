"""
FastAPI HTTP/SSE wrapper for fantasy-pl-mcp to run on Render.

Endpoints:
  GET  /sse    — Server-Sent Events stream for MCP clients that support SSE.
  POST /mcp    — JSON-RPC style endpoint for Streamable HTTP MCP clients.
  GET  /health — Health check (useful for keep-alive pings).
"""

import asyncio
import json
import os
from typing import AsyncGenerator, Any, Dict

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

# Import the FPL MCP server implementation from the installed package
import fpl_mcp.__main__ as fpl_main  # type: ignore[attr-defined]

app = FastAPI(title="Fantasy PL MCP Server")

# Get the MCP server instance from the package's main
# The package creates a server instance when imported
mcp_server = fpl_main.server  # type: ignore[attr-defined]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/sse")
async def sse_endpoint(request: Request) -> StreamingResponse:
    """
    Server-Sent Events endpoint for MCP clients that expect an SSE stream.
    Yields MCP events as they are produced by the server.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        # Stream MCP events via the server's SSE transport
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
    Accepts a JSON-RPC request body and returns the MCP response.
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
