"""HTTP/SSE gateway for a local fpl_mcp stdio server."""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse, ServerSentEvent  # type: ignore

logger = logging.getLogger(__name__)
MCP_RESPONSE_TIMEOUT_SECONDS = 25


async def drain_stderr(process: asyncio.subprocess.Process) -> None:
    if process.stderr is None:
        return
    while True:
        line = await process.stderr.readline()
        if not line:
            return
        logger.warning("fpl_mcp stderr: %s", line.decode(errors="replace").rstrip())


async def stop_fpl_process(process: Optional[asyncio.subprocess.Process]) -> None:
    if process is None or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        logger.warning("fpl_mcp did not terminate within five seconds; killing it")
        process.kill()
        await process.wait()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "fpl_mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    app.state.fpl_proc = process
    app.state.fpl_lock = asyncio.Lock()
    app.state.stderr_task = asyncio.create_task(drain_stderr(process))
    logger.info("Started fpl_mcp subprocess with PID %s", process.pid)
    try:
        yield
    finally:
        await stop_fpl_process(process)
        app.state.stderr_task.cancel()
        try:
            await app.state.stderr_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Fantasy PL MCP Server", lifespan=lifespan)


def get_fpl_process(request: Request) -> Optional[asyncio.subprocess.Process]:
    process: Optional[asyncio.subprocess.Process] = getattr(request.app.state, "fpl_proc", None)
    if process is None or process.returncode is not None:
        return None
    return process


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    process = get_fpl_process(request)
    if process is None:
        return JSONResponse({"status": "unhealthy", "fpl_mcp_alive": False}, status_code=503)
    return JSONResponse({"status": "ok", "fpl_mcp_alive": True})


@app.get("/sse")
async def sse_endpoint(request: Request) -> EventSourceResponse:
    async def event_generator():
        while not await request.is_disconnected():
            yield ServerSentEvent(
                data=json.dumps({"jsonrpc": "2.0", "method": "ping", "params": {}}),
                event="message",
            )
            await asyncio.sleep(10)

    return EventSourceResponse(event_generator())


async def forward_request(
    process: asyncio.subprocess.Process, lock: asyncio.Lock, body: dict[str, Any]
) -> dict[str, Any]:
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("fpl_mcp stdio pipes are unavailable")

    async with lock:
        if process.returncode is not None:
            raise RuntimeError(f"fpl_mcp exited with code {process.returncode}")
        process.stdin.write((json.dumps(body) + "\n").encode())
        await process.stdin.drain()
        response_line = await asyncio.wait_for(
            process.stdout.readline(), timeout=MCP_RESPONSE_TIMEOUT_SECONDS
        )

    if not response_line:
        raise RuntimeError("fpl_mcp closed stdout without a response")
    return json.loads(response_line)


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
            status_code=400,
        )

    process = get_fpl_process(request)
    if process is None:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32603, "message": "MCP subprocess unavailable"}, "id": body.get("id")},
            status_code=503,
        )

    try:
        response = await forward_request(process, request.app.state.fpl_lock, body)
    except asyncio.TimeoutError:
        logger.exception("Timed out waiting for fpl_mcp response")
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32603, "message": "MCP subprocess timed out"}, "id": body.get("id")},
            status_code=504,
        )
    except (BrokenPipeError, ConnectionError, RuntimeError, json.JSONDecodeError) as exc:
        logger.exception("fpl_mcp proxy failure: %s", exc)
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32603, "message": "MCP subprocess error"}, "id": body.get("id")},
            status_code=502,
        )

    return JSONResponse(response)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
