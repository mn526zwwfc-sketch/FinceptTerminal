"""Rutas REST de datos: /market, /news, /macro, /quantlib, /paper, /datahub.

Los paths y parámetros de /market/* siguen el OpenAPI público de
api.fincept.in (search, price, info, snapshot, history, news, batch/prices).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from . import analytics, backtest, macro, news, paper
from .auth import fail, ok, require_auth
from .datahub import hub, topic_allowed
from .market.providers import market, normalize_symbol

router = APIRouter()


def _sym(symbol: str) -> str | None:
    try:
        return normalize_symbol(symbol)
    except ValueError:
        return None


# ── /market ─────────────────────────────────────────────────────────────────

@router.get("/market/search")
async def market_search(q: str = Query(min_length=1, max_length=60), limit: int = Query(10, ge=1, le=25)):
    return ok(await market.search(q, limit))  # "No credits required" en el servidor real


@router.get("/market/price/{symbol}")
async def market_price(symbol: str, user: dict = Depends(require_auth)):
    s = _sym(symbol)
    if not s:
        return fail("Invalid symbol")
    return ok(await market.quote(s))


@router.get("/market/snapshot/{symbol}")
@router.get("/market/info/{symbol}")
async def market_info(symbol: str, user: dict = Depends(require_auth)):
    s = _sym(symbol)
    if not s:
        return fail("Invalid symbol")
    return ok(await market.info(s))


@router.get("/market/history/{symbol}")
async def market_history(symbol: str, period: str = "6mo", interval: str | None = None,
                         user: dict = Depends(require_auth)):
    s = _sym(symbol)
    if not s:
        return fail("Invalid symbol")
    return ok(await market.history(s, period, interval))


@router.get("/market/batch/prices")
async def market_batch(symbols: str = Query(max_length=600), user: dict = Depends(require_auth)):
    syms = [x for x in (_sym(s) for s in symbols.split(",")) if x][:50]
    return ok(list((await market.quotes(syms)).values()))


@router.get("/market/news/{symbol}")
async def market_news(symbol: str, limit: int = Query(15, ge=1, le=50), user: dict = Depends(require_auth)):
    s = _sym(symbol)
    if not s:
        return fail("Invalid symbol")
    return ok(await news.symbol_news(s, limit))


@router.get("/market/risk/{symbol}")
async def market_risk(symbol: str, period: str = "1y", confidence: float = Query(0.95, gt=0.5, lt=0.999),
                      user: dict = Depends(require_auth)):
    s = _sym(symbol)
    if not s:
        return fail("Invalid symbol")
    h = await market.history(s, period, "1d")
    try:
        return ok({"symbol": s, "source": h["source"], **analytics.risk_metrics([c["c"] for c in h["candles"]],
                                                                               confidence=confidence)})
    except ValueError as e:
        return fail(str(e))


# ── /news ───────────────────────────────────────────────────────────────────

@router.get("/news/top")
async def news_top(limit: int = Query(40, ge=1, le=100), q: str | None = None, user: dict = Depends(require_auth)):
    return ok(await news.top_news(limit, q))


# ── /macro ──────────────────────────────────────────────────────────────────

@router.get("/macro/presets")
async def macro_presets(user: dict = Depends(require_auth)):
    return ok(macro.PRESETS)


@router.get("/macro/series")
async def macro_series(id: str = Query(max_length=120), limit: int = Query(120, ge=1, le=2000),
                       user: dict = Depends(require_auth)):
    try:
        return ok(await macro.observations(id, limit))
    except macro.MacroError as e:
        return fail(str(e))


@router.get("/macro/search")
async def macro_search(q: str = Query(min_length=2, max_length=80), user: dict = Depends(require_auth)):
    try:
        return ok(await macro.search(q, 15))
    except macro.MacroError as e:
        return fail(str(e))


# ── /quantlib (subconjunto) ─────────────────────────────────────────────────

class BSIn(BaseModel):
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    time_to_expiry: float = Field(gt=0, description="years")
    rate: float = 0.04
    volatility: float = Field(gt=0, lt=10)
    option_type: str = Field(default="call", pattern="^(call|put)$")
    dividend_yield: float = 0.0


class IVIn(BaseModel):
    price: float = Field(gt=0)
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    time_to_expiry: float = Field(gt=0)
    rate: float = 0.04
    option_type: str = Field(default="call", pattern="^(call|put)$")


@router.post("/quantlib/pricing/bs/price")
async def bs_price(b: BSIn, user: dict = Depends(require_auth)):
    return ok({"price": analytics.bs_price(b.spot, b.strike, b.time_to_expiry, b.rate, b.volatility, b.option_type,
                                           b.dividend_yield)})


@router.post("/quantlib/pricing/bs/greeks")
async def bs_greeks(b: BSIn, user: dict = Depends(require_auth)):
    return ok(analytics.bs_greeks(b.spot, b.strike, b.time_to_expiry, b.rate, b.volatility, b.option_type,
                                  b.dividend_yield))


@router.post("/quantlib/pricing/bs/implied-vol")
async def bs_iv(b: IVIn, user: dict = Depends(require_auth)):
    try:
        return ok({"implied_volatility": analytics.implied_vol(b.price, b.spot, b.strike, b.time_to_expiry, b.rate,
                                                               b.option_type)})
    except ValueError as e:
        return fail(str(e))


class BacktestIn(BaseModel):
    symbol: str
    period: str = "2y"
    fast: int = Field(20, ge=2, le=200)
    slow: int = Field(50, ge=3, le=400)
    initial_cash: float = Field(10_000, gt=0)
    commission_bps: float = Field(5.0, ge=0, le=500)
    slippage_bps: float = Field(5.0, ge=0, le=500)


@router.post("/backtest/sma")
async def backtest_sma(b: BacktestIn, user: dict = Depends(require_auth)):
    s = _sym(b.symbol)
    if not s:
        return fail("Invalid symbol")
    h = await market.history(s, b.period, "1d")
    try:
        r = await asyncio.to_thread(backtest.backtest_sma_cross, h["candles"], b.fast, b.slow, b.initial_cash,
                                    backtest.CostModel(b.commission_bps, b.slippage_bps))
    except ValueError as e:
        return fail(str(e))
    return ok({"symbol": s, "source": h["source"], **r})


class WalkForwardIn(BaseModel):
    symbol: str
    period: str = "10y"
    train_bars: int = Field(504, ge=100, le=2520)
    test_bars: int = Field(126, ge=20, le=1260)
    anchored: bool = False
    commission_bps: float = Field(5.0, ge=0, le=500)
    slippage_bps: float = Field(5.0, ge=0, le=500)


@router.post("/backtest/walk-forward")
async def backtest_walk_forward(b: WalkForwardIn, user: dict = Depends(require_auth)):
    s = _sym(b.symbol)
    if not s:
        return fail("Invalid symbol")
    h = await market.history(s, b.period, "1d")
    try:
        r = await asyncio.to_thread(backtest.walk_forward_sma, h["candles"], b.train_bars, b.test_bars, b.anchored,
                                    None, None, 10_000.0, backtest.CostModel(b.commission_bps, b.slippage_bps))
    except ValueError as e:
        return fail(str(e))
    return ok({"symbol": s, "source": h["source"], **r})


# ── /paper ──────────────────────────────────────────────────────────────────

class OrderIn(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    qty: float = Field(gt=0)
    type: str = Field(default="market", pattern="^(market|limit|stop)$")
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)


@router.get("/paper/account")
async def paper_account(user: dict = Depends(require_auth)):
    return ok({**(await paper.account(user["id"])), "orders": paper.list_orders(user["id"], limit=30)})


@router.get("/paper/orders")
async def paper_orders(status: str | None = None, user: dict = Depends(require_auth)):
    return ok(paper.list_orders(user["id"], status))


@router.post("/paper/orders")
async def paper_place(o: OrderIn, user: dict = Depends(require_auth)):
    try:
        order = await paper.place_order(user["id"], o.symbol, o.side, o.qty, o.type, o.limit_price, o.stop_price)
    except paper.OrderError as e:
        return fail(str(e))
    if order["status"] == "rejected":
        return fail(order["note"] or "order rejected", data=order)
    return ok(order, f"Order {order['status']}")


@router.delete("/paper/orders/{order_id}")
async def paper_cancel(order_id: int, user: dict = Depends(require_auth)):
    try:
        return ok(await paper.cancel_order(user["id"], order_id), "Order cancelled")
    except paper.OrderError as e:
        return fail(str(e))


@router.post("/paper/reset")
async def paper_reset(user: dict = Depends(require_auth)):
    return ok(await paper.reset(user["id"]), "Paper account reset")


# ── /datahub (inspector) ────────────────────────────────────────────────────

@router.get("/datahub/topics")
async def datahub_topics(user: dict = Depends(require_auth)):
    uid = user["id"]
    return ok([t for t in hub.stats()
               if topic_allowed(t["topic"], uid)])


# ── /api/tools (la UI usa el mismo catálogo que MCP y el chat) ──────────────

class ToolCallIn(BaseModel):
    name: str = Field(max_length=64)
    arguments: dict = Field(default_factory=dict)


@router.post("/api/tools/call")
async def tools_call(body: ToolCallIn, user: dict = Depends(require_auth)):
    from .tools import ToolContext, ToolError, call_tool

    try:
        return ok(await call_tool(body.name, body.arguments, ToolContext(user=user, source="ui", client="terminal")))
    except ToolError as e:
        return fail(str(e))
