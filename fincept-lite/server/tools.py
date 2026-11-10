"""Catálogo de tools (equivalente a mcp/McpProvider + mcp/tools/*).

En Fincept, *una sola* superficie de tools sirve a tres consumidores: el chat
IA, los agentes y el servidor MCP para agentes externos. Cada tool declara su
JSON Schema, su categoría y si cambia estado (`destructive`). La política
(acciones permitidas, aprobación por llamada) se aplica en quien la invoca.

Diseño según la guía de la skill mcp-builder:
* Cada parámetro lleva descripción, ejemplos y límites (min/max/longitud).
* Anotaciones MCP completas: title, readOnlyHint, destructiveHint,
  idempotentHint, openWorldHint.
* Listas paginadas con {total, count, offset, has_more, next_offset, items}.
* Errores accionables: dicen qué hacer a continuación (qué tool llamar).
* Los nombres NO llevan prefijo de servicio a propósito: son los del servidor
  MCP real de Fincept (EssentialTools.cpp); los clientes ya los namespacean
  (Claude Code los expone como mcp__fincept__get_quote).
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
from .market.providers import PERIODS, market, normalize_symbol


@dataclass
class ToolContext:
    user: dict
    source: str = "ui"  # "mcp" | "ai_chat" | "ui"
    client: str = "unknown"


@dataclass
class ToolDef:
    name: str
    title: str
    description: str
    category: str
    input_schema: dict
    handler: Callable[[ToolContext, dict], Awaitable[Any]]
    destructive: bool = False  # cambia estado → política "allow actions"
    needs_approval: bool = False  # además pide confirmación en la UI a cada agente externo
    long_running: bool = False
    idempotent: bool = True  # repetir la llamada no tiene efecto adicional
    open_world: bool = False  # habla con servicios externos (Yahoo, RSS, DBnomics)
    destructive_hint: bool | None = None  # por defecto = destructive

    def annotations(self) -> dict:
        destructive = self.destructive if self.destructive_hint is None else self.destructive_hint
        return {"title": self.title, "readOnlyHint": not self.destructive, "destructiveHint": destructive,
                "idempotentHint": self.idempotent, "openWorldHint": self.open_world}

    def schema(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description,
                "inputSchema": self.input_schema, "annotations": self.annotations()}


class ToolError(Exception):
    pass


REGISTRY: dict[str, ToolDef] = {}


# ── helpers de esquema ──────────────────────────────────────────────────────

def obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [], "additionalProperties": False}


def p_str(desc: str, **kw) -> dict:
    return {"type": "string", "description": desc, **kw}


def p_num(desc: str, **kw) -> dict:
    return {"type": "number", "description": desc, **kw}


def p_int(desc: str, **kw) -> dict:
    return {"type": "integer", "description": desc, **kw}


def p_enum(desc: str, values: list, default=None) -> dict:
    out = {"type": "string", "enum": values, "description": desc}
    if default is not None:
        out["default"] = default
    return out


SYMBOL = p_str("Ticker in Yahoo Finance format, e.g. 'AAPL', 'SAN.MC' (Madrid), 'VOD.L' (London), '^GSPC' "
               "(index), 'EURUSD=X' (FX), 'GC=F' (futures), 'BTC-USD' (crypto). Unsure? call lookup_symbol first.",
               minLength=1, maxLength=24)
PERIOD = p_enum("History window.", sorted(PERIODS, key=["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y",
                                                        "max"].index))


def LIMIT(default: int, maximum: int) -> dict:
    return p_int(f"Max items to return (default {default}).", minimum=1, maximum=maximum, default=default)


OFFSET = p_int("Items to skip, for pagination: pass the previous response's next_offset.", minimum=0, default=0)
COSTS = {"commission_bps": p_num("Commission per side in basis points (5 = 0.05%).", minimum=0, maximum=500, default=5),
         "slippage_bps": p_num("Adverse slippage per side in basis points.", minimum=0, maximum=500, default=5)}


def tool(name: str, title: str, description: str, category: str, schema: dict, **flags):
    def deco(fn):
        REGISTRY[name] = ToolDef(name, title, description, category, schema, fn, **flags)
        return fn
    return deco


def paginate(items: list, offset: int, limit: int) -> dict:
    page = items[offset: offset + limit]
    more = offset + len(page) < len(items)
    return {"total": len(items), "count": len(page), "offset": offset, "has_more": more,
            "next_offset": offset + len(page) if more else None, "items": page}


def _sym(args: dict, key: str = "symbol") -> str:
    raw = str(args.get(key, ""))
    try:
        return normalize_symbol(raw)
    except ValueError as e:
        raise ToolError(f"Invalid symbol {raw!r}. Use Yahoo Finance format (AAPL, SAN.MC, ^GSPC, EURUSD=X, BTC-USD) "
                        "or call lookup_symbol(query='company name') to find it.") from e


def _macro_error(e: Exception) -> ToolError:
    return ToolError(f"{e}. Check the id with search_dbnomics(query=...) and list_dbnomics_series(provider, dataset).")


# ── Markets ─────────────────────────────────────────────────────────────────

@tool("get_quote", "Get quote", "Live quote for one ticker: price, change, day range, volume, currency and data "
      "source ('yahoo' or 'sim' when simulated). For several tickers use get_quotes.", "markets",
      obj({"symbol": SYMBOL}, ["symbol"]), open_world=True)
async def _get_quote(ctx, a):
    return await market.quote(_sym(a))


@tool("get_quotes", "Get quotes (batch)", "Live quotes for up to 25 tickers in one call (same fields as get_quote).",
      "markets", obj({"symbols": {"type": "array", "items": SYMBOL, "minItems": 1, "maxItems": 25,
                                  "description": "Tickers, e.g. ['AAPL', 'MSFT', '^IBEX']."}}, ["symbols"]),
      open_world=True)
async def _get_quotes(ctx, a):
    syms = [str(s) for s in a["symbols"]]
    for s in syms:
        _sym({"symbol": s})
    return list((await market.quotes(syms)).values())


@tool("get_history", "Get price history", "OHLCV candles {t (unix seconds), o, h, l, c, v} for a ticker. Large "
      "windows can be truncated: page the rest with result_fetch.", "markets",
      obj({"symbol": SYMBOL, "period": {**PERIOD, "default": "6mo"},
           "interval": p_enum("Candle size; defaults to a sensible one for the period.",
                              ["5m", "15m", "1h", "1d", "1wk", "1mo"])}, ["symbol"]), open_world=True)
async def _get_history(ctx, a):
    return await market.history(_sym(a), a.get("period", "6mo"), a.get("interval"))


@tool("lookup_symbol", "Search tickers", "Find tickers by company name or symbol, e.g. query='santander' → SAN.MC. "
      "Returns symbol, name, exchange and type.", "markets",
      obj({"query": p_str("Company name or partial symbol.", minLength=1, maxLength=60), "limit": LIMIT(8, 25)},
          ["query"]), open_world=True)
async def _lookup(ctx, a):
    q = str(a["query"]).strip()
    if not q:
        raise ToolError("query is empty: pass a company name like 'apple' or a partial ticker like 'AAP'.")
    return await market.search(q, int(a.get("limit", 8)))


@tool("get_technicals", "Get technical snapshot", "Technical snapshot from 1y of daily data: SMA20/50/200, RSI14, "
      "52-week high/low, distance from the high and a trend label (uptrend/downtrend/range).", "markets",
      obj({"symbol": SYMBOL}, ["symbol"]), open_world=True)
async def _technicals(ctx, a):
    h = await market.history(_sym(a), "1y", "1d")
    closes = [c["c"] for c in h["candles"]]
    if len(closes) < 30:
        raise ToolError(f"Only {len(closes)} daily candles for {h['symbol']}: need 30+. Is it a new listing?")

    def last_sma(n):
        return sum(closes[-n:]) / n if len(closes) >= n else None
    gains = [max(0, closes[i] - closes[i - 1]) for i in range(len(closes) - 14, len(closes))]
    losses = [max(0, closes[i - 1] - closes[i]) for i in range(len(closes) - 14, len(closes))]
    rs = (sum(gains) / 14) / (sum(losses) / 14) if sum(losses) else math.inf
    rsi = 100 - 100 / (1 + rs) if rs != math.inf else 100.0
    price, s50, s200 = closes[-1], last_sma(50), last_sma(200)
    trend = ("uptrend" if s50 and s200 and price > s50 > s200
             else "downtrend" if s50 and s200 and price < s50 < s200 else "range")
    return {"symbol": h["symbol"], "price": price, "sma20": last_sma(20), "sma50": s50, "sma200": s200,
            "rsi14": round(rsi, 2), "high_52w": max(closes), "low_52w": min(closes),
            "pct_from_high": (price / max(closes) - 1) * 100, "trend": trend, "source": h["source"]}


# ── News ────────────────────────────────────────────────────────────────────

@tool("get_top_news", "Get top market news", "Latest market headlines (aggregated RSS, deduplicated) with a "
      "sentiment label, newest first. Paginated; optional text filter.", "news",
      obj({"query": p_str("Only headlines containing this text, e.g. 'fed' or 'oil'.", maxLength=60),
           "limit": LIMIT(15, 50), "offset": OFFSET}), open_world=True, idempotent=False)
async def _top_news(ctx, a):
    items = await news.top_news(200, a.get("query"))
    return paginate(items, int(a.get("offset", 0)), int(a.get("limit", 15)))


@tool("get_equity_news", "Get news for a ticker", "Recent headlines for one ticker with sentiment, newest first. "
      "Paginated.", "news", obj({"symbol": SYMBOL, "limit": LIMIT(10, 50), "offset": OFFSET}, ["symbol"]),
      open_world=True, idempotent=False)
async def _eq_news(ctx, a):
    items = await news.symbol_news(_sym(a), 50)
    return paginate(items, int(a.get("offset", 0)), int(a.get("limit", 10)))


# ── Macro (DBnomics) ────────────────────────────────────────────────────────

@tool("search_dbnomics", "Search macro datasets", "Search DBnomics datasets across BLS, FED, ECB, Eurostat, IMF, "
      "OECD, BEA... Returns provider + dataset codes to use with list_dbnomics_series.", "macro",
      obj({"query": p_str("Topic, e.g. 'unemployment', 'inflation euro area'.", minLength=2, maxLength=80),
           "limit": LIMIT(10, 50)}, ["query"]), open_world=True)
async def _dbn_search(ctx, a):
    try:
        return await macro.search(str(a["query"]), int(a.get("limit", 10)))
    except macro.MacroError as e:
        raise _macro_error(e) from e


@tool("list_dbnomics_series", "List series in a dataset", "List series inside one DBnomics dataset, optionally "
      "filtered by text. Returns full series ids for get_dbnomics_observations.", "macro",
      obj({"provider": p_str("Provider code, e.g. 'BLS', 'ECB', 'Eurostat'.", maxLength=40),
           "dataset": p_str("Dataset code, e.g. 'ln', 'FM', 'prc_hicp_manr'.", maxLength=80),
           "query": p_str("Optional text filter.", maxLength=80), "limit": LIMIT(20, 50)}, ["provider", "dataset"]),
      open_world=True)
async def _dbn_list(ctx, a):
    try:
        return await macro.dataset_series(a["provider"], a["dataset"], a.get("query", ""), int(a.get("limit", 20)))
    except macro.MacroError as e:
        raise _macro_error(e) from e


@tool("get_dbnomics_observations", "Get macro series observations", "Observations {period, value} of a DBnomics "
      "series plus last_period/last_value. Narrow with start/end (e.g. start='2020-01', end='2020-12') instead of "
      "pulling long histories; within the window the most recent `limit` points are returned. Well-known ids: "
      + "; ".join(f"{p['id']} = {p['label']}" for p in macro.PRESETS) + ".", "macro",
      obj({"series_id": p_str("PROVIDER/DATASET/SERIES, e.g. 'FED/H15/RIFSPFF_N.M'.", maxLength=120),
           "start": p_str("First period to include, prefix match: '2019', '2019-07', '2022-09-01', '2020-Q1'.",
                          maxLength=10),
           "end": p_str("Last period to include, same format as start.", maxLength=10),
           "limit": p_int("Max observations to return (most recent within the window; default 60).", minimum=1,
                          maximum=2000, default=60)},
          ["series_id"]), open_world=True)
async def _dbn_obs(ctx, a):
    try:
        return await macro.observations(str(a["series_id"]), int(a.get("limit", 60)), a.get("start"), a.get("end"))
    except macro.MacroError as e:
        raise _macro_error(e) from e


# ── Analytics ───────────────────────────────────────────────────────────────

OPTION_TYPE = p_enum("Option type.", ["call", "put"], "call")
OPT = obj({"spot": p_num("Underlying price.", exclusiveMinimum=0), "strike": p_num("Strike price.", exclusiveMinimum=0),
           "days": p_num("Calendar days to expiry (365 = 1 year).", exclusiveMinimum=0, maximum=36500),
           "rate": p_num("Risk-free rate as a decimal (0.04 = 4%).", minimum=-0.1, maximum=1, default=0.04),
           "volatility": p_num("Annual volatility as a decimal (0.25 = 25%).", exclusiveMinimum=0, maximum=10),
           "option_type": OPTION_TYPE,
           "dividend_yield": p_num("Continuous dividend yield as a decimal.", minimum=0, maximum=1, default=0)},
          ["spot", "strike", "days", "volatility"])


@tool("bs_option_price", "Price an option (Black-Scholes)", "Option pricing: European call/put fair value and "
      "greeks (delta, gamma, vega per 1 vol point, theta per day, rho per 1 rate point) with Black-Scholes.",
      "analytics", OPT)
async def _bs(ctx, a):
    try:
        return analytics.bs_greeks(float(a["spot"]), float(a["strike"]), float(a["days"]) / 365,
                                   float(a.get("rate", 0.04)), float(a["volatility"]), a.get("option_type", "call"),
                                   float(a.get("dividend_yield", 0.0)))
    except ValueError as e:
        raise ToolError(str(e)) from e


@tool("implied_volatility", "Solve implied volatility", "Implied volatility (decimal) that makes Black-Scholes "
      "match an option's market price.", "analytics",
      obj({"price": p_num("Option market price (premium).", exclusiveMinimum=0), "spot": OPT["properties"]["spot"],
           "strike": OPT["properties"]["strike"], "days": OPT["properties"]["days"],
           "rate": OPT["properties"]["rate"], "option_type": OPTION_TYPE}, ["price", "spot", "strike", "days"]))
async def _iv(ctx, a):
    try:
        iv = analytics.implied_vol(float(a["price"]), float(a["spot"]), float(a["strike"]), float(a["days"]) / 365,
                                   float(a.get("rate", 0.04)), a.get("option_type", "call"))
    except ValueError as e:
        raise ToolError(f"{e}: the premium must be at least the discounted intrinsic value.") from e
    return {"implied_volatility": iv}


@tool("compute_risk", "Compute risk metrics", "Risk metrics from daily closes: total and annualized return, "
      "annualized volatility, Sharpe, Sortino, max drawdown, historical and parametric VaR/CVaR (daily).",
      "analytics", obj({"symbol": SYMBOL, "period": {**PERIOD, "default": "1y"},
                        "confidence": p_num("VaR confidence level.", minimum=0.8, maximum=0.999, default=0.95)},
                       ["symbol"]), open_world=True)
async def _risk(ctx, a):
    h = await market.history(_sym(a), a.get("period", "1y"), "1d")
    try:
        m = analytics.risk_metrics([c["c"] for c in h["candles"]], confidence=float(a.get("confidence", 0.95)))
    except ValueError as e:
        raise ToolError(f"{e}. Use a longer period, e.g. period='2y'.") from e
    return {"symbol": h["symbol"], "period": h["period"], "source": h["source"], **m}


def _costs(a: dict) -> backtest.CostModel:
    try:
        return backtest.CostModel(float(a.get("commission_bps", 5)), float(a.get("slippage_bps", 5)))
    except ValueError as e:
        raise ToolError(str(e)) from e


@tool("run_backtest", "Backtest SMA crossover", "Backtest an SMA crossover (long/flat) on daily data with "
      "next-bar-open execution, commission + slippage, aligned buy-and-hold benchmark, trade stats and Monte Carlo "
      "return/drawdown ranges. In-sample only: validate with walk_forward_sma before trusting parameters.",
      "analytics", obj({"symbol": SYMBOL, "period": {**PERIOD, "default": "2y"},
                        "fast": p_int("Fast SMA length.", minimum=2, maximum=200, default=20),
                        "slow": p_int("Slow SMA length (> fast).", minimum=3, maximum=400, default=50),
                        "initial_cash": p_num("Starting capital.", exclusiveMinimum=0, default=10000), **COSTS},
                       ["symbol"]), open_world=True)
async def _bt(ctx, a):
    h = await market.history(_sym(a), a.get("period", "2y"), "1d")
    try:
        r = await asyncio.to_thread(backtest.backtest_sma_cross, h["candles"], int(a.get("fast", 20)),
                                    int(a.get("slow", 50)), float(a.get("initial_cash", 10_000)), _costs(a))
    except ValueError as e:
        raise ToolError(f"{e}. Try a longer period or shorter SMAs.") from e
    return {"symbol": h["symbol"], "source": h["source"], **r}


@tool("optimize_sma_cross", "Optimize SMA (hold-out)", "Optimize SMA crossover parameters on the first 70% of 5y "
      "daily data and report the top 10 on the untouched last 30% (hold-out). Judge by the oos_* columns. Slow: "
      "may return a job_id.", "analytics", obj({"symbol": SYMBOL, **COSTS}, ["symbol"]), long_running=True,
      open_world=True)
async def _opt(ctx, a):
    h = await market.history(_sym(a), "5y", "1d")
    try:
        r = await asyncio.to_thread(backtest.optimize_holdout, h["candles"], 0.3, None, None, _costs(a))
    except ValueError as e:
        raise ToolError(f"{e}. The ticker needs ~5 years of daily history.") from e
    return {"symbol": h["symbol"], "source": h["source"], **r}


@tool("walk_forward_sma", "Walk-forward SMA analysis", "Walk-forward analysis of the SMA crossover: re-optimize on "
      "each past window (default 504 bars ≈ 2y) and trade the next window (default 126 bars ≈ 6m) out-of-sample. "
      "Returns stitched OOS equity vs buy-and-hold, per-split parameters, walk-forward efficiency (OOS/IS Sharpe; "
      "< 0.5 suggests overfitting) and parameter stability. Slow: may return a job_id.", "analytics",
      obj({"symbol": SYMBOL, "period": {**PERIOD, "default": "10y"},
           "train_bars": p_int("Training window in daily bars.", minimum=240, maximum=2520, default=504),
           "test_bars": p_int("Out-of-sample window in daily bars.", minimum=20, maximum=1260, default=126),
           "anchored": {"type": "boolean", "default": False,
                        "description": "True = training always starts at the first bar (expanding window)."},
           **COSTS}, ["symbol"]), long_running=True, open_world=True)
async def _wf(ctx, a):
    h = await market.history(_sym(a), a.get("period", "10y"), "1d")
    try:
        r = await asyncio.to_thread(backtest.walk_forward_sma, h["candles"], int(a.get("train_bars", 504)),
                                    int(a.get("test_bars", 126)), bool(a.get("anchored", False)), None, None,
                                    10_000.0, _costs(a))
    except ValueError as e:
        raise ToolError(f"{e}. Use period='10y' or smaller train_bars/test_bars.") from e
    return {"symbol": h["symbol"], "source": h["source"], **r}


# ── Paper trading ───────────────────────────────────────────────────────────

@tool("pt_get_account", "Get paper account", "Paper-trading account (simulated money): cash, equity, realized and "
      "unrealized P&L and open positions with live prices.", "portfolio", obj({}), open_world=True)
async def _pt_acc(ctx, a):
    return await paper.account(ctx.user["id"])


@tool("pt_get_orders", "List paper orders", "Paper-trading orders, newest first. Paginated.", "portfolio",
      obj({"status": p_enum("Only orders in this state.", ["open", "filled", "cancelled", "rejected"]),
           "limit": LIMIT(20, 100), "offset": OFFSET}))
async def _pt_orders(ctx, a):
    rows = paper.list_orders(ctx.user["id"], a.get("status"), 1000)
    return paginate(rows, int(a.get("offset", 0)), int(a.get("limit", 20)))


@tool("pt_place_order", "Place paper order", "Place a PAPER order (simulated money, no real broker). market fills "
      "now at the live price; limit/stop wait until price crosses. No short selling. Needs 'allow actions' and the "
      "user's approval in the terminal for every call.", "portfolio",
      obj({"symbol": SYMBOL, "side": p_enum("Order side.", ["buy", "sell"]),
           "qty": p_num("Quantity (shares/units).", exclusiveMinimum=0, maximum=1e7),
           "type": p_enum("Order type.", ["market", "limit", "stop"], "market"),
           "limit_price": p_num("Required for type=limit.", exclusiveMinimum=0),
           "stop_price": p_num("Required for type=stop.", exclusiveMinimum=0)}, ["symbol", "side", "qty"]),
      destructive=True, needs_approval=True, idempotent=False, open_world=True)
async def _pt_place(ctx, a):
    try:
        order = await paper.place_order(ctx.user["id"], a["symbol"], a["side"], float(a["qty"]),
                                        a.get("type", "market"), a.get("limit_price"), a.get("stop_price"),
                                        source=ctx.source)
    except paper.OrderError as e:
        raise ToolError(f"{e}. Check the arguments with tool_describe(name='pt_place_order').") from e
    if order["status"] == "rejected":
        hint = "Check cash and positions with pt_get_account, then retry with a smaller qty."
        raise ToolError(f"Order rejected: {order['note']}. {hint}")
    return order


@tool("pt_cancel_order", "Cancel paper order", "Cancel an open paper order by id (see pt_get_orders status='open').",
      "portfolio", obj({"order_id": p_int("Order id.", minimum=1)}, ["order_id"]), destructive=True)
async def _pt_cancel(ctx, a):
    try:
        return await paper.cancel_order(ctx.user["id"], int(a["order_id"]))
    except paper.OrderError as e:
        raise ToolError(f"{e}. List open orders with pt_get_orders(status='open').") from e


# ── Watchlists ──────────────────────────────────────────────────────────────

@tool("get_watchlists", "Get watchlists", "The user's watchlists with their symbols.", "portfolio", obj({}))
async def _wl(ctx, a):
    rows = get_db().all("SELECT id, name, symbols FROM watchlists WHERE user_id=? ORDER BY id", (ctx.user["id"],))
    return [{"id": r["id"], "name": r["name"], "symbols": json.loads(r["symbols"])} for r in rows]


@tool("watchlist_add", "Add to watchlist", "Add symbols to a watchlist; creates it if missing, ignores duplicates.",
      "portfolio", obj({"name": p_str("Watchlist name, e.g. 'Bancos'.", minLength=1, maxLength=40),
                        "symbols": {"type": "array", "items": SYMBOL, "minItems": 1, "maxItems": 50,
                                    "description": "Tickers to add."}}, ["name", "symbols"]),
      destructive=True, destructive_hint=False)
async def _wl_add(ctx, a):
    from .watchlists import upsert_symbols
    syms = [_sym({"symbol": s}) for s in a["symbols"]]
    row = upsert_symbols(ctx.user["id"], str(a["name"])[:40], syms)
    return {"id": row["id"], "name": row["name"], "symbols": json.loads(row["symbols"])}


# ── Laboratorio quant (librería quantfin de quant-finance-research) ─────────

def _qf():
    import numpy as np

    from quantfin import avanzados as qa
    from quantfin import mercados as qm
    return np, qa, qm


async def _daily_closes(symbol: str, period: str = "1y") -> tuple[str, list[dict], str]:
    h = await market.history(_sym({"symbol": symbol}), period, "1d")
    if len(h["candles"]) < 60:
        raise ToolError(f"Only {len(h['candles'])} daily candles for {h['symbol']}: need 60+.")
    return h["symbol"], h["candles"], h["source"]


@tool("qf_bubble_test", "Bubble test (SADF)", "Phillips-Shi-Yu (2015) SADF test on 1y of log prices: detects an "
      "explosive regime while it happens (it does not predict when it bursts). Statistic > ~1.5 suggests a bubble "
      "(critical value depends on sample size).", "quant", obj({"symbol": SYMBOL, "period": {**PERIOD, "default": "1y"}},
                                                               ["symbol"]), open_world=True)
async def _qf_bubble(ctx, a):
    np, qa, _ = _qf()
    sym, candles, src = await _daily_closes(a["symbol"], a.get("period", "1y"))
    stat = float(await asyncio.to_thread(qa.sadf, np.log(np.array([c["c"] for c in candles], dtype=float))))
    return {"symbol": sym, "sadf": stat, "explosive": stat > 1.5, "threshold": 1.5, "observations": len(candles),
            "source": src, "reference": "Phillips, Shi y Yu (2015), International Economic Review"}


@tool("qf_systemic_fragility", "Systemic fragility (absorption ratio)", "Kritzman et al. (2011) absorption ratio "
      "of the fund's global multi-asset universe over the last year: share of variance absorbed by the top 20% "
      "principal components, with a z-score versus its own history (z >= 1 = fragile, correlated market).", "quant",
      obj({}), open_world=True, idempotent=False)
async def _qf_fragility(ctx, a):
    np, _, _ = _qf()
    from .fund import agents as FA
    from .fund.engine import _histories, aligned_returns
    rets = aligned_returns(await _histories())
    if not rets or len({len(r) for r in rets.values()}) != 1:
        raise ToolError("Not enough aligned history across the universe right now; retry later.")
    out = await asyncio.to_thread(FA.systemic_fragility, np.array(list(rets.values())).T)
    if not out:
        raise ToolError("Not enough history to compute the absorption ratio.")
    return {**out, "assets": len(rets), "reference": "Kritzman, Li, Page y Rigobon (2011), JPM"}


@tool("qf_pairs_ou", "Pairs trading (Ornstein-Uhlenbeck)", "Fit an Ornstein-Uhlenbeck process to the log-price "
      "spread of two tickers (hedge ratio by OLS) and return mean-reversion speed, half-life, current z-score and the "
      "signal (+1 long spread, -1 short spread, 0 flat) at |z| > entry.", "quant",
      obj({"symbol_a": SYMBOL, "symbol_b": SYMBOL, "period": {**PERIOD, "default": "2y"},
           "entry_z": p_num("Z-score threshold to enter.", minimum=0.5, maximum=5, default=2.0)},
          ["symbol_a", "symbol_b"]), open_world=True)
async def _qf_pairs(ctx, a):
    np, qa, _ = _qf()
    (sa, ca, src), (sb, cb, _) = await asyncio.gather(_daily_closes(a["symbol_a"], a.get("period", "2y")),
                                                      _daily_closes(a["symbol_b"], a.get("period", "2y")))
    da, db = {c["t"] // 86400: c["c"] for c in ca}, {c["t"] // 86400: c["c"] for c in cb}
    days = sorted(set(da) & set(db))
    if len(days) < 120:
        raise ToolError(f"Only {len(days)} common days between {sa} and {sb}: need 120+.")
    la, lb = np.log([da[d] for d in days]), np.log([db[d] for d in days])
    beta, alpha = np.polyfit(lb, la, 1)
    spread = la - (alpha + beta * lb)
    theta, mu, sigma, half_life = qa.ajustar_ou(spread)
    if not np.isfinite(theta) or theta <= 0:
        return {"pair": [sa, sb], "mean_reverting": False, "hedge_ratio": float(beta), "source": src,
                "note": "The spread does not mean-revert (b >= 1 in the AR(1) fit): no pairs signal."}
    z, signal = qa.zscore_pairs(spread, mu, sigma, theta, float(a.get("entry_z", 2.0)))
    return {"pair": [sa, sb], "mean_reverting": True, "hedge_ratio": float(beta), "theta": float(theta),
            "half_life_days": float(half_life * 252), "z_score": float(z[-1]), "signal": int(signal[-1]),
            "observations": len(days), "source": src, "reference": "Uhlenbeck y Ornstein (1930); quantfin.ajustar_ou"}


@tool("qf_risk_parity", "Risk parity weights", "Equal-risk-contribution weights (Maillard et al. 2010) from the "
      "last year of daily returns of 2-20 tickers, with each asset's annual volatility and risk contribution.",
      "quant", obj({"symbols": {"type": "array", "items": SYMBOL, "minItems": 2, "maxItems": 20,
                                "description": "Tickers, e.g. ['SPY', 'TLT', 'GLD']."}}, ["symbols"]),
      open_world=True)
async def _qf_risk_parity(ctx, a):
    np, _, qm = _qf()
    from .fund import agents as FA
    from .fund.engine import aligned_returns
    res = await asyncio.gather(*(market.history(_sym({"symbol": s}), "1y", "1d") for s in a["symbols"]))
    rets = aligned_returns({h["symbol"]: h["candles"] for h in res})
    info = FA.covariance(rets)
    if not info:
        raise ToolError("Not enough common history between those tickers.")
    syms, cov, t = info
    w = qm.risk_parity(cov)
    rc = w * (cov @ w)
    return {"weights": dict(zip(syms, map(float, w))), "annual_vol": dict(zip(syms, map(float, np.sqrt(np.diag(cov) * 252)))),
            "risk_contribution": dict(zip(syms, map(float, rc / rc.sum()))), "days": t,
            "reference": "Maillard, Roncalli y Teïletche (2010); quantfin.risk_parity"}


@tool("qf_yield_curve", "Fit yield curve (Nelson-Siegel)", "Fit a Nelson-Siegel curve to maturities (years) and "
      "yields (decimals). Returns level, slope, curvature, lambda and fitted yields.", "quant",
      obj({"maturities": {"type": "array", "items": p_num("Maturity in years.", exclusiveMinimum=0, maximum=100),
                          "minItems": 4, "maxItems": 40, "description": "e.g. [0.25, 1, 2, 5, 10, 30]"},
           "yields": {"type": "array", "items": p_num("Yield as decimal (0.042 = 4.2%).", minimum=-0.1, maximum=1),
                      "minItems": 4, "maxItems": 40, "description": "Same length as maturities."}},
          ["maturities", "yields"]))
async def _qf_curve(ctx, a):
    np, _, qm = _qf()
    tau, y = np.array(a["maturities"], dtype=float), np.array(a["yields"], dtype=float)
    if len(tau) != len(y):
        raise ToolError("maturities and yields must have the same length.")
    b0, b1, b2, lam = qm.ajustar_ns(tau, y)
    fit = qm.nelson_siegel(tau, b0, b1, b2, lam)
    return {"level": float(b0), "slope": float(b1), "curvature": float(b2), "lambda": float(lam),
            "fitted": [float(v) for v in fit], "rmse_bp": float(np.sqrt(np.mean((fit - y) ** 2)) * 1e4),
            "reference": "Nelson y Siegel (1987), Journal of Business"}


@tool("qf_bond", "Bond price, duration and convexity", "Price (per 100 face), modified duration and convexity of a "
      "fixed-coupon bond.", "quant",
      obj({"coupon": p_num("Annual coupon rate as decimal.", minimum=0, maximum=1),
           "ytm": p_num("Yield to maturity as decimal.", minimum=-0.05, maximum=1),
           "years": p_int("Years to maturity.", minimum=1, maximum=100),
           "freq": p_int("Coupons per year.", minimum=1, maximum=12, default=2)}, ["coupon", "ytm", "years"]))
async def _qf_bond(ctx, a):
    _, _, qm = _qf()
    price, mod_dur, conv = qm.duracion_convexidad(float(a["coupon"]), float(a["ytm"]), int(a["years"]),
                                                  int(a.get("freq", 2)))
    return {"price": float(price), "modified_duration": float(mod_dur), "convexity": float(conv)}


@tool("qf_kelly_binary", "Kelly bet (prediction market)", "Kelly fraction of capital to buy YES on a binary contract "
      "that pays 1, given your probability and the market price (0 if you have no edge).", "quant",
      obj({"probability": p_num("Your probability of YES.", minimum=0, maximum=1),
           "price": p_num("Market price of YES (0-1).", exclusiveMinimum=0, maximum=0.9999)},
          ["probability", "price"]))
async def _qf_kelly(ctx, a):
    _, _, qm = _qf()
    f = qm.kelly_binario(float(a["probability"]), float(a["price"]))
    return {"kelly_fraction": f, "half_kelly": f / 2,
            "note": "Full Kelly is very volatile; practitioners often bet half Kelly or less."}


@tool("qf_market_making", "Market-making quotes (Avellaneda-Stoikov)", "Optimal bid/ask around a mid price given "
      "inventory, risk aversion, volatility, time left and order-arrival decay.", "quant",
      obj({"mid": p_num("Mid price.", exclusiveMinimum=0), "inventory": p_num("Current inventory (units)."),
           "gamma": p_num("Risk aversion.", exclusiveMinimum=0, maximum=10, default=0.1),
           "sigma": p_num("Volatility of the mid price (price units).", exclusiveMinimum=0),
           "time_left": p_num("Remaining horizon (fraction of session).", exclusiveMinimum=0, maximum=1, default=0.5),
           "k": p_num("Order-arrival decay.", exclusiveMinimum=0, default=1.5)}, ["mid", "inventory", "sigma"]))
async def _qf_mm(ctx, a):
    _, _, qm = _qf()
    bid, ask = qm.avellaneda_stoikov(float(a["mid"]), float(a["inventory"]), float(a.get("gamma", 0.1)),
                                     float(a["sigma"]), float(a.get("time_left", 0.5)), float(a.get("k", 1.5)))
    return {"bid": float(bid), "ask": float(ask), "spread": float(ask - bid), "reservation_price": float((bid + ask) / 2)}


@tool("qf_execution_plan", "Execution cost and schedule", "Estimate the market impact of trading `qty` units with "
      "the square-root law (sigma * sqrt(Q/V), from 20-day volatility and volume) and an Almgren-Chriss liquidation "
      "schedule over `steps` slices.", "quant",
      obj({"symbol": SYMBOL, "qty": p_num("Units to trade.", exclusiveMinimum=0),
           "steps": p_int("Number of slices.", minimum=2, maximum=50, default=5),
           "risk_aversion": p_num("Almgren-Chriss lambda.", minimum=0, maximum=1, default=1e-6)}, ["symbol", "qty"]),
      open_world=True)
async def _qf_impact(ctx, a):
    np, qa, qm = _qf()
    from .fund.engine import liquidity
    sym, candles, src = await _daily_closes(a["symbol"], "3mo")
    liq = liquidity({sym: candles}).get(sym)
    if not liq or not liq[1]:
        raise ToolError(f"No volume data for {sym}: impact cannot be estimated.")
    sig_d, vol_avg = liq
    qty = float(a["qty"])
    impact = float(qa.impacto_raiz(sig_d, qty, vol_avg))
    lam = float(a.get("risk_aversion", 1e-6))
    eta = max(1e-9, impact * candles[-1]["c"] / max(qty, 1))  # escala la impaciencia con el impacto estimado
    sched = qm.almgren_chriss(qty, 1.0, int(a.get("steps", 5)), sig_d * candles[-1]["c"], eta, lam) if lam > 0 else \
        np.linspace(qty, 0, int(a.get("steps", 5)) + 1)
    return {"symbol": sym, "qty": qty, "pct_of_daily_volume": qty / vol_avg * 100, "impact_bps": impact * 1e4,
            "daily_vol": sig_d, "remaining_inventory_by_step": [float(x) for x in sched], "source": src,
            "references": ["Bonart (2026, preprint) — ley de la raíz cuadrada", "Almgren y Chriss (2001)"]}


@tool("qf_catalog", "List quantfin functions", "Catalogue of all 39 functions of the quantfin library "
      "(quant-finance-research): market, parameters with limits, outputs, the papers behind each one, where the "
      "terminal already uses it, and a ready-to-run example. Use it before qf_function.", "quant",
      obj({"query": p_str("Filter by name, market or paper, e.g. 'bond', 'Kelly', 'covariance'.", maxLength=60),
           "name": p_str("Return just this function's full description.", maxLength=40)}))
async def _qf_catalog(ctx, a):
    from . import quantfin_catalog as qc
    if a.get("name"):
        if a["name"] not in qc.FUNCS:
            raise ToolError(f"Unknown function {a['name']!r}. Call qf_catalog() without arguments to list them.")
        return qc.describe(a["name"])
    q = str(a.get("query") or "").lower()
    rows = [{k: d[k] for k in ("name", "market", "summary", "papers", "used_in")} | {"params": [p["name"] for p in d["params"]]}
            for d in qc.catalog() if not q or q in f"{d['name']} {d['market']} {d['summary']} {d['papers']}".lower()]
    return {"total": len(rows), "functions": rows}


@tool("qf_function", "Run any quantfin function", "Run one of the 39 quantfin functions on numbers you pass: "
      "options (black_scholes, monte_carlo_call, pnl_cobertura), bonds and curves, FX carry, commodity basis, "
      "time-series momentum, market making, execution, DeFi (LVR, impermanent loss), prediction markets (Kelly, LMSR, "
      "Brier), risk (VaR/ES, GARCH, min-variance, risk parity, Sharpe) and the advanced models (OU, SADF, absorption "
      "ratio, Deflated Sharpe, Higham, Pafka-Kondor, EMA/Donchian, vol targeting, square-root impact). Arguments go "
      "in `args` with the names from qf_catalog(name=...); arrays are capped (5000 values, 50000 matrix cells).",
      "quant", obj({"function": p_str("Function name, e.g. 'black_scholes', 'var_es', 'carry_trade'.",
                                      minLength=2, maxLength=40),
                    "args": {"type": "object", "description": "Arguments by name, e.g. {\"S\":100,\"K\":100,"
                             "\"T\":1,\"r\":0.05,\"sigma\":0.2}. Omit to run the catalogue example."}},
                   ["function"]))
async def _qf_function(ctx, a):
    from . import quantfin_catalog as qc
    name = str(a["function"])
    if name not in qc.FUNCS:
        raise ToolError(f"Unknown function {name!r}. Call qf_catalog(query=...) to find the right one.")
    args = a.get("args")
    if args is None:
        args = qc.describe(name)["example"]
    if not isinstance(args, dict):
        raise ToolError("'args' must be an object with named arguments.")
    try:
        return await asyncio.to_thread(qc.call, name, args)
    except qc.QfArgError as e:
        raise ToolError(f"{e} See qf_catalog(name='{name}').") from e


# ── Fondo multi-agente (paper) ──────────────────────────────────────────────

def _fund_summary(run: dict | None) -> dict | None:
    if not run:
        return None
    rep = run["report"]
    return {"run_id": run["id"], "status": run["status"], "trigger": run["trigger"], "equity": run["equity"],
            "regime": rep.get("macro"), "target_weights": rep.get("target"), "orders": rep.get("orders"),
            "risk_checks": rep.get("risk_checks"), "circuit_breaker": rep.get("circuit_breaker"),
            "desk_trust": rep.get("desk_trust"), "learning": rep.get("learning"), "fills": rep.get("fills"),
            "memo": rep.get("memo_llm") or rep.get("memo")}


@tool("fund_get_state", "Get AI fund state", "State of the multi-agent paper fund: autopilot, kill switch, desk "
      "trust learned from past calls, and a summary of the last investment committee (regime, target weights, "
      "orders, risk checks, memo).", "fund", obj({}), idempotent=False)
async def _fund_state(ctx, a):
    from .fund import engine
    st = engine.get_state(ctx.user["id"])
    return {"autopilot": st["autopilot"], "halted": st["halted"], "halt_reason": st["halt_reason"],
            "desk_trust": st["desk_trust"], "mode": "paper", "last_run": _fund_summary(engine.last_run(ctx.user["id"]))}


@tool("fund_run_cycle", "Run AI fund committee", "Run one investment committee cycle of the multi-agent paper fund "
      "(macro, sentiment, desk analysts, quant, CIO, risk manager) and return the PROPOSED orders. Never executes; "
      "use fund_execute_run with the run_id. Slow: may return a job_id.", "fund", obj({}), destructive=True,
      destructive_hint=False, idempotent=False, open_world=True, long_running=True)
async def _fund_cycle(ctx, a):
    from .fund import engine
    try:
        return _fund_summary(await engine.run_cycle(ctx.user["id"], execute=False, trigger=f"mcp:{ctx.client}"))
    except engine.FundError as e:
        raise ToolError(str(e)) from e


@tool("fund_execute_run", "Execute AI fund proposal", "Execute in the PAPER account the orders proposed by a fund "
      "cycle (must be < 15 min old). Risk limits and the kill switch are re-checked before sending. Needs 'allow "
      "actions' and the user's approval in the terminal.", "fund",
      obj({"run_id": p_int("run_id returned by fund_run_cycle.", minimum=1)}, ["run_id"]),
      destructive=True, needs_approval=True, idempotent=False)
async def _fund_exec(ctx, a):
    from .fund import engine
    try:
        return _fund_summary(await engine.execute_run(ctx.user["id"], int(a["run_id"])))
    except engine.FundError as e:
        raise ToolError(f"{e} Check the last run with fund_get_state.") from e


# ── DataHub / sistema ───────────────────────────────────────────────────────

@tool("datahub_topics", "List DataHub topics", "Live DataHub topics (one fetch, many subscribers): subscribers, "
      "TTL, age, refresh and publish counters, errors.", "system", obj({}), idempotent=False)
async def _dh_topics(ctx, a):
    uid = ctx.user["id"]
    return [t for t in hub.stats() if topic_allowed(t["topic"], uid)]


@tool("datahub_peek", "Peek DataHub topic", "Last-known value of a DataHub topic without triggering a fetch, e.g. "
      "'market:quote:AAPL' or 'news:top'. Returns null if nobody has subscribed yet: use get_quote instead.",
      "system", obj({"topic": p_str("Topic name domain:subdomain:id.", maxLength=120)}, ["topic"]),
      idempotent=False)
async def _dh_peek(ctx, a):
    t = str(a["topic"])
    if not topic_allowed(t, ctx.user["id"]):
        raise ToolError("That topic belongs to another user. List yours with datahub_topics.")
    return {"topic": t, "value": hub.peek(t)}


@tool("get_profile", "Get profile", "Account profile, plan and remaining credits.", "system", obj({}))
async def _profile(ctx, a):
    from .auth import public_profile
    return public_profile(get_db().one("SELECT * FROM users WHERE id=?", (ctx.user["id"],)))


@tool("get_time", "Get server time", "Current server time (UTC) and data mode ('live' or 'sim').", "system", obj({}),
      idempotent=False)
async def _time(ctx, a):
    from .config import settings
    return {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "data_mode": settings.data_mode}


# ── búsqueda BM25 (tool_list del servidor MCP) ──────────────────────────────

def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("_", " "))


def search_tools(query: str, limit: int = 10) -> list[ToolDef]:
    docs = {n: _tokens(f"{t.name} {t.name} {t.title} {t.category} {t.description}") for n, t in REGISTRY.items()}
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


# ── validación ──────────────────────────────────────────────────────────────

_TYPES = {"string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
          "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v),
          "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
          "array": lambda v: isinstance(v, list), "object": lambda v: isinstance(v, dict)}


def _check(name: str, p: dict, v: Any) -> None:
    typ = p.get("type")
    if typ and not _TYPES.get(typ, lambda _: True)(v):
        raise ToolError(f"'{name}' must be of type {typ}, got {type(v).__name__}.")
    if "enum" in p and v not in p["enum"]:
        raise ToolError(f"'{name}' must be one of {p['enum']}, got {v!r}.")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in p and v < p["minimum"]:
            raise ToolError(f"'{name}' must be >= {p['minimum']}, got {v}.")
        if "maximum" in p and v > p["maximum"]:
            raise ToolError(f"'{name}' must be <= {p['maximum']}, got {v}.")
        if "exclusiveMinimum" in p and v <= p["exclusiveMinimum"]:
            raise ToolError(f"'{name}' must be > {p['exclusiveMinimum']}, got {v}.")
    if isinstance(v, str):
        if len(v) < p.get("minLength", 0):
            raise ToolError(f"'{name}' must not be empty.")
        if "maxLength" in p and len(v) > p["maxLength"]:
            raise ToolError(f"'{name}' is too long (max {p['maxLength']} characters).")
    if isinstance(v, list):
        if len(v) < p.get("minItems", 0):
            raise ToolError(f"'{name}' needs at least {p['minItems']} item(s).")
        if "maxItems" in p and len(v) > p["maxItems"]:
            raise ToolError(f"'{name}' accepts at most {p['maxItems']} items; split the request.")
        for i, item in enumerate(v):
            _check(f"{name}[{i}]", p.get("items", {}), item)


def validate_args(t: ToolDef, args: dict) -> None:
    """Valida contra el JSON Schema de la tool (tipos, enums, rangos, longitudes, extras)."""
    if not isinstance(args, dict):
        raise ToolError("arguments must be a JSON object.")
    props = t.input_schema.get("properties", {})
    for r in t.input_schema.get("required", []):
        if r not in args or args[r] in (None, ""):
            raise ToolError(f"Missing required argument '{r}'. Call tool_describe(name='{t.name}') for the schema.")
    for k, v in args.items():
        if k not in props:
            raise ToolError(f"Unknown argument '{k}'. Valid arguments for {t.name}: {', '.join(sorted(props))}.")
        if v is not None:
            _check(k, props[k], v)


async def call_tool(name: str, args: dict, ctx: ToolContext) -> Any:
    t = REGISTRY.get(name)
    if not t:
        raise ToolError(f"Unknown tool '{name}'. Search the catalogue with tool_list(query='what you need').")
    validate_args(t, args or {})
    return await t.handler(ctx, args or {})


__all__ = ["REGISTRY", "ToolDef", "ToolContext", "ToolError", "call_tool", "search_tools", "paginate"]
