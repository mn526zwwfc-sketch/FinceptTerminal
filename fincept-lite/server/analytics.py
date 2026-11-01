"""Analítica cuantitativa (subconjunto de /quantlib/* y del motor de backtesting).

El servidor real expone 590 rutas /quantlib/* (pricing, riesgo, curvas, ML...).
Aquí implementamos en Python puro las piezas más usadas para que la réplica
sea autocontenida: Black-Scholes (precio, griegas, volatilidad implícita),
métricas de riesgo (volatilidad, Sharpe, drawdown, VaR) y un backtest de cruce
de medias.
"""

from __future__ import annotations

import math
import statistics

SQRT2 = math.sqrt(2.0)


def ncdf(x: float) -> float:
    return 0.5 * math.erfc(-x / SQRT2)


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def _d1d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        raise ValueError("spot, strike, time and volatility must be > 0")
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    return d1, d1 - sigma * math.sqrt(T)


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call", q: float = 0.0) -> float:
    d1, d2 = _d1d2(S, K, T, r, sigma, q)
    if option_type == "call":
        return S * math.exp(-q * T) * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2)
    return K * math.exp(-r * T) * ncdf(-d2) - S * math.exp(-q * T) * ncdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, option_type: str = "call", q: float = 0.0) -> dict:
    d1, d2 = _d1d2(S, K, T, r, sigma, q)
    disc_q, disc_r = math.exp(-q * T), math.exp(-r * T)
    gamma = disc_q * npdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * disc_q * npdf(d1) * math.sqrt(T) / 100  # por 1 punto de vol
    if option_type == "call":
        delta = disc_q * ncdf(d1)
        theta = (-S * disc_q * npdf(d1) * sigma / (2 * math.sqrt(T)) - r * K * disc_r * ncdf(d2)
                 + q * S * disc_q * ncdf(d1)) / 365
        rho = K * T * disc_r * ncdf(d2) / 100
    else:
        delta = -disc_q * ncdf(-d1)
        theta = (-S * disc_q * npdf(d1) * sigma / (2 * math.sqrt(T)) + r * K * disc_r * ncdf(-d2)
                 - q * S * disc_q * ncdf(-d1)) / 365
        rho = -K * T * disc_r * ncdf(-d2) / 100
    return {"price": bs_price(S, K, T, r, sigma, option_type, q), "delta": delta, "gamma": gamma, "vega": vega,
            "theta": theta, "rho": rho, "d1": d1, "d2": d2}


def implied_vol(price: float, S: float, K: float, T: float, r: float, option_type: str = "call",
                q: float = 0.0) -> float:
    """Bisección robusta (el precio de BS es monótono en sigma)."""
    lo, hi = 1e-4, 5.0
    intrinsic = max(0.0, (S - K) if option_type == "call" else (K - S))
    if price < intrinsic * math.exp(-r * T) - 1e-9:
        raise ValueError("price below intrinsic value")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if bs_price(S, K, T, r, mid, option_type, q) > price:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-8:
            break
    return 0.5 * (lo + hi)


# ── riesgo ──────────────────────────────────────────────────────────────────

def returns(closes: list[float]) -> list[float]:
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]


def max_drawdown(closes: list[float]) -> float:
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    return mdd


def risk_metrics(closes: list[float], periods_per_year: int = 252, confidence: float = 0.95,
                 risk_free: float = 0.0) -> dict:
    if len(closes) < 10:
        raise ValueError("need at least 10 prices")
    rets = returns(closes)
    mu, sd = statistics.fmean(rets), statistics.pstdev(rets)
    ann_ret = (closes[-1] / closes[0]) ** (periods_per_year / len(rets)) - 1
    ann_vol = sd * math.sqrt(periods_per_year)
    srt = sorted(rets)
    idx = max(0, int((1 - confidence) * len(srt)) - 1)
    hist_var = -srt[idx]
    tail = srt[: idx + 1]
    z = statistics.NormalDist().inv_cdf(confidence)
    downside = [r for r in rets if r < 0]
    dsd = statistics.pstdev(downside) if len(downside) > 1 else 0.0
    return {
        "observations": len(rets),
        "total_return": closes[-1] / closes[0] - 1,
        "annualized_return": ann_ret,
        "annualized_volatility": ann_vol,
        "sharpe": ((mu * periods_per_year - risk_free) / ann_vol) if ann_vol else 0.0,
        "sortino": ((mu * periods_per_year - risk_free) / (dsd * math.sqrt(periods_per_year))) if dsd else 0.0,
        "max_drawdown": max_drawdown(closes),
        "var_historical": hist_var,
        "cvar_historical": -statistics.fmean(tail) if tail else hist_var,
        "var_parametric": -(mu - z * sd),
        "confidence": confidence,
        "best_day": max(rets),
        "worst_day": min(rets),
    }


def sma(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def backtest_sma_cross(candles: list[dict], fast: int = 20, slow: int = 50, initial_cash: float = 10_000.0,
                       fee_bps: float = 5.0) -> dict:
    """Largo cuando SMA rápida > SMA lenta; fuera en caso contrario. Ejecuta al cierre."""
    if fast >= slow:
        raise ValueError("fast must be < slow")
    closes = [c["c"] for c in candles]
    if len(closes) < slow + 5:
        raise ValueError(f"need at least {slow + 5} candles, got {len(closes)}")
    f, s = sma(closes, fast), sma(closes, slow)
    cash, units, trades, equity = initial_cash, 0.0, [], []
    fee = fee_bps / 10_000
    for i, c in enumerate(closes):
        if f[i] is not None and s[i] is not None:
            want_long = f[i] > s[i]
            if want_long and units == 0:
                units = cash * (1 - fee) / c
                cash = 0.0
                trades.append({"t": candles[i]["t"], "side": "buy", "price": c})
            elif not want_long and units > 0:
                cash = units * c * (1 - fee)
                units = 0.0
                trades.append({"t": candles[i]["t"], "side": "sell", "price": c})
        equity.append({"t": candles[i]["t"], "equity": cash + units * c})
    curve = [e["equity"] for e in equity]
    wins, closed = 0, 0
    for i in range(1, len(trades), 2):
        closed += 1
        wins += trades[i]["price"] > trades[i - 1]["price"]
    bh = initial_cash * closes[-1] / closes[slow - 1]
    m = risk_metrics(curve[slow - 1:])
    return {
        "strategy": f"SMA({fast}/{slow}) crossover",
        "initial_cash": initial_cash,
        "final_equity": curve[-1],
        "total_return": curve[-1] / initial_cash - 1,
        "buy_and_hold_return": bh / initial_cash - 1,
        "trades": len(trades),
        "win_rate": wins / closed if closed else None,
        "sharpe": m["sharpe"],
        "max_drawdown": m["max_drawdown"],
        "annualized_volatility": m["annualized_volatility"],
        "equity_curve": equity[::max(1, len(equity) // 400)],
        "trade_log": trades[-50:],
    }
