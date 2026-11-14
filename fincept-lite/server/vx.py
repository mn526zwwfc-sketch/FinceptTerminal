"""Monitores multi-mercado y ficha de instrumento (/vx/*).

Monitores por clase de activo (índices, acciones, divisas, tasas, materias primas, cripto y ETF) con
rendimientos, rango de 52 semanas y minigráfico; curva del Tesoro con ajuste Nelson-Siegel; matriz de
cruces de divisas; y ficha de instrumento con técnico, riesgo y la opinión del fondo de agentes.
Todo es de lectura y sale del resto del servidor (mercado, macro, fondo y quantfin).
"""

from __future__ import annotations

import asyncio
import math
import statistics
import time

from fastapi import APIRouter, Depends, HTTPException, Query

from . import analytics, fred, news
from . import quantfin_catalog as QC
from . import universe as U
from .auth import fail, ok, require_auth
from .fund import agents as A
from .fund import engine
from .fund import live as L
from .fund import training as T
from .fund.research import knowledge_base
from .market.providers import market, normalize_symbol

router = APIRouter(prefix="/vx")


def _r(x, n: int = 6):
    """Redondeo a cifras significativas; None para lo que no es un número finito."""
    if x is None or isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        return None
    return float(f"{x:.{n}g}")


def _sym(symbol: str) -> str:
    try:
        return normalize_symbol(symbol)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Símbolo no válido") from e


# ── cálculo de filas de monitor ─────────────────────────────────────────────

def _perf(closes: list[float], n: int):
    return closes[-1] / closes[-1 - n] - 1 if len(closes) > n and closes[-1 - n] else None


def _ytd_base(candles: list[dict]):
    year = time.gmtime(candles[-1]["t"]).tm_year
    for i in range(len(candles) - 1, 0, -1):
        if time.gmtime(candles[i - 1]["t"]).tm_year < year:
            return candles[i - 1]["c"]
    return None


def row(symbol: str, name: str, group: str, h: dict) -> dict | None:
    cs = h["candles"]
    closes = [c["c"] for c in cs]
    if len(closes) < 2:
        return None
    last, prev = closes[-1], closes[-2]
    year = closes[-252:]
    hi, lo = max(year), min(year)
    base = _ytd_base(cs)
    is_yield = symbol in U.YIELDS
    if is_yield:  # los rendimientos se comparan en puntos básicos, no en porcentaje

        def d(n):
            return (last - closes[-1 - n]) * 100 if len(closes) > n else None
        perf = {"p5d": d(5), "p1m": d(21), "p3m": d(63), "ytd": (last - base) * 100 if base else None, "p1y": d(251)}
    else:
        perf = {"p5d": _perf(closes, 5), "p1m": _perf(closes, 21), "p3m": _perf(closes, 63),
                "ytd": last / base - 1 if base else None, "p1y": _perf(closes, 251)}
    return {"symbol": symbol, "name": name, "group": group, "last": _r(last), "chg": _r(last - prev),
            "chg_pct": _r((last / prev - 1) * 100 if prev else 0.0, 4), **{k: _r(v, 4) for k, v in perf.items()},
            "hi52": _r(hi), "lo52": _r(lo), "pos52": _r((last - lo) / (hi - lo), 3) if hi > lo else 0.5,
            "vol20": _r(A.realized_vol(closes, 20), 3), "spark": [_r(x, 5) for x in closes[-30:]],
            "is_yield": is_yield, "currency": h.get("currency", ""), "source": h.get("source", "?"), "t": cs[-1]["t"]}


async def _rows(items: list[tuple[str, str, str]]) -> list[dict]:
    res = await asyncio.gather(*(market.history(s, "2y", "1d") for s, _, _ in items), return_exceptions=True)
    out = []
    for (s, n, g), h in zip(items, res):
        r = row(s, n, g, h) if isinstance(h, dict) else None
        if r:
            out.append(r)
    return out


def yield_curve(rows: list[dict]) -> dict | None:
    """Curva del Tesoro con los rendimientos disponibles y su ajuste Nelson-Siegel (quantfin.ajustar_ns)."""
    ys = [r for r in rows if r["symbol"] in U.YIELDS and r["last"]]
    if any(r["source"] == "sim" for r in ys):  # un rendimiento simulado no es una curva: no se dibuja
        return None
    pts = sorted((U.YIELDS[r["symbol"]], r["last"]) for r in ys)
    if len(pts) < 3:
        return None
    out = {"points": [{"tenor": t, "yield": y} for t, y in pts],
           "slope_10y_3m": _r(dict(pts).get(10.0, 0) - dict(pts).get(0.25, 0), 4) if 10.0 in dict(pts) else None}
    try:
        res = QC.call("ajustar_ns", {"plazos": [t for t, _ in pts], "tasas": [y / 100 for _, y in pts]})["result"]
        fit = QC.call("nelson_siegel", {"tau": [0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30], "b0": res["nivel"],
                                        "b1": res["pendiente"], "b2": res["curvatura"], "lam": res["lambda"]})
        out["nelson_siegel"] = {k: _r(v, 5) for k, v in res.items()}
        out["fit"] = [{"tenor": t, "yield": _r(y * 100, 5)}
                      for t, y in zip([0.25, 0.5, 1, 2, 3, 5, 7, 10, 15, 20, 30], fit["result"]["tasas"])]
    except Exception:  # el ajuste es un extra: sin él la curva observada sigue siendo válida
        pass
    return out


CROSS = ["USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "MXN"]


def cross_matrix(rows: list[dict]) -> dict | None:
    px = {r["symbol"]: r["last"] for r in rows}
    try:
        usd_per = {"USD": 1.0, "EUR": px["EURUSD=X"], "GBP": px["GBPUSD=X"], "AUD": px["AUDUSD=X"],
                   "JPY": 1 / px["USDJPY=X"], "CHF": 1 / px["USDCHF=X"], "CAD": 1 / px["USDCAD=X"],
                   "MXN": 1 / px["USDMXN=X"]}
    except (KeyError, TypeError, ZeroDivisionError):
        return None
    return {"ccys": CROSS, "matrix": [[_r(usd_per[a] / usd_per[b], 5) for b in CROSS] for a in CROSS]}


@router.get("/universe")
async def universe(user: dict = Depends(require_auth)):
    return ok([{"id": c["id"], "code": c["code"], "name": c["name"],
                "groups": [{"name": g, "items": [{"symbol": s, "name": n} for s, n in items]}
                           for g, items in c["groups"]]} for c in U.CLASSES])


@router.get("/monitor/{cls}")
async def monitor(cls: str, user: dict = Depends(require_auth)):
    if cls not in U.BY_ID:
        return fail("Clase de activo desconocida")
    rows = await _rows(U.symbols(cls))
    out = {"class": cls, "name": U.BY_ID[cls]["name"], "rows": rows, "as_of": max((r["t"] for r in rows), default=None),
           "sources": sorted({r["source"] for r in rows})}
    if cls == "tasas":
        out["curve"] = yield_curve(rows)
    if cls == "divisas":
        out["cross"] = cross_matrix(rows)
    return ok(out)


# ── ficha de un instrumento ─────────────────────────────────────────────────

def _beta(candles: list[dict], bench: list[dict]) -> dict:
    a = {c["t"] // 86400: c["c"] for c in candles[-260:]}
    b = {c["t"] // 86400: c["c"] for c in bench[-260:]}
    days = sorted(set(a) & set(b))
    ra = [a[days[i]] / a[days[i - 1]] - 1 for i in range(1, len(days))]
    rb = [b[days[i]] / b[days[i - 1]] - 1 for i in range(1, len(days))]
    if len(ra) < 60 or statistics.pvariance(rb) == 0 or statistics.pstdev(ra) == 0:
        return {"beta": None, "corr": None}
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    cov = statistics.fmean([(x - ma) * (y - mb) for x, y in zip(ra, rb)])
    return {"beta": _r(cov / statistics.pvariance(rb), 3),
            "corr": _r(cov / (statistics.pstdev(ra) * statistics.pstdev(rb)), 3)}


def _fund_context(uid: int, symbol: str) -> dict | None:
    if symbol not in A.BY_SYMBOL:
        return None
    out: dict = {"desk": A.BY_SYMBOL[symbol].desk}
    tr = T.latest(uid)
    b = (tr or {}).get("book", {}).get(symbol)
    if b and b.get("trained"):
        out["book"] = {"verdict": b.get("verdict"), "validated": b.get("validated", False),
                       "members": [{"config": m["config"], "weight": _r(m["weight"], 3)} for m in b.get("members", [])],
                       "test_sharpe": _r((b.get("test") or {}).get("sharpe"), 3),
                       "buy_hold_sharpe": _r((b.get("buy_hold_test") or {}).get("sharpe"), 3),
                       "exposure_now": _r(b.get("exposure_now"), 3), "cost_bps": b.get("cost_bps")}
    run = engine.last_run(uid)
    v = ((run or {}).get("report") or {}).get("views", {}).get(symbol)
    if v:
        out["view"] = {"score": _r(v["score"], 3), "verdict": v["debate"]["verdict"], "bull": v["debate"]["bull"],
                       "bear": v["debate"]["bear"], "target": run["report"]["target"].get(symbol)}
    return out


@router.get("/security/{symbol}")
async def security(symbol: str, period: str = Query("1y", pattern="^(1y|5y)$"), user: dict = Depends(require_auth)):
    s = _sym(symbol)
    h = await market.history(s, "2y", "1d")
    cs = h["candles"]
    if len(cs) < 2:
        return fail(f"Sin datos para {s}")
    closes = [c["c"] for c in cs]
    info = U.find(s) or {"class": None, "class_name": None, "group": None, "name": h.get("name") or s}
    base = row(s, info["name"], info["group"] or "", h)
    year = closes[-253:]
    risk = analytics.risk_metrics(year) if len(year) > 30 else {}
    stats = {**{k: base[k] for k in ("last", "chg", "chg_pct", "p5d", "p1m", "p3m", "ytd", "p1y", "hi52", "lo52",
                                     "pos52", "vol20", "is_yield")},
             "open": _r(cs[-1]["o"]), "high": _r(cs[-1]["h"]), "low": _r(cs[-1]["l"]), "volume": cs[-1]["v"],
             "prev_close": _r(closes[-2]), "p6m": _r(_perf(closes, 126), 4),
             **{f"sma{n}": _r(statistics.fmean(closes[-n:])) for n in (20, 50, 200) if len(closes) >= n},
             "rsi14": _r(A.rsi(closes)[-1], 4), "vol60": _r(A.realized_vol(closes, 60), 3),
             "ann_vol": _r(risk.get("annualized_volatility"), 3), "sharpe": _r(risk.get("sharpe"), 3),
             "sortino": _r(risk.get("sortino"), 3), "max_drawdown": _r(risk.get("max_drawdown"), 3),
             "var95": _r(risk.get("var_historical"), 3), "cvar95": _r(risk.get("cvar_historical"), 3),
             "best_day": _r(risk.get("best_day"), 3), "worst_day": _r(risk.get("worst_day"), 3)}
    if s != U.BENCHMARK:
        try:
            stats |= _beta(cs, (await market.history(U.BENCHMARK, "2y", "1d"))["candles"])
        except Exception:
            stats |= {"beta": None, "corr": None}
    try:
        sig = await asyncio.to_thread(A.asset_signals, closes)
        stats["signals"] = {"trend": sig["trend"], "momentum": _r(sig["momentum"], 3), "score": _r(sig["score"], 3),
                            "mom_12_1": _r(sig["mom_12_1"], 4), "drawdown": _r(sig["drawdown"], 3),
                            "panic_state": bool(sig["panic_state"]), "sadf": _r(sig["sadf"], 3),
                            "bubble": bool(sig["bubble"])}
    except ValueError:
        stats["signals"] = None
    if period == "5y":
        chart = (await market.history(s, "5y", "1wk"))["candles"]
    else:
        chart = cs[-260:]
    return ok({"symbol": s, **info, "currency": h.get("currency", ""), "source": h.get("source", "?"),
               "interval": "1wk" if period == "5y" else "1d", "t": cs[-1]["t"], "stats": stats,
               "candles": [[c["t"], _r(c["o"]), _r(c["h"]), _r(c["l"]), _r(c["c"]), c["v"]] for c in chart],
               "fund": _fund_context(user["id"], s)})


# ── noticias, macro, fondo, conocimiento ────────────────────────────────────

@router.get("/news")
async def vx_news(symbol: str | None = None, q: str | None = Query(None, max_length=60),
                  limit: int = Query(40, ge=1, le=80), user: dict = Depends(require_auth)):
    items = await (news.symbol_news(_sym(symbol), limit) if symbol else news.top_news(limit, q))
    return ok([{k: x.get(k) for k in ("title", "link", "source", "published", "sentiment", "sentiment_score")}
               for x in items])


MACRO_UNITS = {"fed": "%", "unemployment": "%", "inflation": "% interanual"}


@router.get("/macro")
async def vx_macro(user: dict = Depends(require_auth)):
    series = await engine._macro_series()
    meta = series["meta"]
    regime = A.macro_regime(series["fed"], series["unemployment"], series["inflation"], None, meta)
    run = engine.last_run(user["id"])
    rep = (run or {}).get("report") or {}
    rates = await _rows([x for x in U.symbols("tasas") if x[0] in U.YIELDS])
    return ok({"indicators": [{"id": k, "label": (meta.get(k) or {}).get("label") or A.MACRO_LABELS[k],
                               "unit": MACRO_UNITS[k], "values": [_r(v, 5) for v in (series[k] or [])][-24:],
                               **{f: (meta.get(k) or {}).get(f) for f in ("series", "provider", "last_period",
                                                                         "age_months", "stale")}}
                              for k in ("fed", "unemployment", "inflation")],
               "regime": regime, "fred": fred.available(), "curve": yield_curve(rates),
               "committee": {"regime": rep.get("macro"), "fragility": (rep.get("quantfin") or {}).get("fragility"),
                             "run_id": run["id"], "at": run["finished"]} if rep else None})


@router.get("/fund")
async def vx_fund(user: dict = Depends(require_auth)):
    uid = user["id"]
    st = engine.get_state(uid)
    training = T.latest(uid) or T.seed(uid, engine.required_cost(uid))
    return ok({"state": {k: st[k] for k in ("autopilot", "interval_min", "halted", "halt_reason", "desk_trust",
                                            "consecutive_losses", "last_cycle_at")},
               "mode": L.mode(uid), "run": engine.last_run(uid), "runs": engine.list_runs(uid)[:10],
               "training": training, "agents": T.agent_profiles(),
               "universe": [vars(a) for a in A.UNIVERSE], "desks": A.DESKS, "policy": vars(engine.POLICY)})


@router.get("/kb")
async def vx_kb(user: dict = Depends(require_auth)):
    return ok(knowledge_base())


_lab_cache: list | None = None


@router.get("/lab")
async def vx_lab(user: dict = Depends(require_auth)):
    """Catálogo de las 39 funciones de quantfin con el resultado de su ejemplo ya calculado."""
    global _lab_cache
    if _lab_cache is None:
        def build():
            out = []
            def short(v):
                return v[:8] + [f"… ({len(v)} valores)"] if isinstance(v, list) and len(v) > 8 else v
            for d in QC.catalog():
                if d["name"] in T.EXCLUDED_FUNCTIONS:  # decisión del usuario: sin optimización de Markowitz
                    continue
                try:
                    res = QC.call(d["name"], d["example"])["result"]
                except QC.QfArgError as e:
                    res = {"error": str(e)}
                full = sum(len(v) if isinstance(v, list) else 1 for v in d["example"].values()) <= 40
                out.append({**{k: d[k] for k in d if k != "example"}, "example": d["example"] if full else None,
                            "example_preview": {k: short(v) for k, v in d["example"].items()},
                            "example_result": {k: short(v) for k, v in res.items()}})
            return out
        _lab_cache = await asyncio.to_thread(build)
    return ok(_lab_cache)
