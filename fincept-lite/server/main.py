"""Fincept Lite — punto de entrada.

Un único proceso que junta lo que en Fincept está repartido entre el backend
remoto (api.fincept.in: FastAPI + finceptgo /v1) y el propio terminal
(DataHub, paper trading, servidor MCP local):

    REST   /user/* /v1/* /market/* /news/* /macro/* /quantlib/* /paper/* /research/chat
    WS     /ws                     → DataHub ({"op":"auth"} y luego sub/unsub a tópicos)
    MCP    POST /mcp               → agentes externos (Claude Code, Codex, Cursor…)
    UI     /                        → terminal web estilo Fincept
"""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ai_chat, auth, mcp_server, news, routes, watchlists
from .fund import engine as fund_engine
from .fund import routes as fund_routes
from .auth import InsufficientCredits, insufficient_credits_response, user_from_api_key
from .config import ROOT, VERSION, settings
from .datahub import Subscriber, TopicPolicy, hub, topic_allowed
from .db import get_db
from .market.providers import market
from .paper import matcher

WEB = ROOT / "web"
TOPIC_RE = re.compile(r"^[a-z_]+:[A-Za-z0-9_.:^=\-]{1,100}$")


# ── productores del DataHub ─────────────────────────────────────────────────

class QuoteProducer:
    """market:quote:<SYM> — un refresh agrupa todos los símbolos caducados (batch)."""

    patterns = ["market:quote:*"]

    async def refresh(self, hub_, topics: list[str]) -> None:
        syms = [t.split(":", 2)[2] for t in topics]
        quotes = await market.quotes(syms, max_age=0.5)
        for t, s in zip(topics, syms):
            q = quotes.get(s.upper())
            if q:
                await hub_.publish(t, q)
            else:
                await hub_.publish_error(t, f"no data for {s}")


class NewsProducer:
    patterns = ["news:top"]

    async def refresh(self, hub_, topics: list[str]) -> None:
        await hub_.publish("news:top", await news.top_news(60))


def configure_hub() -> None:
    hub.producers.clear()
    hub.policies.clear()
    hub.listeners.clear()
    live = settings.live
    hub.set_policy_pattern("market:quote:*", TopicPolicy(
        ttl_ms=settings.quote_ttl_live_ms if live else settings.quote_ttl_sim_ms,
        min_interval_ms=15_000 if live else 1_000, refresh_timeout_ms=20_000))
    hub.set_policy_pattern("news:top", TopicPolicy(ttl_ms=180_000, min_interval_ms=60_000))
    hub.set_policy_pattern("paper:*", TopicPolicy(push_only=True, coalesce_within_ms=150))
    hub.set_policy_pattern("mcp:*", TopicPolicy(push_only=True))
    hub.set_policy_pattern("chat:*", TopicPolicy(push_only=True, drop_on_idle=True))
    hub.set_policy_pattern("fund:*", TopicPolicy(push_only=True))
    hub.register_producer(QuoteProducer())
    hub.register_producer(NewsProducer())
    hub.on_publish("market:quote:*", matcher.on_quote)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_db()
    auth.ensure_demo_user()
    configure_hub()
    hub.start()
    await matcher.restore()
    autopilot = asyncio.create_task(fund_engine.autopilot_loop())
    mode = "LIVE (Yahoo/RSS/DBnomics, fallback sim)" if settings.live else "SIM"
    print(f"[fincept-lite] v{VERSION} · datos {mode} · http://{settings.host}:{settings.port}", flush=True)
    yield
    autopilot.cancel()
    await hub.stop()


app = FastAPI(title="Fincept API (Lite replica)", description="Réplica educativa de la API de Fincept Terminal",
              version=VERSION, lifespan=lifespan)


@app.exception_handler(InsufficientCredits)
async def _credits_handler(_req, exc: InsufficientCredits):
    return insufficient_credits_response(exc)


for r in (auth.router, watchlists.router, routes.router, ai_chat.router, mcp_server.router, fund_routes.router):
    app.include_router(r)


@app.get("/health")
async def health():
    return {"ok": True, "status": "healthy", "name": "fincept-terminal", "version": VERSION,
            "data_mode": settings.data_mode, "ai_mode": "claude" if ai_chat.claude_available() else "offline",
            "market_provider": market.yahoo.status() if settings.live else {"provider": "sim", "state": "ok"},
            "time": int(time.time())}


@app.get("/api/info")
async def info():
    return {"name": "Fincept API (Lite replica)", "version": VERSION, "docs": "/docs", "mcp": "/mcp",
            "websocket": "/ws (primer mensaje: {\"op\":\"auth\",\"api_key\":…})"}


# ── WebSocket del DataHub ───────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    # La API key llega en el primer mensaje ({"op":"auth","api_key":…}) y no en la
    # URL, para que no quede en logs de acceso ni en el historial (como hace el
    # terminal, que limpia la query de las URLs antes de loguearlas).
    await websocket.accept()
    try:
        first = await asyncio.wait_for(websocket.receive_json(), timeout=5)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, RuntimeError):
        await websocket.close(code=4401)
        return
    user = user_from_api_key(first.get("api_key") if isinstance(first, dict) and first.get("op") == "auth" else None)
    if not user:
        await websocket.close(code=4401)
        return
    uid = user["id"]
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    async def on_msg(msg: dict) -> None:
        if queue.full():  # backpressure: se descarta lo más viejo
            queue.get_nowait()
        queue.put_nowait(msg)

    sub = Subscriber(on_msg, label=f"ws:{uid}")
    topics: set[str] = set()

    async def writer() -> None:
        while True:
            await websocket.send_json(await queue.get())

    wtask = asyncio.create_task(writer())
    await websocket.send_json({"type": "hello", "user_id": uid, "data_mode": settings.data_mode, "version": VERSION})
    try:
        while True:
            msg = await websocket.receive_json()
            op = msg.get("op") if isinstance(msg, dict) else None
            req = [t for t in (msg.get("topics") or []) if isinstance(t, str)][:200] if op else []
            if op == "sub":
                for t in req:
                    if not TOPIC_RE.match(t) or not topic_allowed(t, uid):
                        await on_msg({"type": "error", "topic": t, "error": "topic not allowed"})
                        continue
                    if t not in topics:
                        topics.add(t)
                        await hub.subscribe(t, sub)
            elif op == "unsub":
                for t in req:
                    topics.discard(t)
                    hub.unsubscribe(t, sub)
            elif op == "ping":
                await on_msg({"type": "pong", "ts": time.time()})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        hub.unsubscribe_all(sub)
        wtask.cancel()


# ── UI ──────────────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(WEB / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run("server.main:app", host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    run()
