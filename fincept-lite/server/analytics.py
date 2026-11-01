"""Analítica cuantitativa (subconjunto de /quantlib/* y del motor de backtesting).

El servidor real expone 590 rutas /quantlib/* (pricing, riesgo, curvas, ML...).
Aquí implementamos en Python puro las piezas más usadas para que la réplica
sea autocontenida: Black-Scholes (precio, griegas, volatilidad implícita) y
métricas de riesgo (volatilidad, Sharpe, drawdown, VaR). El backtesting vive en
backtest.py.
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
