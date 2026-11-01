"""Catálogo de tools (equivalente a mcp/McpProvider + mcp/tools/*).

En Fincept, *una sola* superficie de tools sirve a tres consumidores: el chat
IA, los agentes y el servidor MCP para agentes externos. Cada tool declara su
JSON Schema, su categoría y si cambia estado (`destructive`). La política
(acciones permitidas, aprobación por llamada) se aplica en quien la invoca.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import analytics, backtest, macro, news, paper
from .datahub import hub, topic_allowed
from .db import get_db
from .market.providers import market, normalize_symbol


@dataclass
class ToolContext:
    user: dict
    source: str = "ui"  # "mcp" | "ai_chat" | "ui"
    client: str = "unknown"


@dataclass
class ToolDef:
    name: str
    description: str
    category: str
    input_schema: dict
    handler: Callable[[ToolContext, dict], Awaitable[Any]]
    destructive: bool = False
    needs_approval: bool = False  # pide confirmación en la UI cuando lo llama un agente externo
    long_running: bool = False

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description, "inputSchema": self.input_schema}


class ToolError(Exception):
    pass


REGISTRY: dict[str, ToolDef] = {}


def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


S = {"type": "string"}
N = {"type": "number"}
I = {"type": "integer"}


def tool(name: str, description: str, category: str, schema: dict, **flags):
    def deco(fn):
        REGISTRY[name] = ToolDef(name, description, category, schema, fn, **flags)
        return fn
    return deco


def _sym(args: dict, key: str = "symbol") -> str:
    try:
        return normalize_symbol(str(args.get(key, "")))
    except ValueError as e:
        raise ToolError(str(e)) from e


# ── Markets ─────────────────────────────────────────────────────────────────

@tool("get_quote", "Live quote for one ticker (price, change, day range, volume). Yahoo-style symbols: AAPL, "
      "^GSPC, EURUSD=X, BTC-USD, GC=F, SAN.MC.", "markets", obj({"symbol": S}, ["symbol"]))
async def _get_quote(ctx, a):
    return await market.quote(_sym(a))


@tool("get_quotes", "Batch live quotes for up to 25 tickers in one call.", "markets",
      obj({"symbols": {"type": "array", "items": S, "maxItems": 25}}, ["symbols"]))
async def _get_quotes(ctx, a):
    syms = [str(s) for s in a.get("symbols", [])][:25]
    if not syms:
        raise ToolError("symbols is empty")
    return list((await market.quotes(syms)).values())


@tool("get_history", "OHLCV price history. period: 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,max; interval: 5m,15m,1h,1d,1wk.",
      "markets", obj({"symbol": S, "period": S, "interval": S}, ["symbol"]))
async def _get_history(ctx, a):
    return await market.history(_sym(a), a.get("period", "6mo"), a.get("interval"))


@tool("lookup_symbol", "Search tickers by company name or symbol.", "markets",
      obj({"query": S, "limit": I}, ["query"]))
async def _lookup(ctx, a):
    q = str(a.get("query", "")).strip()
    if not q:
        raise ToolError("query is empty")
    return await market.search(q, int(a.get("limit", 8)))


@tool("get_technicals", "Technical snapshot: SMA20/50/200, RSI14, distance to 52-week high/low, trend label.",
      "markets", obj({"symbol": S}, ["symbol"]))
async def _technicals(ctx, a):
    h = await market.history(_sym(a), "1y", "1d")
    closes = [c["c"] for c in h["candles"]]
    if len(closes) < 30:
        raise ToolError("not enough history")
    def last_sma(n):
        return sum(closes[-n:]) / n if len(closes) >= n else None
    gains = [max(0, closes[i] - closes[i - 1]) for i in range(len(closes) - 14, len(closes))]
    losses = [max(0, closes[i - 1] - closes[i]) for i in range(len(closes) - 14, len(closes))]
    rs = (sum(gains) / 14) / (sum(losses) / 14) if sum(losses) else math.inf
    rsi = 100 - 100 / (1 + rs) if rs != math.inf else 100.0
    price, s50, s200 = closes[-1], last_sma(50), last_sma(200)
    trend = "uptrend" if s50 and s200 and price > s50 > s200 else "downtrend" if s50 and s200 and price < s50 < s200 else "range"
    return {"symbol": h["symbol"], "price": price, "sma20": last_sma(20), "sma50": s50, "sma200": s200,
            "rsi14": round(rsi, 2), "high_52w": max(closes), "low_52w": min(closes),
            "pct_from_high": (price / max(closes) - 1) * 100, "trend": trend, "source": h["source"]}


# ── News ────────────────────────────────────────────────────────────────────

@tool("get_top_news", "Latest market headlines (aggregated RSS, deduplicated, with sentiment). Optional query filter.",
      "news", obj({"limit": I, "query": S}))
async def _top_news(ctx, a):
    return await news.top_news(int(a.get("limit", 15)), a.get("query"))


@tool("get_equity_news", "Recent headlines for one ticker, with sentiment.", "news",
      obj({"symbol": S, "limit": I}, ["symbol"]))
async def _eq_news(ctx, a):
    return await news.symbol_news(_sym(a), int(a.get("limit", 10)))


# ── Macro (DBnomics) ────────────────────────────────────────────────────────

@tool("search_dbnomics", "Search DBnomics datasets (BLS, FED, ECB, Eurostat, IMF, OECD...).", "macro",
      obj({"query": S, "limit": I}, ["query"]))
async def _dbn_search(ctx, a):
    try:
        return await macro.search(str(a["query"]), int(a.get("limit", 10)))
    except macro.MacroError as e:
        raise ToolError(str(e)) from e


@tool("list_dbnomics_series", "List series inside a DBnomics dataset, optionally filtered by text.", "macro",
      obj({"provider": S, "dataset": S, "query": S, "limit": I}, ["provider", "dataset"]))
async def _dbn_list(ctx, a):
    try:
        return await macro.dataset_series(a["provider"], a["dataset"], a.get("query", ""), int(a.get("limit", 20)))
    except macro.MacroError as e:
        raise ToolError(str(e)) from e


@tool("get_dbnomics_observations", "Observations for a DBnomics series id like FED/H15/RIFSPFF_N.M. Presets: "
      + ", ".join(p["id"] for p in macro.PRESETS), "macro", obj({"series_id": S, "limit": I}, ["series_id"]))
async def _dbn_obs(ctx, a):
    try:
        return await macro.observations(str(a["series_id"]), int(a.get("limit", 60)))
    except macro.MacroError as e:
        raise ToolError(str(e)) from e


# ── Analytics ───────────────────────────────────────────────────────────────

OPT = obj({"spot": N, "strike": N, "days": N, "rate": N, "volatility": N, "option_type": {"enum": ["call", "put"]},
           "dividend_yield": N}, ["spot", "strike", "days", "volatility"])


@tool("bs_option_price", "Option pricing: European call/put fair value and greeks (delta, gamma, vega, theta, "
      "rho) with Black-Scholes. rate/volatility/dividend_yield as decimals (0.05 = 5%).",
      "analytics", OPT)
async def _bs(ctx, a):
    try:
        return analytics.bs_greeks(float(a["spot"]), float(a["strike"]), float(a["days"]) / 365,
                                   float(a.get("rate", 0.04)), float(a["volatility"]), a.get("option_type", "call"),
                                   float(a.get("dividend_yield", 0.0)))
    except ValueError as e:
        raise ToolError(str(e)) from e


@tool("implied_volatility", "Implied volatility from an option's market price (Black-Scholes).", "analytics",
      obj({"price": N, "spot": N, "strike": N, "days": N, "rate": N, "option_type": {"enum": ["call", "put"]}},
          ["price", "spot", "strike", "days"]))
async def _iv(ctx, a):
    try:
        iv = analytics.implied_vol(float(a["price"]), float(a["spot"]), float(a["strike"]), float(a["days"]) / 365,
                                   float(a.get("rate", 0.04)), a.get("option_type", "call"))
    except ValueError as e:
        raise ToolError(str(e)) from e
    return {"implied_volatility": iv}


@tool("compute_risk", "Risk metrics from daily history: annualized return/vol, Sharpe, Sortino, max drawdown, "
      "historical & parametric VaR/CVaR.", "analytics",
      obj({"symbol": S, "period": S, "confidence": N}, ["symbol"]))
async def _risk(ctx, a):
    h = await market.history(_sym(a), a.get("period", "1y"), "1d")
    try:
        m = analytics.risk_metrics([c["c"] for c in h["candles"]], confidence=float(a.get("confidence", 0.95)))
    except ValueError as e:
        raise ToolError(str(e)) from e
    return {"symbol": h["symbol"], "period": h["period"], "source": h["source"], **m}


COSTS = {"commission_bps": N, "slippage_bps": N}


def _costs(a: dict) -> backtest.CostModel:
    try:
        return backtest.CostModel(float(a.get("commission_bps", 5)), float(a.get("slippage_bps", 5)))
    except ValueError as e:
        raise ToolError(str(e)) from e


@tool("run_backtest", "Backtest an SMA crossover (long/flat) on daily data with next-bar-open execution, commission "
      "+ slippage, aligned buy-and-hold benchmark, trade stats and Monte Carlo drawdown/return ranges.", "analytics",
      obj({"symbol": S, "period": S, "fast": I, "slow": I, "initial_cash": N, **COSTS}, ["symbol"]))
async def _bt(ctx, a):
    h = await market.history(_sym(a), a.get("period", "2y"), "1d")
    try:
        r = await asyncio.to_thread(backtest.backtest_sma_cross, h["candles"], int(a.get("fast", 20)),
                                    int(a.get("slow", 50)), float(a.get("initial_cash", 10_000)), _costs(a))
    except ValueError as e:
        raise ToolError(str(e)) from e
    return {"symbol": h["symbol"], "source": h["source"], **r}


@tool("optimize_sma_cross", "Optimize SMA crossover parameters on the first 70% of 5y daily data and report the top "
      "10 on the untouched last 30% (hold-out). Judge by the oos_* columns. Slow: may return a job_id.",
      "analytics", obj({"symbol": S, **COSTS}, ["symbol"]), long_running=True)
async def _opt(ctx, a):
    h = await market.history(_sym(a), "5y", "1d")
    try:
        r = await asyncio.to_thread(backtest.optimize_holdout, h["candles"], 0.3, None, None, _costs(a))
    except ValueError as e:
        raise ToolError(str(e)) from e
    return {"symbol": h["symbol"], "source": h["source"], **r}


@tool("walk_forward_sma", "Walk-forward analysis of the SMA crossover: re-optimize on each past window (default 2y) "
      "and trade the next window (default 6m) out-of-sample; returns stitched OOS equity vs buy-and-hold, per-split "
      "parameters, walk-forward efficiency and parameter stability. Slow: may return a job_id.", "analytics",
      obj({"symbol": S, "period": S, "train_bars": I, "test_bars": I, "anchored": {"type": "boolean"}, **COSTS},
          ["symbol"]), long_running=True)
async def _wf(ctx, a):
    h = await market.history(_sym(a), a.get("period", "10y"), "1d")
    try:
        r = await asyncio.to_thread(backtest.walk_forward_sma, h["candles"], int(a.get("train_bars", 504)),
                                    int(a.get("test_bars", 126)), bool(a.get("anchored", False)), None, None,
                                    10_000.0, _costs(a))
    except ValueError as e:
        raise ToolError(str(e)) from e
    return {"symbol": h["symbol"], "source": h["source"], **r}


# ── Paper trading ───────────────────────────────────────────────────────────

@tool("pt_get_account", "Paper-trading account: cash, equity, P&L and positions.", "portfolio", obj({}))
async def _pt_acc(ctx, a):
    return await paper.account(ctx.user["id"])


@tool("pt_get_orders", "Paper-trading orders (status: open, filled, cancelled, rejected).", "portfolio",
      obj({"status": S, "limit": I}))
async def _pt_orders(ctx, a):
    return paper.list_orders(ctx.user["id"], a.get("status"), int(a.get("limit", 50)))


@tool("pt_place_order", "Place a PAPER order (simulated money). type: market|limit|stop.", "portfolio",
      obj({"symbol": S, "side": {"enum": ["buy", "sell"]}, "qty": N, "type": {"enum": ["market", "limit", "stop"]},
           "limit_price": N, "stop_price": N}, ["symbol", "side", "qty"]),
      destructive=True, needs_approval=True)
async def _pt_place(ctx, a):
    try:
        return await paper.place_order(ctx.user["id"], a["symbol"], a["side"], float(a["qty"]), a.get("type", "market"),
                                       a.get("limit_price"), a.get("stop_price"), source=ctx.source)
    except paper.OrderError as e:
        raise ToolError(str(e)) from e


@tool("pt_cancel_order", "Cancel an open paper order by id.", "portfolio", obj({"order_id": I}, ["order_id"]),
      destructive=True)
async def _pt_cancel(ctx, a):
    try:
        return await paper.cancel_order(ctx.user["id"], int(a["order_id"]))
    except paper.OrderError as e:
        raise ToolError(str(e)) from e


# ── Watchlists ──────────────────────────────────────────────────────────────

@tool("get_watchlists", "The user's watchlists with their symbols.", "portfolio", obj({}))
async def _wl(ctx, a):
    rows = get_db().all("SELECT id, name, symbols FROM watchlists WHERE user_id=? ORDER BY id", (ctx.user["id"],))
    return [{"id": r["id"], "name": r["name"], "symbols": json.loads(r["symbols"])} for r in rows]


@tool("watchlist_add", "Add symbols to a watchlist (created if missing).", "portfolio",
      obj({"name": S, "symbols": {"type": "array", "items": S}}, ["name", "symbols"]), destructive=True)
async def _wl_add(ctx, a):
    from .watchlists import upsert_symbols
    syms = []
    for s in a.get("symbols", []):
        try:
            syms.append(normalize_symbol(str(s)))
        except ValueError as e:
            raise ToolError(str(e)) from e
    row = upsert_symbols(ctx.user["id"], str(a["name"])[:40], syms)
    return {"id": row["id"], "name": row["name"], "symbols": json.loads(row["symbols"])}


# ── DataHub / sistema ───────────────────────────────────────────────────────

@tool("datahub_topics", "Live DataHub topics: subscribers, TTL, age, refresh counters.", "system", obj({}))
async def _dh_topics(ctx, a):
    uid = ctx.user["id"]
    return [t for t in hub.stats() if topic_allowed(t["topic"], uid)]


@tool("datahub_peek", "Last-known value of a DataHub topic (e.g. market:quote:AAPL, news:top).", "system",
      obj({"topic": S}, ["topic"]))
async def _dh_peek(ctx, a):
    t = str(a["topic"])
    if not topic_allowed(t, ctx.user["id"]):
        raise ToolError("topic belongs to another user")
    return {"topic": t, "value": hub.peek(t)}


@tool("get_profile", "Account profile and remaining credits.", "system", obj({}))
async def _profile(ctx, a):
    from .auth import public_profile
    return public_profile(get_db().one("SELECT * FROM users WHERE id=?", (ctx.user["id"],)))


@tool("get_time", "Current server time (UTC) and data mode.", "system", obj({}))
async def _time(ctx, a):
    from .config import settings
    return {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "data_mode": settings.data_mode}


# ── búsqueda BM25 (tool_list del servidor MCP) ──────────────────────────────

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("_", " "))


def search_tools(query: str, limit: int = 10) -> list[ToolDef]:
    docs = {n: _tokens(f"{t.name} {t.name} {t.category} {t.description}") for n, t in REGISTRY.items()}
    q = _tokens(query)
    if not q:
        return list(REGISTRY.values())[:limit]
    n_docs = len(docs)
    avgdl = sum(len(d) for d in docs.values()) / n_docs
    df = Counter(tok for d in docs.values() for tok in set(d))
    k1, b = 1.4, 0.75
    scores = {}
    for name, d in docs.items():
        tf = Counter(d)
        s = 0.0
        for tok in q:
            if tok in tf:
                idf = math.log(1 + (n_docs - df[tok] + 0.5) / (df[tok] + 0.5))
                s += idf * tf[tok] * (k1 + 1) / (tf[tok] + k1 * (1 - b + b * len(d) / avgdl))
        if s > 0:
            scores[name] = s
    return [REGISTRY[n] for n, _ in sorted(scores.items(), key=lambda kv: -kv[1])[:limit]]


def validate_args(t: ToolDef, args: dict) -> None:
    """Validación mínima del JSON Schema (required, tipos básicos, enums, extras)."""
    if not isinstance(args, dict):
        raise ToolError("arguments must be an object")
    props = t.input_schema.get("properties", {})
    for r in t.input_schema.get("required", []):
        if r not in args or args[r] in (None, ""):
            raise ToolError(f"missing required argument: {r}")
    for k, v in args.items():
        if k not in props:
            raise ToolError(f"unknown argument: {k}")
        p = props[k]
        if "enum" in p and v not in p["enum"]:
            raise ToolError(f"{k} must be one of {p['enum']}")
        typ = p.get("type")
        ok = {"string": isinstance(v, str), "number": isinstance(v, (int, float)) and not isinstance(v, bool),
              "integer": isinstance(v, int) and not isinstance(v, bool), "array": isinstance(v, list),
              "object": isinstance(v, dict)}.get(typ, True)
        if not ok:
            raise ToolError(f"{k} must be of type {typ}")


async def call_tool(name: str, args: dict, ctx: ToolContext) -> Any:
    t = REGISTRY.get(name)
    if not t:
        raise ToolError(f"unknown tool: {name}")
    validate_args(t, args or {})
    return await t.handler(ctx, args or {})


__all__ = ["REGISTRY", "ToolDef", "ToolContext", "ToolError", "call_tool", "search_tools"]
