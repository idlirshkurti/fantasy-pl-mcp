"""Streamable HTTP gateway for a local legacy fpl_mcp stdio server."""

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
MCP_PROTOCOL_VERSION = "2026-07-28"
LEGACY_MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_RESPONSE_TIMEOUT_SECONDS = 25


def jsonrpc_error(call_id: Any, code: int, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": call_id},
        status_code=status_code,
    )


def allowed_origins() -> set[str]:
    return {origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "").split(",") if origin.strip()}


async def drain_stderr(process: asyncio.subprocess.Process) -> None:
    if process.stderr is None:
        return
    while line := await process.stderr.readline():
        logger.warning("fpl_mcp stderr: %s", line.decode(errors="replace").rstrip())


async def send_message(process: asyncio.subprocess.Process, body: dict[str, Any]) -> None:
    if process.stdin is None:
        raise RuntimeError("fpl_mcp stdin is unavailable")
    process.stdin.write((json.dumps(body) + "\n").encode())
    await process.stdin.drain()


async def read_response(process: asyncio.subprocess.Process) -> dict[str, Any]:
    if process.stdout is None:
        raise RuntimeError("fpl_mcp stdout is unavailable")
    response_line = await asyncio.wait_for(process.stdout.readline(), timeout=MCP_RESPONSE_TIMEOUT_SECONDS)
    if not response_line:
        raise RuntimeError("fpl_mcp closed stdout without a response")
    return json.loads(response_line)


async def bootstrap_legacy_server(process: asyncio.subprocess.Process) -> None:
    request_id = "streamable-http-gateway-initialize"
    await send_message(
        process,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "initialize",
            "params": {
                "protocolVersion": LEGACY_MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "fantasy-pl-streamable-http-gateway", "version": "0.1.0"},
            },
        },
    )
    response = await read_response(process)
    if response.get("id") != request_id or "error" in response:
        raise RuntimeError(f"fpl_mcp initialization failed: {response}")
    await send_message(process, {"jsonrpc": "2.0", "method": "notifications/initialized"})


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
    stderr_task = asyncio.create_task(drain_stderr(process))
    try:
        await bootstrap_legacy_server(process)
        app.state.fpl_proc = process
        app.state.fpl_lock = asyncio.Lock()
        app.state.stderr_task = stderr_task
        logger.info("Started and initialized fpl_mcp subprocess with PID %s", process.pid)
        yield
    finally:
        await stop_fpl_process(process)
        stderr_task.cancel()
        try:
            await stderr_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Fantasy PL MCP Server", lifespan=lifespan)


def get_fpl_process(request: Request) -> Optional[asyncio.subprocess.Process]:
    process: Optional[asyncio.subprocess.Process] = getattr(request.app.state, "fpl_proc", None)
    if process is None or process.returncode is not None:
        return None
    return process


def validate_streamable_http_request(request: Request, body: Any) -> Optional[JSONResponse]:
    origin = request.headers.get("origin")
    if origin is not None and origin not in allowed_origins():
        return jsonrpc_error(None, -32000, "Forbidden origin", 403)

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return jsonrpc_error(body.get("id") if isinstance(body, dict) else None, -32600, "Invalid Request", 400)

    call_id = body.get("id")
    accept = request.headers.get("accept", "")
    if "application/json" not in accept or "text/event-stream" not in accept:
        return jsonrpc_error(call_id, -32020, "Accept must include application/json and text/event-stream", 400)

    protocol_version = request.headers.get("mcp-protocol-version")
    if protocol_version != MCP_PROTOCOL_VERSION:
        return jsonrpc_error(call_id, -32020, f"Unsupported protocol version; supported: {MCP_PROTOCOL_VERSION}", 400)

    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    metadata = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    if metadata.get("io.modelcontextprotocol/protocolVersion") != protocol_version:
        return jsonrpc_error(call_id, -32020, "MCP-Protocol-Version header does not match request metadata", 400)

    if request.headers.get("mcp-method") != body["method"]:
        return jsonrpc_error(call_id, -32020, "Mcp-Method header does not match request method", 400)

    if body["method"] in {"tools/call", "resources/read", "prompts/get"}:
        name = params.get("name") if body["method"] == "tools/call" else params.get("uri")
        if not isinstance(name, str) or request.headers.get("mcp-name") != name:
            return jsonrpc_error(call_id, -32020, "Mcp-Name header does not match request parameters", 400)

    return None


@app.get("/health")
async def health(request: Request) -> JSONResponse:
    process = get_fpl_process(request)
    if process is None:
        return JSONResponse({"status": "unhealthy", "fpl_mcp_alive": False}, status_code=503)
    return JSONResponse({"status": "ok", "fpl_mcp_alive": True, "protocolVersion": MCP_PROTOCOL_VERSION})


async def forward_request(process: asyncio.subprocess.Process, lock: asyncio.Lock, body: dict[str, Any]) -> dict[str, Any]:
    async with lock:
        if process.returncode is not None:
            raise RuntimeError(f"fpl_mcp exited with code {process.returncode}")
        await send_message(process, body)
        return await read_response(process)


@app.post("/mcp")
async def mcp_endpoint(request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:
        return jsonrpc_error(None, -32700, "Parse error", 400)

    validation_error = validate_streamable_http_request(request, body)
    if validation_error is not None:
        return validation_error

    process = get_fpl_process(request)
    if process is None:
        return jsonrpc_error(body.get("id"), -32603, "MCP subprocess unavailable", 503)

    if "id" not in body:
        try:
            async with request.app.state.fpl_lock:
                await send_message(process, body)
        except (BrokenPipeError, ConnectionError, RuntimeError) as exc:
            logger.exception("fpl_mcp notification failure: %s", exc)
            return jsonrpc_error(None, -32603, "MCP subprocess error", 502)
        return JSONResponse(status_code=202, content=None)

    try:
        response = await forward_request(process, request.app.state.fpl_lock, body)
    except asyncio.TimeoutError:
        logger.exception("Timed out waiting for fpl_mcp response")
        return jsonrpc_error(body["id"], -32603, "MCP subprocess timed out", 504)
    except (BrokenPipeError, ConnectionError, RuntimeError, json.JSONDecodeError) as exc:
        logger.exception("fpl_mcp proxy failure: %s", exc)
        return jsonrpc_error(body["id"], -32603, "MCP subprocess error", 502)

    status_code = 404 if response.get("error", {}).get("code") == -32601 else 200
    return JSONResponse(response, status_code=status_code)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
