from __future__ import annotations
import asyncio, json, os, re, shutil, signal, subprocess, sys, time, uuid
from pathlib import Path
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("DEMO_MANAGEMENT_HOME", Path.home()/".demo-management"))
DATA.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA / "config.json"
SESSIONS_FILE = DATA / "sessions.json"
DEFAULT_MCP = {"id":"demoignite","name":"DemoIgnite","transport":"http","url":"http://127.0.0.1:8085/mcp","enabled":True,"description":"Demo provisioning and lifecycle management"}
DEFAULTS = {"provider":"ollama","ollama_url":"http://127.0.0.1:11434","model":"","theme":"midnight","mcp_servers":[DEFAULT_MCP],"skills_dir":str(DATA/"skills"),"demoignite_path":""}
DEMOIGNITE_PROCESS = None
DEMOIGNITE_PID_FILE = DATA / "demoignite-process.json"

def read_json(path: Path, default):
    try: return json.loads(path.read_text())
    except Exception: return default

def save_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2))

def config():
    current = read_json(CONFIG_FILE, {})
    merged = {**DEFAULTS, **current}
    if not CONFIG_FILE.exists(): save_json(CONFIG_FILE, merged)
    return merged

def sessions(): return read_json(SESSIONS_FILE, [])
def save_sessions(data): save_json(SESSIONS_FILE, data)

app = FastAPI(title="Demo Management")
app.mount("/static", StaticFiles(directory=ROOT/"app"/"static"), name="static")

@app.get("/", response_class=HTMLResponse)
def home(): return (ROOT/"app"/"templates"/"index.html").read_text()

@app.get("/api/config")
def get_config():
    c=config(); return {k:v for k,v in c.items() if k not in ("api_key",)}

class ConfigUpdate(BaseModel): data: dict[str, Any]
@app.put("/api/config")
def update_config(payload: ConfigUpdate):
    c=config(); allowed={"provider","ollama_url","model","theme","mcp_servers","skills_dir","api_base_url","api_key","demoignite_path"}
    c.update({k:v for k,v in payload.data.items() if k in allowed})
    save_json(CONFIG_FILE,c); return {k:v for k,v in c.items() if k!="api_key"}

class DemoIgniteStart(BaseModel):
    path: str | None = None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def _managed_process_info():
    global DEMOIGNITE_PROCESS
    saved = read_json(DEMOIGNITE_PID_FILE, {})
    if DEMOIGNITE_PROCESS is not None:
        if DEMOIGNITE_PROCESS.poll() is None:
            return {"managed": True, "running": True, "pid": DEMOIGNITE_PROCESS.pid, "path": saved.get("path", config().get("demoignite_path", ""))}
        DEMOIGNITE_PROCESS = None
        DEMOIGNITE_PID_FILE.unlink(missing_ok=True)
        return {"managed": False, "running": False, "pid": None, "path": config().get("demoignite_path", "")}
    pid = saved.get("pid")
    if pid and _pid_alive(int(pid)):
        return {"managed": True, "running": True, "pid": int(pid), "path": saved.get("path", "")}
    if saved:
        DEMOIGNITE_PID_FILE.unlink(missing_ok=True)
    return {"managed": False, "running": False, "pid": None, "path": config().get("demoignite_path", "")}


def _stop_managed_demoignite():
    global DEMOIGNITE_PROCESS
    info = _managed_process_info()
    if not info["running"]:
        DEMOIGNITE_PROCESS = None
        DEMOIGNITE_PID_FILE.unlink(missing_ok=True)
        return {"stopped": False, "managed": False, "message": "No DemoIgnite process managed by this application is running."}
    pid = int(info["pid"])
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.killpg(pid, signal.SIGTERM)
        if DEMOIGNITE_PROCESS is not None:
            try:
                DEMOIGNITE_PROCESS.wait(timeout=8)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=10)
                else:
                    os.killpg(pid, signal.SIGKILL)
        elif os.name != "nt":
            for _ in range(30):
                if not _pid_alive(pid): break
                time.sleep(.2)
            if _pid_alive(pid): os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except Exception as exc:
        raise HTTPException(500, f"Could not stop the managed DemoIgnite process: {exc}")
    finally:
        DEMOIGNITE_PROCESS = None
        DEMOIGNITE_PID_FILE.unlink(missing_ok=True)
    return {"stopped": True, "managed": True, "pid": pid}


@app.get("/api/mcp/demoignite/process")
def demoignite_process_status():
    return _managed_process_info()


@app.post("/api/mcp/demoignite/start")
async def start_demoignite(payload: DemoIgniteStart):
    # Start DemoIgnite from the configured repository directory and track ownership.
    global DEMOIGNITE_PROCESS
    c = config()
    requested_path = (payload.path or c.get("demoignite_path") or "").strip()
    if not requested_path:
        raise HTTPException(400, "Set the DemoIgnite source-code location in Settings first.")
    location = Path(requested_path).expanduser().resolve()
    if not location.is_dir():
        raise HTTPException(400, "The configured DemoIgnite location is not an existing directory.")
    app_file = location / "app.py"
    requirements = location / "requirements.txt"
    if not app_file.is_file() or not requirements.is_file():
        raise HTTPException(400, "The selected directory must contain both app.py and requirements.txt.")

    existing = _managed_process_info()
    if existing["running"]:
        return {"started": True, "already_running": True, "managed": True, "pid": existing["pid"], "path": existing["path"]}

    # Do not launch a second instance if an independently managed MCP endpoint is already healthy.
    probe = await mcp_call("demoignite", "list_demos", {})
    if probe.get("ok"):
        c["demoignite_path"] = str(location)
        save_json(CONFIG_FILE, c)
        return {"started": False, "external": True, "managed": False, "path": str(location), "message": "DemoIgnite is already running outside Demo Management; it will not be managed or stopped by this app."}

    log_dir = DATA / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "demoignite.log"
    bootstrap = '''import os, pathlib, subprocess, sys
root = pathlib.Path.cwd()
venv = root / ".venv"
python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if not python.is_file():
    subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(root / "requirements.txt")])
os.execv(str(python), [str(python), str(root / "app.py")])
'''
    try:
        with log_path.open("ab") as log_file:
            kwargs = {"cwd": str(location), "stdin": subprocess.DEVNULL, "stdout": log_file, "stderr": subprocess.STDOUT}
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                kwargs["start_new_session"] = True
            DEMOIGNITE_PROCESS = subprocess.Popen([sys.executable, "-c", bootstrap], **kwargs)
        c["demoignite_path"] = str(location)
        save_json(CONFIG_FILE, c)
        save_json(DEMOIGNITE_PID_FILE, {"pid": DEMOIGNITE_PROCESS.pid, "path": str(location), "started_at": time.time()})
    except Exception as exc:
        DEMOIGNITE_PROCESS = None
        raise HTTPException(500, f"Could not start DemoIgnite: {exc}")
    return {"started": True, "managed": True, "pid": DEMOIGNITE_PROCESS.pid, "path": str(location), "log": str(log_path)}


@app.post("/api/mcp/demoignite/stop")
def stop_demoignite():
    return _stop_managed_demoignite()


@app.post("/api/mcp/demoignite/restart")
async def restart_demoignite():
    _stop_managed_demoignite()
    return await start_demoignite(DemoIgniteStart(path=None))


@app.on_event("shutdown")
def stop_owned_demoignite_on_app_shutdown():
    # Only stop a process launched and recorded by this application. External MCP servers are untouched.
    try:
        _stop_managed_demoignite()
    except Exception:
        pass

@app.get("/api/ollama/status")
async def ollama_status():
    c=config(); base=c.get("ollama_url",DEFAULTS["ollama_url"]).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            r=await client.get(base+"/api/tags"); r.raise_for_status(); models=r.json().get("models",[])
        return {"available":True,"models":[m.get("name") for m in models if m.get("name")],"url":base}
    except Exception as e: return {"available":False,"models":[],"error":str(e)}

@app.post("/api/ollama/start")
def start_ollama():
    if shutil.which("ollama") is None: return {"started":False,"error":"Ollama executable was not found. Install Ollama, then retry."}
    try:
        subprocess.Popen(["ollama","serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {"started":True}
    except Exception as e: return {"started":False,"error":str(e)}

@app.get("/api/demos")
async def demos():
    result=await mcp_call("demoignite","list_demos",{})
    if result.get("ok"):
        text=result.get("text","")
        structured=result.get("structured")
        if isinstance(structured,(list,dict)):
            return {"connected":True,"items":structured}
        try: return {"connected":True,"items":json.loads(text)}
        except Exception: return {"connected":True,"items":[],"raw":text}
    return {"connected":False,"items":[],"error":result.get("error","DemoIgnite MCP is not reachable")}

async def mcp_call(server_id: str, tool_name: str, arguments: dict):
    c=config(); server=next((s for s in c.get("mcp_servers",[]) if s.get("id")==server_id and s.get("enabled",True)),None)
    if not server: return {"ok":False,"error":f"MCP server '{server_id}' is not configured or enabled."}
    try:
        from mcp import ClientSession, types
        from mcp.client.streamable_http import streamablehttp_client
        from mcp.client.stdio import stdio_client, StdioServerParameters
        if server.get("transport")=="http":
            async with streamablehttp_client(server["url"]) as (read,write,_):
                async with ClientSession(read,write) as session:
                    await session.initialize(); result=await session.call_tool(tool_name,arguments)
        elif server.get("transport")=="stdio":
            params=StdioServerParameters(command=server["command"],args=server.get("args",[]),env={**os.environ,**server.get("env",{})})
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as session:
                    await session.initialize(); result=await session.call_tool(tool_name,arguments)
        else: return {"ok":False,"error":"Unsupported MCP transport."}
        text="\n".join(x.text for x in getattr(result,"content",[]) if getattr(x,"type",None)=="text")
        return {"ok":not getattr(result,"isError",False),"text":text,"structured":getattr(result,"structuredContent",None)}
    except Exception as e: return {"ok":False,"error":str(e)}

async def list_tools():
    c=config(); found=[]
    for server in c.get("mcp_servers",[]):
        if not server.get("enabled",True): continue
        try:
            from mcp import ClientSession
            from mcp.client.streamable_http import streamablehttp_client
            from mcp.client.stdio import stdio_client, StdioServerParameters
            if server.get("transport")=="http":
                cm=streamablehttp_client(server["url"])
                async with cm as (read,write,_):
                    async with ClientSession(read,write) as session:
                        await session.initialize(); res=await session.list_tools()
            else:
                params=StdioServerParameters(command=server["command"],args=server.get("args",[]),env={**os.environ,**server.get("env",{})})
                async with stdio_client(params) as (read,write):
                    async with ClientSession(read,write) as session:
                        await session.initialize(); res=await session.list_tools()
            for t in res.tools:
                found.append({"type":"function","function":{"name":f"{server['id']}__{t.name}","description":t.description or f"MCP tool {t.name}","parameters":t.inputSchema or {"type":"object","properties":{}}}})
        except Exception: pass
    return found

@app.get("/api/mcp/status")
async def mcp_status():
    c=config(); output=[]
    for s in c.get("mcp_servers",[]):
        ok=False; error=""
        if s.get("enabled",True):
            try:
                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client
                from mcp.client.stdio import stdio_client, StdioServerParameters
                if s.get("transport")=="http":
                    async with streamablehttp_client(s["url"]) as (read,write,_):
                        async with ClientSession(read,write) as session:
                            await session.initialize(); await session.list_tools(); ok=True
                elif s.get("transport")=="stdio":
                    params=StdioServerParameters(command=s["command"],args=s.get("args",[]),env={**os.environ,**s.get("env",{})})
                    async with stdio_client(params) as (read,write):
                        async with ClientSession(read,write) as session:
                            await session.initialize(); await session.list_tools(); ok=True
                else: error="Unsupported transport"
            except Exception as e: error=str(e)
        elif not s.get("enabled",True): error="Disabled"
        output.append({"id":s.get("id"),"name":s.get("name"),"connected":ok,"error":error,"enabled":s.get("enabled",True)})
    return output

@app.get("/api/skills")
def get_skills():
    folder=Path(config().get("skills_dir",str(DATA/"skills"))).expanduser(); folder.mkdir(parents=True,exist_ok=True)
    items=[]
    for p in sorted(folder.iterdir()):
        if p.is_dir():
            skill=p/"SKILL.md"; items.append({"name":p.name,"description":skill.read_text(errors="ignore")[:350] if skill.exists() else "No SKILL.md description","path":str(p)})
        elif p.is_file() and p.suffix.lower()==".md": items.append({"name":p.stem,"description":p.read_text(errors="ignore")[:350],"path":str(p)})
    return {"directory":str(folder),"items":items}

class SkillCreate(BaseModel):
    name: str
    content: str

@app.post("/api/skills")
def create_skill(payload: SkillCreate):
    name=payload.name.strip()
    if not name or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for ch in name):
        raise HTTPException(400,"Use only letters, numbers, hyphens, and underscores in the skill name.")
    if not payload.content.strip(): raise HTTPException(400,"Skill instructions cannot be empty.")
    folder=Path(config().get("skills_dir",str(DATA/"skills"))).expanduser(); folder.mkdir(parents=True,exist_ok=True)
    target=folder/name; target.mkdir(parents=True,exist_ok=True)
    (target/"SKILL.md").write_text(payload.content.strip()+"\n")
    return {"ok":True,"name":name}

def _tool_name_set(tools: list[dict]) -> set[str]:
    return {
        item.get("function", {}).get("name", "")
        for item in tools
        if item.get("function", {}).get("name")
    }


def _extract_text_tool_calls(content: str, tools: list[dict]) -> list[dict]:
    """Recover tool calls emitted as text by models that fail to use Ollama's tool_calls field.

    Accepts both valid JSON-like {"name": ..., "parameters": {...}} and the
    common malformed variant {"name": ..., "parameters{...}}. Only names
    advertised by the connected MCP servers are executable.
    """
    allowed = _tool_name_set(tools)
    found: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for match in re.finditer(r'"name"\s*:\s*"([^"]+)"', content):
        name = match.group(1)
        if name not in allowed:
            continue
        tail = content[match.end():]
        param_match = re.search(r'"?parameters"?\s*:?\s*', tail)
        if not param_match:
            continue
        rest = tail[param_match.end():]
        start = rest.find("{")
        if start < 0:
            continue
        depth = 0
        in_string = False
        escaped = False
        end = None
        for index in range(start, len(rest)):
            char = rest[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    end = index + 1
                    break
        if end is None:
            continue
        try:
            arguments = json.loads(rest[start:end])
        except Exception:
            continue
        if not isinstance(arguments, dict):
            continue
        signature = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        if signature in seen:
            continue
        seen.add(signature)
        found.append({"function": {"name": name, "arguments": arguments}})
    return found


def _normalize_tool_arguments(raw: Any) -> dict:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


class ChatRequest(BaseModel): session_id: str|None=None; message: str
@app.get("/api/sessions")
def get_sessions(): return sessions()
@app.post("/api/sessions")
def new_session():
    data=sessions(); item={"id":uuid.uuid4().hex,"title":"New conversation","messages":[],"updated":time.time()}; data.insert(0,item); save_sessions(data); return item
@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    item=next((x for x in sessions() if x["id"]==sid),None)
    if not item: raise HTTPException(404,"Session not found")
    return item

@app.post("/api/chat")
async def chat(req: ChatRequest):
    c=config(); data=sessions(); item=next((x for x in data if x["id"]==req.session_id),None)
    if not item:
        item={"id":uuid.uuid4().hex,"title":req.message[:48],"messages":[],"updated":time.time()}; data.insert(0,item)
    item["messages"].append({"role":"user","content":req.message})
    if item["title"]=="New conversation": item["title"]=req.message[:48]
    if c.get("provider")=="ollama":
        base=c.get("ollama_url",DEFAULTS["ollama_url"]).rstrip("/"); model=c.get("model")
        if not model: raise HTTPException(400,"Select an Ollama model in Settings before chatting.")
        tools=await list_tools()
        skill_context=[]
        skill_dir=Path(c.get("skills_dir",str(DATA/"skills"))).expanduser()
        if skill_dir.exists():
            for sf in sorted(skill_dir.glob("*/SKILL.md")):
                try: skill_context.append(f"\n\n## Skill: {sf.parent.name}\n"+sf.read_text()[:12000])
                except Exception: pass
        messages=[{"role":"system","content":"You are Demo Management, an assistant for discovering, installing, running, monitoring and cleaning up technical demos. Use configured MCP tools whenever the user asks about a specific demo, its details, environments, or actions. Invoke tools using native tool calls; never print tool-call JSON as text. After receiving tool results, answer using those results. Be explicit before destructive cleanup. The user may refer to demos by name, ID, or keywords. Available demos are shown in the right panel. Follow relevant installed skills below."+"".join(skill_context)}]
        messages += [{"role":m["role"],"content":m["content"]} for m in item["messages"][-30:] if m["role"] in ("user","assistant")]
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                for _ in range(6):
                    body={"model":model,"messages":messages,"stream":False}
                    if tools: body["tools"]=tools
                    response=await client.post(base+"/api/chat",json=body); response.raise_for_status(); answer=response.json().get("message",{})
                    content=answer.get("content","") or ""
                    calls=answer.get("tool_calls") or []
                    # Some local models print a pseudo tool-call object in assistant
                    # content instead of populating Ollama's structured tool_calls.
                    # Recover those calls and execute them through the same MCP path.
                    if not calls:
                        calls=_extract_text_tool_calls(content, tools)
                    if not calls:
                        reply=content; break
                    # Preserve the model's native assistant tool-call message when it
                    # exists; otherwise synthesize the standard Ollama conversation turn.
                    if answer.get("tool_calls"):
                        messages.append(answer)
                    else:
                        messages.append({"role":"assistant","content":"","tool_calls":calls})
                    for call in calls:
                        name=call.get("function",{}).get("name","")
                        args=_normalize_tool_arguments(call.get("function",{}).get("arguments",{}))
                        if "__" not in name: output={"ok":False,"error":"Invalid tool route"}
                        else:
                            sid,tname=name.split("__",1)
                            output=await mcp_call(sid,tname,args)
                        # Persist the actual MCP execution as a chat message. This does not
                        # alter tool selection or invocation; it only makes the call visible.
                        item["messages"].append({
                            "role":"tool",
                            "name":name,
                            "arguments":args,
                            "result":output,
                            "content":output.get("text") or output.get("error") or json.dumps(
                                output.get("structured") if output.get("structured") is not None else output,
                                ensure_ascii=False,
                            ),
                        })
                        messages.append({"role":"tool","content":json.dumps(output,ensure_ascii=False),"tool_name":name})
                else: reply="I reached the tool-call limit for this turn. Please continue with a follow-up."
        except Exception as e: reply=f"I couldn't reach the selected Ollama model ({model}). Check Ollama and the model in Settings.\n\nDetails: {e}"
    else:
        reply="The configured remote provider is not yet enabled in this first version. Select Ollama in Settings."
    item["messages"].append({"role":"assistant","content":reply}); item["updated"]=time.time(); save_sessions(data)
    return {"session":item,"reply":reply,"model":c.get("model"),"provider":c.get("provider")}

@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    data=[x for x in sessions() if x["id"]!=sid]; save_sessions(data); return {"ok":True}

@app.get("/api/health")
def health(): return {"ok":True,"name":"Demo Management","version":"1.0.0"}
