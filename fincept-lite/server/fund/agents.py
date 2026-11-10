"""Equipo de agentes del fondo (todo determinista; el LLM solo redacta, nunca decide).

Cada agente es una función pura sobre datos de mercado: así sus decisiones se
pueden testear, auditar y reproducir. La skill llm-trading-agent-security exige
que los límites y la ejecución no dependan de la salida de un modelo, por eso el
gestor de riesgos y el trader son código con reglas fijas.

Origen de cada pieza:
* Analistas por mesa ............ equity-research / yfinance-data (técnico + riesgo + noticias)
* Estratega macro ............... macro-rates-monitor (tipos, paro, inflación → régimen)
* Investigador cuant ............ backtesting-frameworks (selección in-sample, validación OOS)
* Gestor de riesgos / trader .... llm-trading-agent-security (límites, cortacircuitos, allowlist)
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field

from ..backtest import CostModel, perf_metrics, run_signals, sma

# ── universo global multi-activo (instrumentos negociables en la cuenta paper) ─

@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    desk: str
    max_weight: float  # límite individual del gestor de riesgos


UNIVERSE: list[Asset] = [
    Asset("SPY", "S&P 500 (EE. UU.)", "equities", 0.15), Asset("QQQ", "Nasdaq 100 (EE. UU.)", "equities", 0.12),
    Asset("VGK", "Europa", "equities", 0.10), Asset("EWJ", "Japón", "equities", 0.08),
    Asset("EEM", "Emergentes", "equities", 0.08), Asset("EWP", "España", "equities", 0.06),
    Asset("TLT", "Bonos EE. UU. 20+ años", "rates", 0.15), Asset("IEF", "Bonos EE. UU. 7-10 años", "rates", 0.15),
    Asset("GLD", "Oro", "commodities", 0.10), Asset("SLV", "Plata", "commodities", 0.05),
    Asset("USO", "Petróleo WTI", "commodities", 0.05),
    Asset("UUP", "Dólar (índice)", "fx", 0.08), Asset("FXE", "Euro", "fx", 0.06), Asset("FXY", "Yen", "fx", 0.06),
    Asset("BTC-USD", "Bitcoin", "crypto", 0.05), Asset("ETH-USD", "Ethereum", "crypto", 0.03),
    Asset("SOL-USD", "Solana", "crypto", 0.02),
]
BY_SYMBOL = {a.symbol: a for a in UNIVERSE}
DESKS = {
    "equities": "Renta variable global", "rates": "Renta fija", "commodities": "Materias primas",
    "fx": "Divisas", "crypto": "Cripto",
}
DESK_MAX = {"equities": 0.50, "rates": 0.40, "commodities": 0.20, "fx": 0.15, "crypto": 0.10}


# ── señales técnicas (analistas) ────────────────────────────────────────────

def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    for i in range(n, len(closes)):
        gains = sum(max(0.0, closes[j] - closes[j - 1]) for j in range(i - n + 1, i + 1))
        losses = sum(max(0.0, closes[j - 1] - closes[j]) for j in range(i - n + 1, i + 1))
        out[i] = 100.0 if losses == 0 else 100 - 100 / (1 + gains / losses)
    return out


def realized_vol(closes: list[float], n: int) -> float:
    rets = [closes[i] / closes[i - 1] - 1 for i in range(max(1, len(closes) - n), len(closes))]
    return statistics.pstdev(rets) * math.sqrt(252) if len(rets) > 2 else 0.0


def asset_signals(closes: list[float]) -> dict:
    """Foto técnica de un activo: tendencia, momentum, reversión, volatilidad."""
    if len(closes) < 210:
        raise ValueError("need >= 210 daily closes")
    s50, s200 = sma(closes, 50)[-1], sma(closes, 200)[-1]
    px = closes[-1]
    mom_12_1 = closes[-22] / closes[-253] - 1 if len(closes) > 253 else closes[-22] / closes[0] - 1
    mom_3m = px / closes[-64] - 1
    r = rsi(closes)[-1]
    vol20, vol60 = realized_vol(closes, 20), realized_vol(closes, 60)
    high = max(closes[-252:])
    trend = (1 if px > s200 else -1) * 0.5 + (0.5 if s50 > s200 else -0.5)
    momentum = math.tanh((0.6 * mom_12_1 + 0.4 * mom_3m) / max(vol60, 0.05))
    reversion = 0.5 if r < 30 else -0.5 if r > 75 else 0.0
    score = max(-1.0, min(1.0, 0.45 * trend + 0.45 * momentum + 0.10 * reversion))
    return {"price": px, "sma50": s50, "sma200": s200, "mom_12_1": mom_12_1, "mom_3m": mom_3m, "rsi14": r,
            "vol20": vol20, "vol60": vol60, "drawdown": px / high - 1, "trend": trend, "momentum": momentum,
            "reversion": reversion, "score": score}


# ── playbook de estrategias (investigador cuant) ────────────────────────────

def _strat_trend(closes):  # precio sobre su media de 200 sesiones
    s = sma(closes, 200)
    return [None if v is None else int(c > v) for c, v in zip(closes, s)]


def _strat_cross(closes):  # cruce SMA 50/200
    f, s = sma(closes, 50), sma(closes, 200)
    return [None if a is None or b is None else int(a > b) for a, b in zip(f, s)]


def _strat_momentum(closes):  # momentum de 3 meses
    return [None if i < 63 else int(closes[i] > closes[i - 63]) for i in range(len(closes))]


def _strat_reversion(closes):  # compra sobreventa (RSI<30), sale al normalizar (RSI>55)
    r, out, pos = rsi(closes), [], 0
    for v in r:
        if v is None:
            out.append(None)
            continue
        pos = 1 if v < 30 else 0 if v > 55 else pos
        out.append(pos)
    return out


PLAYBOOK = {
    "trend_200d": ("Tendencia: largo si precio > SMA200", _strat_trend),
    "sma_50_200": ("Cruce dorado SMA50/SMA200", _strat_cross),
    "momentum_3m": ("Momentum de series temporales a 3 meses", _strat_momentum),
    "mean_reversion": ("Reversión a la media por RSI", _strat_reversion),
}


def select_strategy(candles: list[dict], holdout: float = 0.3, costs: CostModel = CostModel()) -> dict:
    """Elige la estrategia con SOLO el tramo in-sample y la juzga en el tramo reservado.

    'Aprender' sin hacer trampa: el ranking nunca ve los datos fuera de muestra.
    """
    closes = [c["c"] for c in candles]
    split = int(len(candles) * (1 - holdout))
    if split < 260 or len(candles) - split < 60:
        raise ValueError("not enough history to select a strategy")
    rows = []
    for key, (label, fn) in PLAYBOOK.items():
        sig = fn(closes)
        warm = next((i for i, v in enumerate(sig) if v is not None), len(sig))
        is_r = run_signals(candles, sig, warm, split, costs=costs)
        oos_r = run_signals(candles, sig, split, costs=costs)
        is_m = perf_metrics([1.0] + [e / is_r["equity"][0] for e in is_r["equity"]])
        oos_m = perf_metrics([1.0] + [e / oos_r["equity"][0] for e in oos_r["equity"]])
        rows.append({"strategy": key, "label": label, "is_sharpe": is_m["sharpe"], "oos_sharpe": oos_m["sharpe"],
                     "oos_return": oos_m["total_return"], "current_signal": sig[-1]})
    best = max(rows, key=lambda r: r["is_sharpe"])  # selección in-sample
    validated = best["oos_sharpe"] > 0  # validación fuera de muestra
    return {**best, "validated": validated, "candidates": rows,
            "trust": 1.0 if validated else 0.5}


# ── estratega macro ─────────────────────────────────────────────────────────

def macro_regime(fed: list[float] | None, unemployment: list[float] | None, inflation: list[float] | None) -> dict:
    """Régimen a partir de series mensuales (más reciente al final). Sin datos → neutral."""
    notes, score = [], 0.0
    if unemployment and len(unemployment) >= 13:
        sahm = statistics.fmean(unemployment[-3:]) - min(unemployment[-13:-1])
        notes.append(f"Regla de Sahm {sahm:+.2f} pp")
        if sahm >= 0.5:
            score -= 1.0
            notes.append("señal de recesión")
        elif sahm <= 0.2:
            score += 0.5
    if fed and len(fed) >= 7:
        chg = fed[-1] - fed[-7]
        notes.append(f"Fed funds {fed[-1]:.2f}% ({chg:+.2f} pp en 6 meses)")
        score += 0.5 if chg < -0.1 else -0.5 if chg > 0.25 else 0.0
    if inflation and inflation[-1] is not None:
        notes.append(f"Inflación zona euro {inflation[-1]:.1f}%")
        score -= 0.5 if inflation[-1] > 4 else 0.0
    if not notes:
        return {"regime": "neutral", "score": 0.0, "notes": ["Sin datos macro (modo sim o red no disponible)"],
                "rates_direction": "flat"}
    regime = "risk_on" if score >= 0.5 else "risk_off" if score <= -0.5 else "neutral"
    rates = "falling" if fed and len(fed) >= 7 and fed[-1] < fed[-7] - 0.1 else \
        "rising" if fed and len(fed) >= 7 and fed[-1] > fed[-7] + 0.25 else "flat"
    return {"regime": regime, "score": score, "notes": notes, "rates_direction": rates}


REGIME_TILT = {  # multiplicador por mesa según el régimen
    "risk_on": {"equities": 1.2, "crypto": 1.2, "commodities": 1.0, "fx": 0.9, "rates": 0.8},
    "neutral": {"equities": 1.0, "crypto": 1.0, "commodities": 1.0, "fx": 1.0, "rates": 1.0},
    "risk_off": {"equities": 0.6, "crypto": 0.4, "commodities": 1.1, "fx": 1.1, "rates": 1.3},
}


# ── sentimiento (dato externo NO confiable) ─────────────────────────────────

INJECTION_PATTERNS = [r"ignore (previous|all|the above) instructions", r"new (task|directive|instruction)",
                      r"system prompt", r"(buy|sell|transfer|send) .{0,40}(now|immediately)", r"you are now",
                      r"disregard .{0,30}(rules|limits)"]


def sanitize_headline(text: str) -> str | None:
    """Devuelve el titular limpio o None si parece un intento de inyección (se descarta y se audita)."""
    t = re.sub(r"\s+", " ", text or "").strip()[:200]
    if any(re.search(p, t, re.IGNORECASE) for p in INJECTION_PATTERNS):
        return None
    return t


def news_sentiment(items: list[dict]) -> dict:
    kept, dropped = [], 0
    for it in items:
        clean = sanitize_headline(it.get("title", ""))
        if clean is None:
            dropped += 1
        else:
            kept.append({"title": clean, "score": float(it.get("sentiment_score", 0.0))})
    avg = statistics.fmean([k["score"] for k in kept]) if kept else 0.0
    return {"headlines": len(kept), "dropped_suspicious": dropped, "avg_sentiment": avg,
            "tilt": max(-0.1, min(0.1, avg * 0.2)), "sample": [k["title"] for k in kept[:5]]}


# ── gestor de riesgos (reglas fijas, con veto) ──────────────────────────────

@dataclass
class RiskPolicy:
    target_vol: float = 0.10  # volatilidad anual objetivo de la cartera
    min_cash: float = 0.05
    max_gross: float = 1.0  # sin apalancamiento
    max_drawdown_halt: float = 0.10  # cortacircuitos: caída desde máximos
    max_consecutive_losses: int = 3
    max_turnover: float = 0.30  # % de equity negociado por ciclo
    min_trade: float = 0.02  # banda de rebalanceo
    desk_max: dict = field(default_factory=lambda: dict(DESK_MAX))


def apply_risk(raw: dict[str, float], vols: dict[str, float], policy: RiskPolicy) -> tuple[dict[str, float], list[dict]]:
    """Recorta pesos brutos a los límites. Devuelve (pesos, registro de cada control)."""
    checks: list[dict] = []
    w = {s: max(0.0, v) for s, v in raw.items() if s in BY_SYMBOL}  # allowlist y solo largos
    dropped = sorted(set(raw) - set(w) - {s for s, v in raw.items() if v <= 0})
    if dropped:
        checks.append({"check": "allowlist", "status": "blocked", "detail": f"fuera del universo: {dropped}"})
    for s in list(w):  # límite individual
        cap = BY_SYMBOL[s].max_weight
        if w[s] > cap:
            checks.append({"check": f"límite {s}", "status": "clamped", "detail": f"{w[s]:.1%} → {cap:.0%}"})
            w[s] = cap
    for desk, cap in policy.desk_max.items():  # límite por mesa
        tot = sum(v for s, v in w.items() if BY_SYMBOL[s].desk == desk)
        if tot > cap:
            f = cap / tot
            for s in w:
                if BY_SYMBOL[s].desk == desk:
                    w[s] *= f
            checks.append({"check": f"mesa {desk}", "status": "clamped", "detail": f"{tot:.1%} → {cap:.0%}"})
    port_vol = sum(w[s] * vols.get(s, 0.3) for s in w)  # cota superior (correlación 1)
    if port_vol > policy.target_vol:
        f = policy.target_vol / port_vol
        w = {s: v * f for s, v in w.items()}
        checks.append({"check": "objetivo de volatilidad", "status": "scaled",
                       "detail": f"vol ≤ {port_vol:.1%} → {policy.target_vol:.0%} (×{f:.2f})"})
    gross_cap = min(policy.max_gross, 1 - policy.min_cash)
    gross = sum(w.values())
    if gross > gross_cap:
        w = {s: v * gross_cap / gross for s, v in w.items()}
        checks.append({"check": "exposición bruta / caja mínima", "status": "scaled",
                       "detail": f"{gross:.1%} → {gross_cap:.0%}"})
    if not checks:
        checks.append({"check": "límites", "status": "ok", "detail": "sin ajustes"})
    return {s: round(v, 4) for s, v in w.items() if v >= 0.005}, checks


def circuit_breaker(equity: float, peak: float, consecutive_losses: int, policy: RiskPolicy) -> dict:
    dd = equity / peak - 1 if peak > 0 else 0.0
    if peak <= 0 or equity <= 0:
        return {"halted": True, "reason": "estado inválido de la cuenta", "drawdown": dd}
    if dd <= -policy.max_drawdown_halt:
        return {"halted": True, "reason": f"drawdown {dd:.1%} supera el límite de {policy.max_drawdown_halt:.0%}",
                "drawdown": dd}
    if consecutive_losses >= policy.max_consecutive_losses:
        return {"halted": True, "reason": f"{consecutive_losses} ciclos seguidos en pérdidas", "drawdown": dd}
    return {"halted": False, "reason": None, "drawdown": dd}


# ── director de inversiones (combina las opiniones) ─────────────────────────

def build_portfolio(views: dict[str, dict], regime: dict, sentiment: dict, desk_trust: dict[str, float]) -> dict:
    """Pesos brutos ∝ convicción × confianza en la estrategia × confianza en la mesa × inclinación macro,
    con paridad de riesgo (inverso de la volatilidad)."""
    tilt = REGIME_TILT[regime["regime"]]
    raw = {}
    for s, v in views.items():
        a = BY_SYMBOL[s]
        conv = v["score"] + (sentiment["tilt"] if a.desk in ("equities", "crypto") else 0.0)
        if conv <= 0.05 or v["strategy"]["current_signal"] == 0 and v["strategy"]["validated"]:
            continue  # la estrategia validada dice "fuera": se respeta
        inv_vol = 1 / max(v["signals"]["vol60"], 0.04)
        raw[s] = conv * v["strategy"]["trust"] * desk_trust.get(a.desk, 1.0) * tilt[a.desk] * inv_vol
    tot = sum(raw.values())
    return {s: x / tot for s, x in raw.items()} if tot else {}


# ── trader (pesos → órdenes) ────────────────────────────────────────────────

def plan_orders(target: dict[str, float], positions: dict[str, float], prices: dict[str, float], equity: float,
                policy: RiskPolicy) -> tuple[list[dict], list[dict]]:
    """Ventas primero (liberan caja), luego compras; respeta banda y rotación máxima."""
    orders, checks = [], []
    symbols = sorted(set(target) | {s for s in positions if s in BY_SYMBOL})
    for s in symbols:
        px = prices.get(s)
        if not px or px <= 0:
            checks.append({"check": f"precio {s}", "status": "blocked", "detail": "sin precio válido"})
            continue
        cur_w = positions.get(s, 0.0) * px / equity
        diff = target.get(s, 0.0) - cur_w
        if abs(diff) < policy.min_trade and not (target.get(s, 0.0) == 0 and positions.get(s, 0.0) > 0):
            continue
        frac = BY_SYMBOL[s].desk == "crypto"
        qty = abs(diff) * equity / px
        qty = round(qty, 4) if frac else math.floor(qty)
        if diff < 0:
            qty = min(qty if qty else positions.get(s, 0.0), positions.get(s, 0.0))
        if qty <= 0:
            continue
        orders.append({"symbol": s, "side": "buy" if diff > 0 else "sell", "qty": qty, "price": px,
                       "notional": qty * px, "from_weight": round(cur_w, 4), "to_weight": round(target.get(s, 0.0), 4)})
    # Ventas primero; las compras por convicción (peso objetivo) para que el límite de rotación
    # aplace las posiciones pequeñas, nunca las de mayor convicción.
    orders.sort(key=lambda o: (o["side"] != "sell", -o["to_weight"]))
    budget, kept = policy.max_turnover * equity, []
    for o in orders:
        if o["side"] == "buy" and o["notional"] > budget:
            checks.append({"check": f"rotación {o['symbol']}", "status": "deferred",
                           "detail": f"{o['notional']:,.0f} supera el presupuesto restante {budget:,.0f}"})
            continue
        budget -= o["notional"]
        kept.append(o)
    return kept, checks


def update_desk_trust(trust: dict[str, float], last_views: dict[str, dict], prices_then: dict[str, float],
                      prices_now: dict[str, float]) -> tuple[dict[str, float], dict[str, dict]]:
    """Aprendizaje: cada mesa gana o pierde confianza según si sus opiniones acertaron la dirección."""
    hits: dict[str, list[int]] = {}
    for s, v in last_views.items():
        if s in BY_SYMBOL and prices_then.get(s) and prices_now.get(s):
            ret = prices_now[s] / prices_then[s] - 1
            if abs(v.get("score", 0)) > 0.05 and abs(ret) > 1e-6:
                hits.setdefault(BY_SYMBOL[s].desk, []).append(int((v["score"] > 0) == (ret > 0)))
    new, report = dict(trust), {}
    for desk, hs in hits.items():
        rate = sum(hs) / len(hs)
        old = trust.get(desk, 1.0)
        new[desk] = round(min(1.5, max(0.5, 0.8 * old + 0.2 * (0.5 + rate))), 4)  # EMA acotada
        report[desk] = {"calls": len(hs), "hit_rate": rate, "trust_before": old, "trust_after": new[desk]}
    return new, report
