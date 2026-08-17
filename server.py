"""
MCP HTTP/SSE server that proxies to a local fpl_mcp subprocess.

Endpoints:
  GET  /sse    — Simple SSE heartbeat (can be extended).
  POST /mcp    — JSON-RPC proxy to python -m fpl_mcp (stdio).
  GET  /health — Health check.
"""

import asyncio
import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent  # type: ignore

app = FastAPI(title="Fantasy PL MCP Server")

# Global subprocess handle
fpl_proc: Optional[subprocess.Popen] = None


def start_fpl_subprocess():
    global fpl_proc
    # Start the MCP server from the installed fork
    fpl_proc = subprocess.Popen(
        [sys.executable, "-m", "fpl_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


@app.on_event("startup")
async def startup_event():
    start_fpl_subprocess()


@app.on_event("shutdown")
async def shutdown_event():
    if fpl_proc is not None:
        fpl_proc.terminate()


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
    if fpl_proc is None:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32603, "message": "Server not ready"}, "id": None},
            status_code=503,
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status_code=400,
        )

    # Write request to subprocess stdin
    req_line = json.dumps(body) + "\n"
    fpl_proc.stdin.write(req_line)
    fpl_proc.stdin.flush()

    # Read one response line from stdout
    resp_line = fpl_proc.stdout.readline()
    if not resp_line:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32603, "message": "Subprocess error"}, "id": body.get("id", 1)},
            status_code=500,
        )

    try:
        resp = json.loads(resp_line)
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32603, "message": "Invalid response from subprocess"}, "id": body.get("id", 1)},
            status_code=500,
        )

    return JSONResponse(resp)


def main():
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
