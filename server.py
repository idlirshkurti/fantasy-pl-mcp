import asyncio,hmac,json,logging,os,sys
from contextlib import asynccontextmanager
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
log=logging.getLogger(__name__); TIMEOUT=25; BLOCKED={"update_fpl_credentials"}
def error(i,c,m,s):return JSONResponse({"jsonrpc":"2.0","error":{"code":c,"message":m},"id":i},status_code=s)
def auth(v,t):return bool(t and v and v.startswith("Bearer ") and hmac.compare_digest(v[7:].strip(),t))
async def send(p,x):p.stdin.write((json.dumps(x)+"\n").encode());await p.stdin.drain()
async def recv(p):
 l=await asyncio.wait_for(p.stdout.readline(),TIMEOUT)
 if not l:raise RuntimeError("fpl_mcp closed stdout")
 return json.loads(l)
async def drain(p):
 while l:=await p.stderr.readline():log.warning("fpl_mcp stderr: %s",l.decode(errors="replace").rstrip())
@asynccontextmanager
async def life(app):
 token=os.getenv("MCP_API_TOKEN")
 if not token:raise RuntimeError("MCP_API_TOKEN must be configured")
 p=await asyncio.create_subprocess_exec(sys.executable,"-m","fpl_mcp",stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE); task=asyncio.create_task(drain(p))
 try:
  await send(p,{"jsonrpc":"2.0","id":"gateway-init","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"fantasy-pl-gateway","version":"0.1.0"}}});r=await recv(p)
  if r.get("id")!="gateway-init" or "error" in r:raise RuntimeError(f"initialization failed: {r}")
  await send(p,{"jsonrpc":"2.0","method":"notifications/initialized"});app.state.p=p;app.state.lock=asyncio.Lock();app.state.token=token;yield
 finally:
  if p.returncode is None:p.terminate();await p.wait()
  task.cancel()
app=FastAPI(title="Fantasy PL MCP Server",lifespan=life)
@app.get("/health")
async def health():return {"status":"ok"}
@app.post("/mcp")
async def mcp(q:Request):
 if not auth(q.headers.get("authorization"),getattr(q.app.state,"token",None)):return JSONResponse({"jsonrpc":"2.0","error":{"code":-32001,"message":"Unauthorized"},"id":None},401,{"WWW-Authenticate":"Bearer"})
 try:b=await q.json()
 except: return error(None,-32700,"Parse error",400)
 if not isinstance(b,dict) or b.get("jsonrpc")!="2.0" or not isinstance(b.get("method"),str):return error(b.get("id") if isinstance(b,dict) else None,-32600,"Invalid Request",400)
 m=b["method"];i=b.get("id")
 if m=="initialize":return JSONResponse({"jsonrpc":"2.0","id":i,"result":{"protocolVersion":b.get("params",{}).get("protocolVersion","2025-03-26"),"capabilities":{"tools":{}},"serverInfo":{"name":"fantasy-pl","version":"0.1.0"}}})
 if m=="notifications/initialized":return JSONResponse(status_code=202,content=None)
 if m=="tools/call" and b.get("params",{}).get("name") in BLOCKED:return error(i,-32601,"Tool is not available through the remote gateway",404)
 p=getattr(q.app.state,"p",None)
 if not p or p.returncode is not None:return error(i,-32603,"MCP subprocess unavailable",503)
 try:
  async with q.app.state.lock:
   await send(p,b)
   if i is None:return JSONResponse(status_code=202,content=None)
   r=await recv(p)
 except asyncio.TimeoutError:return error(i,-32603,"MCP subprocess timed out",504)
 except Exception as e:log.exception("mcp proxy error: %s",e);return error(i,-32603,"MCP subprocess error",502)
 if m=="tools/list" and isinstance(r.get("result",{}).get("tools"),list):r["result"]["tools"]=[x for x in r["result"]["tools"] if x.get("name") not in BLOCKED]
 return JSONResponse(r,status_code=404 if r.get("error",{}).get("code")==-32601 else 200)
def main():
 import uvicorn;uvicorn.run(app,host="0.0.0.0",port=int(os.getenv("PORT","8000")))
if __name__=="__main__":main()
