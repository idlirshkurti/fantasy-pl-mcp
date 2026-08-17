import asyncio, hmac, json, logging, os, sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log=logging.getLogger(__name__)
VERSION="2026-07-28"; LEGACY="2024-11-05"; TIMEOUT=25
BLOCKED={"update_fpl_credentials"}

def err(id,code,message,status): return JSONResponse({"jsonrpc":"2.0","error":{"code":code,"message":message},"id":id},status_code=status)
def token_ok(value,expected): return bool(expected and value and value.startswith("Bearer ") and hmac.compare_digest(value[7:].strip(),expected))
def allowed(name): return name not in BLOCKED
async def send(p,obj):
    if not p.stdin: raise RuntimeError("stdin unavailable")
    p.stdin.write((json.dumps(obj)+"\n").encode()); await p.stdin.drain()
async def receive(p):
    if not p.stdout: raise RuntimeError("stdout unavailable")
    line=await asyncio.wait_for(p.stdout.readline(),TIMEOUT)
    if not line: raise RuntimeError("stdout closed")
    return json.loads(line)
async def stderr(p):
    if p.stderr:
        while line:=await p.stderr.readline(): log.warning("fpl_mcp stderr: %s",line.decode(errors="replace").rstrip())
async def bootstrap(p):
    id="gateway-init"
    await send(p,{"jsonrpc":"2.0","id":id,"method":"initialize","params":{"protocolVersion":LEGACY,"capabilities":{},"clientInfo":{"name":"fantasy-pl-gateway","version":"0.1.0"}}})
    result=await receive(p)
    if result.get("id")!=id or "error" in result: raise RuntimeError(f"fpl_mcp initialization failed: {result}")
    await send(p,{"jsonrpc":"2.0","method":"notifications/initialized"})
@asynccontextmanager
async def lifespan(app):
    secret=os.getenv("MCP_API_TOKEN")
    if not secret: raise RuntimeError("MCP_API_TOKEN must be configured")
    p=await asyncio.create_subprocess_exec(sys.executable,"-m","fpl_mcp",stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    task=asyncio.create_task(stderr(p))
    try:
        await bootstrap(p); app.state.proc=p; app.state.lock=asyncio.Lock(); app.state.secret=secret; yield
    finally:
        if p.returncode is None:
            p.terminate()
            try: await asyncio.wait_for(p.wait(),5)
            except asyncio.TimeoutError: p.kill(); await p.wait()
        task.cancel()
app=FastAPI(title="Fantasy PL MCP Server",lifespan=lifespan)
def proc(request):
    p=getattr(request.app.state,"proc",None)
    return p if p and p.returncode is None else None
@app.get("/health")
async def health(request):
    return JSONResponse({"status":"ok","fpl_mcp_alive":True,"protocolVersion":VERSION}) if proc(request) else JSONResponse({"status":"unhealthy","fpl_mcp_alive":False},status_code=503)
def valid(request,body):
    if not isinstance(body,dict) or body.get("jsonrpc")!="2.0" or not isinstance(body.get("method"),str): return err(body.get("id") if isinstance(body,dict) else None,-32600,"Invalid Request",400)
    id=body.get("id"); params=body.get("params") if isinstance(body.get("params"),dict) else {}; meta=params.get("_meta") if isinstance(params.get("_meta"),dict) else {}
    if request.headers.get("mcp-protocol-version")!=VERSION or meta.get("io.modelcontextprotocol/protocolVersion")!=VERSION: return err(id,-32020,"Unsupported protocol version",400)
    if request.headers.get("mcp-method")!=body["method"]: return err(id,-32020,"Mcp-Method header does not match request method",400)
    if "application/json" not in request.headers.get("accept","") or "text/event-stream" not in request.headers.get("accept",""): return err(id,-32020,"Accept must include application/json and text/event-stream",400)
@app.post("/mcp")
async def mcp(request:Request):
    if not token_ok(request.headers.get("authorization"),getattr(request.app.state,"secret", "")): return JSONResponse({"jsonrpc":"2.0","error":{"code":-32001,"message":"Unauthorized"},"id":None},status_code=401,headers={"WWW-Authenticate":"Bearer"})
    try: body=await request.json()
    except Exception: return err(None,-32700,"Parse error",400)
    bad=valid(request,body)
    if bad:return bad
    params=body.get("params",{}); name=params.get("name","")
    if body["method"]=="tools/call" and not allowed(name): return err(body.get("id"),-32601,"Tool is not available through the remote gateway",404)
    p=proc(request)
    if not p:return err(body.get("id"),-32603,"MCP subprocess unavailable",503)
    try:
        async with request.app.state.lock:
            await send(p,body)
            if "id" not in body:return JSONResponse(status_code=202,content=None)
            result=await receive(p)
    except asyncio.TimeoutError:return err(body.get("id"),-32603,"MCP subprocess timed out",504)
    except Exception as ex: log.exception("proxy failure: %s",ex); return err(body.get("id"),-32603,"MCP subprocess error",502)
    if body["method"]=="tools/list" and isinstance(result.get("result",{}).get("tools"),list): result["result"]["tools"]=[x for x in result["result"]["tools"] if allowed(x.get("name",""))]
    return JSONResponse(result,status_code=404 if result.get("error",{}).get("code")==-32601 else 200)
def main():
    import uvicorn; uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8000")))
if __name__=="__main__":main()
