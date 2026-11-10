"""Servidor MCP para agentes externos — réplica de fincept-qt/src/mcp/server/McpHttpServer*.

    POST /mcp    JSON-RPC 2.0 (petición, notificación o batch) — Streamable HTTP sin estado
    GET  /mcp    405 (no hay stream iniciado por el servidor)

Reglas copiadas del original:
* Sin Mcp-Session-Id: cada POST se responde con application/json. Solo
  notificaciones/respuestas → 202 sin cuerpo. JSON inválido → 400 + -32700.
* `Authorization: Bearer <token>` obligatorio. El token es estable (vive en la
  BD) y regenerarlo revoca a todos los clientes.
* Defensa DNS-rebinding: Host debe ser loopback; Origin (si viene) también;
  peticiones de navegador cross-site que no sean navegación se rechazan.
* Toolsets: "essentials" (meta-tools + lecturas clave) o "full".
* Tools que cambian estado: rechazadas salvo que el usuario active
  "allow actions"; las marcadas needs_approval piden además confirmación en la
  UI del terminal para *cada* llamada (ToolApprovalDialog).
* Protocolo de jobs: si una tool supera la ventana de gracia devuelve
  {job_id, status:"running"}; el cliente usa job_status/job_result.
* Resultados > 24 KB se truncan y el resto se pagina con result_fetch.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
import sys
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from .auth import require_auth
from .config import ROOT, VERSION, settings
from .datahub import hub
from .db import get_db
from .formatting import to_markdown
from .tools import REGISTRY, ToolContext, ToolDef, ToolError, call_tool, search_tools

router = APIRouter()

PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
ESSENTIAL_READS = ["get_quote", "get_quotes", "get_history", "lookup_symbol", "get_technicals", "get_top_news",
                   "get_equity_news", "search_dbnomics", "get_dbnomics_observations", "compute_risk",
                   "bs_option_price", "pt_get_account", "pt_get_orders", "get_watchlists", "fund_get_state"]
APPROVAL_TIMEOUT_S = 90

def _p(typ: str, desc: str, **kw) -> dict:
    return {"type": typ, "description": desc, **kw}


_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
JOB_ID = _p("string", "Id returned in a {job_id, status:'running'} receipt.", maxLength=40)
META_TOOLS: dict[str, dict] = {
    "tool_list": {"title": "Search tool catalogue",
                  "description": "Search the whole tool catalogue (BM25) by what you need, e.g. 'option pricing' "
                                 "or 'unemployment'. Returns names, one-line descriptions and whether they change "
                                 "state. Then call tool_describe or tool_invoke.",
                  "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
                      "query": _p("string", "What you need, in plain words.", maxLength=120),
                      "limit": _p("integer", "Max tools to return (default 15).", minimum=1, maximum=50)}},
                  "annotations": _RO},
    "tool_describe": {"title": "Describe a tool", "description": "Full input schema, annotations and policy of one "
                                                                "tool found with tool_list.",
                      "inputSchema": {"type": "object", "additionalProperties": False, "required": ["name"],
                                      "properties": {"name": _p("string", "Tool name, e.g. 'get_history'.")}},
                      "annotations": _RO},
    "tool_invoke": {"title": "Invoke any tool",
                    "description": "Call any built-in tool found through tool_list (useful when it is not in your "
                                   "tool list). Same policy as calling it directly: state-changing tools may be "
                                   "refused or need the user's approval.",
                    "inputSchema": {"type": "object", "additionalProperties": False, "required": ["tool"],
                                    "properties": {"tool": _p("string", "Tool name."),
                                                   "arguments": _p("object", "Arguments for that tool.")}},
                    "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False,
                                    "openWorldHint": True}},
    "job_status": {"title": "Job status", "description": "Status of a long-running job (running, completed, failed, "
                                                       "cancelled). Waits up to wait_ms for it to finish.",
                   "inputSchema": {"type": "object", "additionalProperties": False, "required": ["job_id"],
                                   "properties": {"job_id": JOB_ID, "wait_ms": _p(
                                       "integer", "Max milliseconds to wait (0-30000).", minimum=0, maximum=30000)}},
                   "annotations": {**_RO, "idempotentHint": False}},
    "job_result": {"title": "Job result", "description": "Result of a completed job (same format as the tool).",
                   "inputSchema": {"type": "object", "additionalProperties": False, "required": ["job_id"],
                                   "properties": {"job_id": JOB_ID}}, "annotations": _RO},
    "job_cancel": {"title": "Cancel job", "description": "Cancel a running job.",
                   "inputSchema": {"type": "object", "additionalProperties": False, "required": ["job_id"],
                                   "properties": {"job_id": JOB_ID}},
                   "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True,
                                   "openWorldHint": False}},
    "job_list": {"title": "List jobs", "description": "Your 20 most recent jobs and their status.",
                 "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
                 "annotations": {**_RO, "idempotentHint": False}},
    "result_fetch": {"title": "Fetch truncated result",
                     "description": "Page through a result that exceeded the response budget (its first part came "
                                    "back with truncated=true and a result_id).",
                     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["result_id"],
                                     "properties": {"result_id": _p("string", "result_id from the truncation note."),
                                                    "offset": _p("integer", "Character offset.", minimum=0),
                                                    "limit": _p("integer", "Characters to return.", minimum=1)}},
                     "annotations": _RO},
}


@dataclass
class Job:
    id: str
    user_id: int
    tool: str
    task: asyncio.Task
    fmt: str = "json"
    started: float = field(default_factory=time.time)
    finished: float | None = None


@dataclass
class UserMcpState:
    toolset: str = "essentials"
    activity: deque = field(default_factory=lambda: deque(maxlen=200))
    clients: dict = field(default_factory=dict)  # user-agent -> clientInfo.name
    approvals: dict = field(default_factory=dict)  # approval_id -> Future
    calls: deque = field(default_factory=deque)  # timestamps para el rate limit


JOBS: dict[str, Job] = {}
RESULTS: dict[str, tuple[int, str, float]] = {}  # result_id -> (user_id, full_text, created)
STATE: dict[int, UserMcpState] = {}


def state(uid: int) -> UserMcpState:
    return STATE.setdefault(uid, UserMcpState())


def rpc_result(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def rpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


log = logging.getLogger("fincept.mcp")
RATE_LIMIT_CALLS, RATE_LIMIT_WINDOW = 120, 60.0
RESPONSE_FORMAT = {"type": "string", "enum": ["json", "markdown"], "default": "json",
                   "description": "'json' (default) for structured data, 'markdown' for a compact readable summary."}


def structured(value: Any) -> dict:
    """structuredContent debe ser un objeto JSON: las listas se envuelven en {items, count}."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {"items": value, "count": len(value)}
    return {"value": value}


def text_result(payload: Any, is_error: bool = False) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str)
    out = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if not isinstance(payload, str) and not is_error:
        out["structuredContent"] = structured(json.loads(text))
    return out


def public_schema(t: ToolDef) -> dict:
    """Esquema anunciado: el de la tool + response_format (lo gestiona el servidor, no la tool)."""
    sch = t.schema()
    props = {**sch["inputSchema"].get("properties", {}), "response_format": RESPONSE_FORMAT}
    return {**sch, "inputSchema": {**sch["inputSchema"], "properties": props}}


def instructions() -> str:
    return "\n".join([
        "Fincept Lite is the user's running financial terminal: live quotes, price history, news, macro data "
        "(DBnomics), analytics, watchlists and a paper-trading account.",
        "- Discover: tool_list(query) searches the whole catalogue; tool_describe(name) returns one tool's schema.",
        "- Call: use a listed tool directly, or any tool found through tool_list with tool_invoke(tool, arguments).",
        '- Long-running tools answer {"job_id", "status":"running"}: poll job_status(job_id, wait_ms=20000), then '
        "job_result(job_id). Do not start the tool again.",
        "- Results over the response budget come back truncated with a result_id; page with result_fetch.",
        "- State-changing tools (orders, watchlists) run only if the user allowed actions for external agents; "
        "paper orders also need the user's approval in the terminal for every call. If refused, tell the user "
        "what you wanted to do instead of retrying.",
        "- Quote tool results, never guess prices or figures.",
    ])


# ── guardas ─────────────────────────────────────────────────────────────────

def _host_ok(host_header: str | None) -> bool:
    if not host_header:
        return False
    host = urlsplit("//" + host_header).hostname or ""
    return host in LOOPBACK or host in {h.lower() for h in settings.extra_allowed_hosts} or \
        f"[{host}]" in LOOPBACK


def guard(request: Request) -> JSONResponse | None:
    h = request.headers
    if not _host_ok(h.get("host")):
        return JSONResponse(status_code=403, content={"error": "forbidden host"})
    origin = h.get("origin")
    if origin and origin != "null":
        oh = urlsplit(origin).hostname or ""
        if oh not in LOOPBACK and oh not in settings.extra_allowed_hosts:
            return JSONResponse(status_code=403, content={"error": "forbidden origin"})
    site, mode = h.get("sec-fetch-site"), h.get("sec-fetch-mode")
    if site in {"cross-site", "same-site"} and mode != "navigate":
        return JSONResponse(status_code=403, content={"error": "cross-site request refused"})
    return None


def user_for_token(auth_header: str | None) -> dict | None:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None
    return get_db().one("SELECT * FROM users WHERE mcp_token=?", (token,))


def ensure_token(uid: int) -> str:
    row = get_db().one("SELECT mcp_token FROM users WHERE id=?", (uid,))
    if row and row["mcp_token"]:
        return row["mcp_token"]
    tok = "fmcp_" + secrets.token_urlsafe(32)
    get_db().execute("UPDATE users SET mcp_token=? WHERE id=?", (tok, uid))
    return tok


# ── actividad / aprobaciones ────────────────────────────────────────────────

async def record(uid: int, client: str, tool: str, success: bool, denied: bool, started: float, summary: str) -> None:
    rec = {"at": time.time(), "client": client, "tool": tool, "success": success, "denied": denied,
           "duration_ms": int((time.time() - started) * 1000), "summary": summary[:200]}
    st = state(uid)
    st.activity.appendleft(rec)
    await hub.publish(f"mcp:{uid}:activity", list(st.activity)[:50])


async def request_approval(uid: int, client: str, tool: str, args: dict) -> tuple[bool, str]:
    topic = f"mcp:{uid}:approvals"
    ts = hub.topics.get(topic)
    if not ts or not ts.subscribers:
        return False, "no terminal window is open to approve this call"
    st = state(uid)
    aid = uuid.uuid4().hex[:12]
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    st.approvals[aid] = fut
    summary = ", ".join(f"{k}={v}" for k, v in args.items())[:300]
    await hub.publish(topic, {"pending": [{"id": aid, "client": client, "tool": tool, "summary": summary,
                                            "expires_at": time.time() + APPROVAL_TIMEOUT_S}]})
    try:
        approved = await asyncio.wait_for(fut, APPROVAL_TIMEOUT_S)
        return bool(approved), "approved by user" if approved else "denied by user"
    except asyncio.TimeoutError:
        return False, "approval timed out"
    finally:
        st.approvals.pop(aid, None)
        await hub.publish(topic, {"pending": [], "resolved": aid})


# ── empaquetado de resultados ───────────────────────────────────────────────

def package(uid: int, value: Any, fmt: str = "json", title: str = "") -> dict:
    as_json = json.dumps(value, ensure_ascii=False, default=str)
    text = to_markdown(json.loads(as_json), title) if fmt == "markdown" else as_json
    raw = text.encode()
    if len(raw) <= settings.mcp_result_budget:
        out = {"content": [{"type": "text", "text": text}], "isError": False}
        if len(as_json.encode()) <= settings.mcp_result_budget:  # structuredContent no se salta el presupuesto
            out["structuredContent"] = structured(json.loads(as_json))
        return out
    rid = uuid.uuid4().hex[:16]
    RESULTS[rid] = (uid, text, time.time())
    head = raw[: settings.mcp_result_budget].decode(errors="ignore")
    note = {"truncated": True, "result_id": rid, "total_chars": len(text), "returned_chars": len(head),
            "hint": "call result_fetch(result_id, offset, limit) for the rest"}
    return {"content": [{"type": "text", "text": head}, {"type": "text", "text": json.dumps(note)}], "isError": False}


# ── ejecución de tools ──────────────────────────────────────────────────────

async def run_tool(user: dict, client: str, name: str, args: dict, allow_defer: bool = True) -> dict:
    uid, started = user["id"], time.time()
    t = REGISTRY.get(name)
    if t is None:
        raise KeyError(name)
    args = dict(args)
    fmt = args.pop("response_format", "json")
    if fmt not in ("json", "markdown"):
        return text_result("Error: response_format must be 'json' or 'markdown'.", True)
    st = state(uid)
    while st.calls and st.calls[0] < started - RATE_LIMIT_WINDOW:
        st.calls.popleft()
    if len(st.calls) >= RATE_LIMIT_CALLS:
        wait = int(st.calls[0] + RATE_LIMIT_WINDOW - started) + 1
        await record(uid, client, name, False, True, started, "rate limited")
        return text_result(f"Error: rate limit of {RATE_LIMIT_CALLS} tool calls per minute reached. Retry in {wait} s, "
                           "or batch work (get_quotes takes up to 25 tickers).", True)
    st.calls.append(started)
    fresh = get_db().one("SELECT mcp_allow_actions FROM users WHERE id=?", (uid,))
    if t.destructive and not (fresh and fresh["mcp_allow_actions"]):
        msg = (f"Refused: '{name}' changes state and external agents are not allowed to take actions. "
               "The user can enable it in the terminal: MCP → Allow actions.")
        await record(uid, client, name, False, True, started, "refused: actions disabled")
        return text_result(msg, True)
    if t.needs_approval:
        ok, why = await request_approval(uid, client, name, args)
        if not ok:
            await record(uid, client, name, False, True, started, why)
            return text_result(f"Refused: {why}. Tell the user what you wanted to do instead of retrying.", True)
    ctx = ToolContext(user=user, source="mcp", client=client)
    task = asyncio.create_task(call_tool(name, args, ctx))
    try:
        value = await asyncio.wait_for(asyncio.shield(task), settings.mcp_grace_seconds if allow_defer else None)
    except asyncio.TimeoutError:
        jid = "job_" + uuid.uuid4().hex[:12]
        job = Job(jid, uid, name, task, fmt)
        JOBS[jid] = job

        def _done(_t: asyncio.Task, job=job) -> None:
            job.finished = time.time()
            asyncio.create_task(record(uid, client, name, not _t.cancelled() and _t.exception() is None, False,
                                       started, "job finished"))
        task.add_done_callback(_done)
        return text_result({"job_id": jid, "status": "running", "tool": name,
                            "hint": "poll job_status(job_id, wait_ms=20000), then job_result(job_id)"})
    except ToolError as e:
        await record(uid, client, name, False, False, started, str(e))
        return text_result(f"Error: {e}", True)
    except Exception:  # el error de una tool nunca tumba el servidor ni filtra detalles internos
        err_id = uuid.uuid4().hex[:8]
        log.exception("tool %s failed (error id %s)", name, err_id)
        await record(uid, client, name, False, False, started, f"internal error {err_id}")
        return text_result(f"Error: internal error while running {name} (id {err_id}). It was logged on the "
                           "server; retry later or use another tool.", True)
    await record(uid, client, name, True, False, started, "ok")
    return package(uid, value, fmt, t.title)


def _job_view(job: Job) -> dict:
    t = job.task
    status = "running" if not t.done() else "cancelled" if t.cancelled() else "failed" if t.exception() else "completed"
    out = {"job_id": job.id, "tool": job.tool, "status": status, "elapsed_ms": int(((job.finished or time.time())
                                                                                   - job.started) * 1000)}
    if status == "failed":
        exc = t.exception()
        out["error"] = str(exc) if isinstance(exc, ToolError) else "internal error (logged on the server)"
    return out


async def call_meta(user: dict, client: str, name: str, args: dict) -> dict:
    uid = user["id"]
    if name == "tool_list":
        found = search_tools(str(args.get("query", "")), int(args.get("limit", 15)))
        return text_result([{"name": t.name, "description": t.description, "category": t.category,
                             "changes_state": t.destructive} for t in found])
    if name == "tool_describe":
        t = REGISTRY.get(str(args.get("name", "")))
        if not t:
            return text_result(f"Error: unknown tool {args.get('name')!r}. Search with tool_list(query=...).", True)
        return text_result({**public_schema(t), "changes_state": t.destructive, "needs_approval": t.needs_approval,
                            "long_running": t.long_running})
    if name == "tool_invoke":
        target = str(args.get("tool", ""))
        if target in META_TOOLS or target not in REGISTRY:
            return text_result(f"Error: tool_invoke can only call built-in data tools; {target!r} is not one", True)
        return await run_tool(user, client, target, args.get("arguments") or {})
    if name in {"job_status", "job_result", "job_cancel"}:
        job = JOBS.get(str(args.get("job_id", "")))
        if not job or job.user_id != uid:
            return text_result("Error: unknown job_id", True)
        if name == "job_cancel":
            job.task.cancel()
            return text_result({"job_id": job.id, "status": "cancelled"})
        if name == "job_status":
            wait = max(0, min(30_000, int(args.get("wait_ms", 0)))) / 1000
            if wait and not job.task.done():
                await asyncio.wait({job.task}, timeout=wait)
            return text_result(_job_view(job))
        view = _job_view(job)
        if view["status"] == "running":
            return text_result({**view, "hint": "not finished yet; call job_status with wait_ms"})
        if view["status"] != "completed":
            return text_result(view, True)
        return package(uid, job.task.result(), job.fmt, REGISTRY[job.tool].title)
    if name == "job_list":
        return text_result([_job_view(j) for j in JOBS.values() if j.user_id == uid][-20:])
    if name == "result_fetch":
        hit = RESULTS.get(str(args.get("result_id", "")))
        if not hit or hit[0] != uid:
            return text_result("Error: unknown or expired result_id", True)
        off = max(0, int(args.get("offset", 0)))
        lim = max(1, min(settings.mcp_result_budget, int(args.get("limit", settings.mcp_result_budget))))
        chunk = hit[1][off: off + lim]
        return text_result({"offset": off, "returned": len(chunk), "total_chars": len(hit[1]),
                            "done": off + len(chunk) >= len(hit[1]), "data": chunk})
    raise KeyError(name)


def advertised_tools(uid: int) -> list[dict]:
    st = state(uid)
    names = list(META_TOOLS) + (ESSENTIAL_READS if st.toolset == "essentials" else list(REGISTRY))
    out = []
    for n in names:
        if n in META_TOOLS:
            m = META_TOOLS[n]
            out.append({"name": n, **m, "annotations": {"title": m["title"], **m["annotations"]}})
        elif n in REGISTRY:
            t = REGISTRY[n]
            if st.toolset == "essentials" and t.destructive:
                continue
            out.append(public_schema(t))
    return out


# ── dispatcher JSON-RPC ─────────────────────────────────────────────────────

async def handle_message(msg: Any, user: dict, ua: str) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return rpc_error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
    if "method" not in msg:
        return None  # respuesta del cliente a algo nuestro → ignorar
    method, mid, params = msg["method"], msg.get("id"), msg.get("params") or {}
    is_notification = "id" not in msg
    st = state(user["id"])
    client = st.clients.get(ua, "unknown")
    try:
        if method == "initialize":
            info = params.get("clientInfo") or {}
            name = "".join(ch for ch in str(info.get("name", "unknown")) if ch.isprintable())[:64] or "unknown"
            st.clients[ua] = name
            asked = params.get("protocolVersion")
            version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            result = {"protocolVersion": version,
                      "capabilities": {"tools": {"listChanged": False}, "logging": {}, "resources": {},
                                       "prompts": {}},
                      "serverInfo": {"name": "fincept-terminal", "title": "Fincept Lite", "version": VERSION},
                      "instructions": instructions()}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            tools = advertised_tools(user["id"])
            start = int(params.get("cursor") or 0) if str(params.get("cursor") or "0").isdigit() else 0
            page = tools[start: start + 100]
            result = {"tools": page}
            if start + 100 < len(tools):
                result["nextCursor"] = str(start + 100)
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if not isinstance(name, str) or not isinstance(args, dict):
                return rpc_error(mid, -32602, "Invalid params: name (string) and arguments (object) required")
            try:
                if name in META_TOOLS:
                    result = await call_meta(user, client, name, args)
                else:
                    result = await run_tool(user, client, name, args)
            except KeyError:
                return rpc_error(mid, -32602, f"Unknown tool: {name}. Use tool_list to search the catalogue.")
        elif method in {"resources/list"}:
            result = {"resources": []}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": []}
        elif method == "prompts/list":
            result = {"prompts": []}
        elif method == "logging/setLevel":
            result = {}
        elif method.startswith("notifications/"):
            return None
        else:
            return None if is_notification else rpc_error(mid, -32601, f"Method not found: {method}")
    except Exception as e:
        return None if is_notification else rpc_error(mid, -32603, f"Internal error: {e.__class__.__name__}")
    return None if is_notification else rpc_result(mid, result)


@router.get("/mcp")
async def mcp_get():
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp")
async def mcp_post(request: Request):
    blocked = guard(request)
    if blocked:
        return blocked
    user = user_for_token(request.headers.get("authorization"))
    if not user:
        return JSONResponse(status_code=401, content=rpc_error(None, -32001, "Unauthorized: bearer token required"),
                            headers={"WWW-Authenticate": 'Bearer realm="fincept-mcp"'})
    body = await request.body()
    if len(body) > 8 * 1024 * 1024:
        return JSONResponse(status_code=413, content=rpc_error(None, -32600, "Request too large"))
    try:
        doc = json.loads(body)
    except (ValueError, UnicodeDecodeError) as e:
        return JSONResponse(status_code=400, content=rpc_error(None, -32700, f"Parse error: {e}"))
    ua = request.headers.get("user-agent", "")[:120]
    if isinstance(doc, list):
        if not doc:
            return JSONResponse(status_code=400, content=rpc_error(None, -32600, "Invalid Request: empty batch"))
        out = [r for r in await asyncio.gather(*(handle_message(m, user, ua) for m in doc)) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    if not isinstance(doc, dict):
        return JSONResponse(status_code=400, content=rpc_error(None, -32700, "Parse error: expected object or array"))
    res = await handle_message(doc, user, ua)
    return JSONResponse(res) if res is not None else Response(status_code=202)


# ── API REST para la pestaña MCP/Connect de la UI ───────────────────────────

def _snippets(token: str, base_url: str) -> dict:
    url = base_url.rstrip("/") + "/mcp"
    bridge = ROOT.parent / "fincept-qt" / "scripts" / "mcp" / "fincept_mcp_stdio.py"
    py = shutil.which("python3") or sys.executable
    return {
        "url": url,
        "token": token,
        "claude_code": f'claude mcp add --transport http fincept {url} -H "Authorization: Bearer {token}" -s user',
        "codex_toml": f'[mcp_servers.fincept]\nurl = "{url}"\nbearer_token_env_var = "FINCEPT_MCP_TOKEN"',
        "generic_json": json.dumps({"mcpServers": {"fincept": {"type": "http", "url": url,
                                                               "headers": {"Authorization": f"Bearer {token}"}}}},
                                   indent=2),
        "stdio_json": json.dumps({"mcpServers": {"fincept": {"command": py, "args": [str(bridge), "--url", url],
                                                             "env": {"FINCEPT_MCP_TOKEN": token}}}}, indent=2),
        "bridge_script": str(bridge) if Path(bridge).exists() else None,
    }


@router.get("/api/mcp/connect")
async def mcp_connect(request: Request, user: dict = Depends(require_auth)):
    token = ensure_token(user["id"])
    fresh = get_db().one("SELECT mcp_allow_actions FROM users WHERE id=?", (user["id"],))
    st = state(user["id"])
    return {"success": True, "data": {**_snippets(token, str(request.base_url)),
                                      "allow_actions": bool(fresh["mcp_allow_actions"]), "toolset": st.toolset,
                                      "clients": sorted(set(st.clients.values())),
                                      "activity": list(st.activity)[:50],
                                      "tools": [{"name": t.name, "category": t.category, "destructive": t.destructive,
                                                 "needs_approval": t.needs_approval, "description": t.description}
                                                for t in REGISTRY.values()]}}


@router.post("/api/mcp/token/regenerate")
async def mcp_regen(request: Request, user: dict = Depends(require_auth)):
    tok = "fmcp_" + secrets.token_urlsafe(32)
    get_db().execute("UPDATE users SET mcp_token=? WHERE id=?", (tok, user["id"]))
    return {"success": True, "data": _snippets(tok, str(request.base_url))}


class McpSettings(BaseModel):
    allow_actions: bool | None = None
    toolset: str | None = None


@router.put("/api/mcp/settings")
async def mcp_settings(body: McpSettings, user: dict = Depends(require_auth)):
    if body.allow_actions is not None:
        get_db().execute("UPDATE users SET mcp_allow_actions=? WHERE id=?", (int(body.allow_actions), user["id"]))
    if body.toolset in {"essentials", "full"}:
        state(user["id"]).toolset = body.toolset
    fresh = get_db().one("SELECT mcp_allow_actions FROM users WHERE id=?", (user["id"],))
    return {"success": True, "data": {"allow_actions": bool(fresh["mcp_allow_actions"]),
                                      "toolset": state(user["id"]).toolset}}


class ApprovalIn(BaseModel):
    approve: bool


@router.post("/api/mcp/approvals/{aid}")
async def mcp_approve(aid: str, body: ApprovalIn, user: dict = Depends(require_auth)):
    fut = state(user["id"]).approvals.get(aid)
    if not fut or fut.done():
        return {"success": False, "message": "approval not pending"}
    fut.set_result(body.approve)
    return {"success": True, "data": {"id": aid, "approved": body.approve}}
