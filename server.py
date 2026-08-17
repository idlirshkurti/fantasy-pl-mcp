import asyncio
import hmac
import json
import logging
import os
import sys
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)
TIMEOUT = 25
BLOCKED = {"update_fpl_credentials"}
PUBLIC_TEAM_TOOLS = {"get_team", "get_my_team", "get_my_current_team"}
FPL_API = "https://fantasy.premierleague.com/api"


def error(request_id, code, message, status):
    return JSONResponse(
        {"jsonrpc": "2.0", "error": {"code": code, "message": message}, "id": request_id},
        status_code=status,
    )


def auth(value, token):
    return bool(token and value and value.startswith("Bearer ") and hmac.compare_digest(value[7:].strip(), token))


async def send(proc, payload):
    if not proc.stdin:
        raise RuntimeError("fpl_mcp stdin unavailable")
    proc.stdin.write((json.dumps(payload) + "\n").encode())
    await proc.stdin.drain()


async def recv(proc):
    if not proc.stdout:
        raise RuntimeError("fpl_mcp stdout unavailable")
    line = await asyncio.wait_for(proc.stdout.readline(), TIMEOUT)
    if not line:
        raise RuntimeError("fpl_mcp closed stdout")
    return json.loads(line)


async def drain(proc):
    if proc.stderr:
        while line := await proc.stderr.readline():
            log.warning("fpl_mcp stderr: %s", line.decode(errors="replace").rstrip())


async def public_team(team_id, gameweek):
    try:
        team_id = int(team_id)
    except (TypeError, ValueError):
        raise ValueError("team_id must be a positive integer")
    if team_id < 1:
        raise ValueError("team_id must be a positive integer")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        if gameweek is None:
            bootstrap = (await client.get(f"{FPL_API}/bootstrap-static/")).raise_for_status().json()
            events = bootstrap.get("events", [])
            active = next((event for event in events if event.get("is_current")), None)
            active = active or next((event for event in events if event.get("is_next")), None)
            active = active or next((event for event in reversed(events) if event.get("finished")), None)
            if not active:
                raise RuntimeError("FPL did not provide a gameweek")
            gameweek = active["id"]
        else:
            try:
                gameweek = int(gameweek)
            except (TypeError, ValueError):
                raise ValueError("gameweek must be an integer")

        response = await client.get(f"{FPL_API}/entry/{team_id}/event/{gameweek}/picks/")
        response.raise_for_status()
        data = response.json()

    return {"team_id": team_id, "gameweek": gameweek, **data}


def tool_result(request_id, data):
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"content": [{"type": "text", "text": json.dumps(data)}]},
        }
    )


@asynccontextmanager
async def life(app):
    token = os.getenv("MCP_API_TOKEN")
    if not token:
        raise RuntimeError("MCP_API_TOKEN must be configured")
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "fpl_mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    task = asyncio.create_task(drain(proc))
    try:
        await send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": "gateway-init",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "fantasy-pl-gateway", "version": "0.1.0"},
                },
            },
        )
        result = await recv(proc)
        if result.get("id") != "gateway-init" or "error" in result:
            raise RuntimeError(f"initialization failed: {result}")
        await send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        app.state.proc = proc
        app.state.lock = asyncio.Lock()
        app.state.token = token
        yield
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        task.cancel()


app = FastAPI(title="Fantasy PL MCP Server", lifespan=life)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/mcp")
async def mcp(request: Request):
    if not auth(request.headers.get("authorization"), getattr(request.app.state, "token", None)):
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Unauthorized"}, "id": None},
            401,
            {"WWW-Authenticate": "Bearer"},
        )
    try:
        body = await request.json()
    except Exception:
        return error(None, -32700, "Parse error", 400)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return error(body.get("id") if isinstance(body, dict) else None, -32600, "Invalid Request", 400)

    method = body["method"]
    request_id = body.get("id")
    if method == "initialize":
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": body.get("params", {}).get("protocolVersion", "2025-03-26"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fantasy-pl", "version": "0.1.0"},
                },
            }
        )
    if method == "notifications/initialized":
        return JSONResponse(status_code=202, content=None)

    params = body.get("params", {})
    tool_name = params.get("name") if isinstance(params, dict) else None
    if method == "tools/call" and tool_name in BLOCKED:
        return error(request_id, -32601, "Tool is not available through the remote gateway", 404)
    if method == "tools/call" and tool_name in PUBLIC_TEAM_TOOLS:
        arguments = params.get("arguments", {}) if isinstance(params, dict) else {}
        if not isinstance(arguments, dict):
            return error(request_id, -32602, "Tool arguments must be an object", 400)
        team_id = arguments.get("team_id")
        if tool_name in {"get_my_team", "get_my_current_team"}:
            team_id = os.getenv("FPL_TEAM_ID")
        if not team_id:
            return error(request_id, -32602, "FPL_TEAM_ID must be configured for this tool", 400)
        try:
            return tool_result(request_id, await public_team(team_id, arguments.get("gameweek")))
        except ValueError as exc:
            return error(request_id, -32602, str(exc), 400)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            message = "FPL team or gameweek was not found" if status == 404 else f"FPL API returned HTTP {status}"
            return error(request_id, -32603, message, 502)
        except Exception as exc:
            log.exception("public team lookup failed: %s", exc)
            return error(request_id, -32603, "FPL public team lookup failed", 502)

    proc = getattr(request.app.state, "proc", None)
    if not proc or proc.returncode is not None:
        return error(request_id, -32603, "MCP subprocess unavailable", 503)
    try:
        async with request.app.state.lock:
            await send(proc, body)
            if request_id is None:
                return JSONResponse(status_code=202, content=None)
            result = await recv(proc)
    except asyncio.TimeoutError:
        return error(request_id, -32603, "MCP subprocess timed out", 504)
    except Exception as exc:
        log.exception("mcp proxy error: %s", exc)
        return error(request_id, -32603, "MCP subprocess error", 502)

    if method == "tools/list" and isinstance(result.get("result", {}).get("tools"), list):
        result["result"]["tools"] = [
            tool for tool in result["result"]["tools"] if tool.get("name") not in BLOCKED
        ]
    return JSONResponse(result, status_code=404 if result.get("error", {}).get("code") == -32601 else 200)


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
