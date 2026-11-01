"""AI Chat (F10): réplica de /research/chat + ToolDispatcher del terminal.

En Fincept el chat IA enruta a un proveedor LLM (OpenAI/Anthropic/Gemini/... o
el LLM de Fincept, 5 créditos por respuesta) y le da las mismas tools que el
servidor MCP; un dispatcher ejecuta varias rondas de tool calls.

Aquí:
* Si hay credenciales de Anthropic (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN)
  se usa Claude con un bucle manual de tool use sobre el catálogo de tools.
* Si no, un agente offline determinista detecta la intención (precio,
  noticias, riesgo, backtest, macro...) y llama a las mismas tools.
* Las tools que cambian estado no se exponen al chat: el modelo sugiere el
  comando (p. ej. `BUY 10 AAPL`) y el usuario decide.
* Cada tool call se publica en el DataHub (`chat:<uid>:<session>`) para que la
  UI la muestre en vivo.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from typing import Any

import anthropic
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .auth import InsufficientCredits, charge, insufficient_credits_response, refund, require_auth
from .config import settings
from .datahub import hub
from .db import get_db
from .macro import PRESETS
from .tools import REGISTRY, ToolContext, ToolError, call_tool

router = APIRouter()

CHAT_COST = 5.0  # /research/llm: "Cost: 5 credits per successful response"
MAX_ROUNDS = 8
SESSIONS: dict[tuple[int, str], list[dict]] = {}

SYSTEM = (
    "You are the AI analyst inside Fincept Lite, a Bloomberg-style financial terminal. "
    "Answer in the user's language (usually Spanish). Use the tools for every number you state: never guess "
    "prices, rates or figures. When a tool result has source \"sim\", say the data is simulated. "
    "Keep answers compact and terminal-like: short paragraphs, bullet points, tables in plain text when useful. "
    "You cannot place orders yourself; if the user wants to trade, give them the exact terminal command, e.g. "
    "`BUY 10 AAPL` or `SELL 5 MSFT @ 420` (paper trading). This is research, not investment advice."
)


def claude_available() -> bool:
    if os.environ.get("FINCEPT_AI", "").lower() == "offline":
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def chat_tools() -> list[dict]:
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in REGISTRY.values() if not t.destructive]


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=40)


async def _emit(uid: int, sid: str, event: dict) -> None:
    await hub.publish(f"chat:{uid}:{sid}", {**event, "ts": time.time()})


async def _exec(ctx: ToolContext, sid: str, name: str, args: dict) -> tuple[str, bool, dict]:
    t0 = time.time()
    await _emit(ctx.user["id"], sid, {"event": "tool_start", "tool": name, "args": args})
    try:
        if name not in REGISTRY or REGISTRY[name].destructive:
            raise ToolError(f"tool not available in chat: {name}")
        value = await call_tool(name, args, ctx)
        text, ok = json.dumps(value, ensure_ascii=False, default=str), True
        if len(text) > 30_000:
            text = text[:30_000] + "…(truncated)"
    except ToolError as e:
        text, ok = f"Error: {e}", False
    except Exception as e:
        text, ok = f"Error: {e.__class__.__name__}: {e}", False
    rec = {"tool": name, "args": args, "ok": ok, "ms": int((time.time() - t0) * 1000)}
    await _emit(ctx.user["id"], sid, {"event": "tool_end", **rec})
    return text, ok, rec


# ── modo Claude ─────────────────────────────────────────────────────────────

_client: anthropic.AsyncAnthropic | None = None


def client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


async def run_claude(ctx: ToolContext, sid: str, messages: list[dict]) -> tuple[str, list[dict]]:
    calls: list[dict] = []
    for _ in range(MAX_ROUNDS):
        response = await client().beta.messages.create(
            model=settings.ai_model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # si el modelo declina por política, la API reintenta con el fallback
            thinking={"type": "adaptive"},
            output_config={"effort": settings.ai_effort},
            system=SYSTEM,
            tools=chat_tools(),
            messages=messages,
        )
        # Historial append-only: se guarda el contenido tal cual (incluye bloques de thinking).
        messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "refusal":
            return "El modelo declinó esta petición. Reformúlala o usa las pantallas del terminal.", calls
        if response.stop_reason == "pause_turn":
            continue
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            text = "\n".join(b.text for b in response.content if b.type == "text").strip()
            if response.stop_reason == "max_tokens":
                text += "\n\n_(respuesta cortada por límite de tokens)_"
            return text or "(sin respuesta)", calls
        results = await asyncio.gather(*(_exec(ctx, sid, b.name, b.input if isinstance(b.input, dict) else {})
                                         for b in tool_uses))
        blocks = []
        for b, (text, ok, rec) in zip(tool_uses, results):
            calls.append(rec)
            blocks.append({"type": "tool_result", "tool_use_id": b.id, "content": text, "is_error": not ok})
        messages.append({"role": "user", "content": blocks})  # todos los resultados en un único mensaje
    return "Se alcanzó el máximo de rondas de herramientas; prueba una pregunta más concreta.", calls


# ── modo offline ────────────────────────────────────────────────────────────

ALIASES = {
    "apple": "AAPL", "microsoft": "MSFT", "nvidia": "NVDA", "amazon": "AMZN", "google": "GOOGL",
    "alphabet": "GOOGL", "meta": "META", "facebook": "META", "tesla": "TSLA", "netflix": "NFLX",
    "bitcoin": "BTC-USD", "btc": "BTC-USD", "ethereum": "ETH-USD", "ether": "ETH-USD", "solana": "SOL-USD",
    "oro": "GC=F", "gold": "GC=F", "plata": "SI=F", "silver": "SI=F", "petroleo": "CL=F", "petróleo": "CL=F",
    "oil": "CL=F", "santander": "SAN.MC", "bbva": "BBVA.MC", "inditex": "ITX.MC", "iberdrola": "IBE.MC",
    "telefonica": "TEF.MC", "telefónica": "TEF.MC", "repsol": "REP.MC", "sp500": "^GSPC", "s&p": "^GSPC",
    "nasdaq": "^IXIC", "dow": "^DJI", "ibex": "^IBEX", "dax": "^GDAXI", "nikkei": "^N225", "vix": "^VIX",
    "euro": "EURUSD=X", "eurusd": "EURUSD=X", "yen": "USDJPY=X", "jpmorgan": "JPM",
}
STOP = {"A", "I", "Y", "O", "DE", "EL", "LA", "LOS", "LAS", "UN", "UNA", "QUE", "ES", "EN", "Y", "THE", "AND",
        "OR", "OF", "VS", "AI", "IA", "US", "USA", "EE", "UU", "ETF", "PE", "VAR", "RSI", "SMA", "CEO", "PIB",
        "IPC", "BCE", "FED", "MCP", "API", "OK", "HOY", "ME", "MI", "SU", "AL", "DEL", "POR", "CON", "SIN",
        "PARA", "COMO", "QUÉ", "CUÁL", "BUY", "SELL", "GDP", "CPI", "ECB"}


def extract_symbols(text: str) -> list[str]:
    out: list[str] = []
    low = text.lower()
    for name, sym in ALIASES.items():
        if re.search(rf"(?<![\w&]){re.escape(name)}(?!\w)", low):
            out.append(sym)
    for tok in re.findall(r"(?<![\w$])\^?[A-Z][A-Z0-9]{0,5}(?:[.\-=][A-Z]{1,4})?(?![\w])", text):
        if tok not in STOP and tok not in out:
            out.append(tok)
    return list(dict.fromkeys(out))[:6]


def _fmt_num(x: Any, d: int = 2) -> str:
    try:
        return f"{float(x):,.{d}f}"
    except (TypeError, ValueError):
        return str(x)


def _pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:+.2f}%"
    except (TypeError, ValueError):
        return "n/d"


async def run_offline(ctx: ToolContext, sid: str, text: str) -> tuple[str, list[dict]]:
    low = text.lower()
    syms = extract_symbols(text)
    calls: list[dict] = []

    async def use(name: str, args: dict) -> Any:
        raw, ok, rec = await _exec(ctx, sid, name, args)
        calls.append(rec)
        return json.loads(raw) if ok else None

    def has(*words: str) -> bool:
        return any(w in low for w in words)

    lines: list[str] = []
    if has("noticia", "news", "titular", "headline"):
        items = await use("get_equity_news", {"symbol": syms[0], "limit": 6}) if syms else \
            await use("get_top_news", {"limit": 8})
        lines.append(f"**Noticias{' de ' + syms[0] if syms else ''}**")
        for n in items or []:
            tag = {"positive": "▲", "negative": "▼"}.get(n["sentiment"], "•")
            lines.append(f"{tag} {n['title']} — _{n['source']}_")
    elif has("riesgo", "risk", "var", "volatil", "sharpe", "drawdown") and syms:
        for s in syms[:3]:
            r = await use("compute_risk", {"symbol": s, "period": "1y"})
            if r:
                lines.append(f"**{s}** (1 año, fuente {r['source']}): rentab. {_pct(r['total_return'])} · vol anual "
                             f"{_pct(r['annualized_volatility'])} · Sharpe {_fmt_num(r['sharpe'])} · máx. drawdown "
                             f"{_pct(r['max_drawdown'])} · VaR 95% diario {_pct(r['var_historical'])}")
    elif has("backtest", "estrategia", "strategy", "cruce", "crossover") and syms:
        r = await use("run_backtest", {"symbol": syms[0], "period": "2y", "fast": 20, "slow": 50})
        if r:
            lines.append(f"**Backtest {r['strategy']} en {syms[0]}** (2 años): {_pct(r['total_return'])} vs buy&hold "
                         f"{_pct(r['buy_and_hold_return'])} · {r['trades']} operaciones · Sharpe {_fmt_num(r['sharpe'])}"
                         f" · máx. DD {_pct(r['max_drawdown'])}. Ajusta parámetros en la pestaña BACKTEST (F5).")
    elif has("técnic", "tecnic", "technical", "rsi", "tendencia", "trend", "media móvil", "sma") and syms:
        for s in syms[:3]:
            t = await use("get_technicals", {"symbol": s})
            if t:
                lines.append(f"**{s}** {_fmt_num(t['price'])} · SMA50 {_fmt_num(t['sma50'])} · SMA200 "
                             f"{_fmt_num(t['sma200'])} · RSI14 {t['rsi14']} · {t['trend']} · "
                             f"{t['pct_from_high']:+.1f}% desde máx. 52s")
    elif has("cartera", "portfolio", "posicion", "posición", "cuenta", "account", "p&l", "pnl"):
        a = await use("pt_get_account", {})
        if a:
            lines.append(f"**Cuenta paper**: equity {_fmt_num(a['equity'])} · caja {_fmt_num(a['cash'])} · P&L total "
                         f"{_fmt_num(a['total_pnl'])} ({a['total_pnl_pct']:+.2f}%)")
            for p in a["positions"]:
                lines.append(f"• {p['symbol']}: {p['qty']:g} @ {_fmt_num(p['avg_price'])} → {_fmt_num(p['last'])} "
                             f"({p['unrealized_pct']:+.2f}%)")
            if not a["positions"]:
                lines.append("Sin posiciones. Prueba el comando `BUY 10 AAPL`.")
    elif has("tipo", "rate", "fed", "bce", "ecb", "desempleo", "unemploy", "inflaci", "ipc", "cpi", "pib", "gdp",
             "macro"):
        wanted = []
        for p in PRESETS:
            lab = p["label"].lower()
            if (has("fed") and "fed" in lab) or (has("bce", "ecb") and "bce" in lab) or \
               (has("desempleo", "unemploy") and "desempleo" in lab) or \
               (has("inflaci", "ipc", "cpi") and ("ipc" in lab or "ipca" in lab)) or (has("pib", "gdp") and "pib" in lab):
                wanted.append(p)
        for p in wanted or PRESETS[:4]:
            o = await use("get_dbnomics_observations", {"series_id": p["id"], "limit": 3})
            if o:
                lines.append(f"• **{p['label']}**: {o['last_value']} {p['unit']} ({o['last_period']}, DBnomics)")
            else:
                lines.append(f"• {p['label']}: no disponible ahora mismo")
    elif syms:
        qs = await use("get_quotes", {"symbols": syms})
        for q in qs or []:
            arrow = "▲" if q["change"] >= 0 else "▼"
            lines.append(f"**{q['symbol']}** {q['name']}: {_fmt_num(q['price'])} {q['currency']} {arrow} "
                         f"{q['change_pct']:+.2f}% (máx {_fmt_num(q['high'])} / mín {_fmt_num(q['low'])}, "
                         f"fuente {q['source']})")
    if not lines:
        lines = ["Modo offline: entiendo preguntas sobre **precios** (\"¿cómo va NVDA y AAPL?\"), **noticias**, "
                 "**riesgo/VaR**, **técnico/RSI**, **backtest**, **cartera** y **macro** (Fed, BCE, desempleo, IPC).",
                 "Para respuestas libres con un LLM, arranca el servidor con `ANTHROPIC_API_KEY`."]
    return "\n".join(lines), calls


# ── ruta ────────────────────────────────────────────────────────────────────

@router.post("/research/chat")
async def chat(body: ChatIn, user: dict = Depends(require_auth)):
    sid = body.session_id or uuid.uuid4().hex[:12]
    mode = "claude" if claude_available() else "offline"
    cost = CHAT_COST if mode == "claude" else 0.0
    try:
        charge(user, "/research/chat", cost)
    except InsufficientCredits as e:
        return insufficient_credits_response(e)
    ctx = ToolContext(user=user, source="ai_chat", client="ai_chat")
    db = get_db()
    db.execute("INSERT INTO chat_messages(user_id, session_id, role, text, at) VALUES (?,?,?,?,?)",
               (user["id"], sid, "user", body.message, time.time()))
    history = SESSIONS.setdefault((user["id"], sid), [])
    mark = len(history)
    try:
        try:
            if mode == "claude":
                history.append({"role": "user", "content": body.message})
                reply, calls = await run_claude(ctx, sid, history)
            else:
                reply, calls = await run_offline(ctx, sid, body.message)
        except anthropic.APIError:
            # Volver al último prefijo válido: nunca dejar un tool_use sin su tool_result.
            del history[mark:]
            raise
    except anthropic.AuthenticationError:
        refund(user, "/research/chat", cost)
        reply, calls = await run_offline(ctx, sid, body.message)
        reply = "_(credenciales de Anthropic inválidas → modo offline)_\n" + reply
        mode = "offline"
    except anthropic.RateLimitError:
        refund(user, "/research/chat", cost)
        return {"success": False, "message": "El proveedor LLM está limitando peticiones; reintenta en unos segundos."}
    except anthropic.APIStatusError as e:
        refund(user, "/research/chat", cost)
        return {"success": False, "message": f"Error del proveedor LLM (HTTP {e.status_code})."}
    except anthropic.APIConnectionError:
        refund(user, "/research/chat", cost)
        return {"success": False, "message": "No se pudo conectar con el proveedor LLM."}
    db.execute("INSERT INTO chat_messages(user_id, session_id, role, text, at) VALUES (?,?,?,?,?)",
               (user["id"], sid, "assistant", reply, time.time()))
    return {"success": True, "data": {"session_id": sid, "reply": reply, "tool_calls": calls, "mode": mode,
                                      "credits_charged": cost}}


@router.get("/chat/sessions")
async def chat_sessions(user: dict = Depends(require_auth)):
    rows = get_db().all(
        "SELECT session_id, MIN(at) AS started, MAX(at) AS last, COUNT(*) AS messages,"
        " (SELECT text FROM chat_messages c2 WHERE c2.session_id=c.session_id AND c2.role='user' ORDER BY id LIMIT 1)"
        " AS title FROM chat_messages c WHERE user_id=? GROUP BY session_id ORDER BY last DESC LIMIT 30",
        (user["id"],),
    )
    return {"success": True, "data": rows}


@router.get("/chat/sessions/{sid}")
async def chat_session(sid: str, user: dict = Depends(require_auth)):
    rows = get_db().all("SELECT role, text, at FROM chat_messages WHERE user_id=? AND session_id=? ORDER BY id",
                        (user["id"], sid))
    return {"success": True, "data": {"session_id": sid, "messages": rows}}
