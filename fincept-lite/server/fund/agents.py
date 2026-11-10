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

import numpy as np

from quantfin import avanzados as qa  # librería quant-finance-research de Agustín Ortega
from quantfin import mercados as qm

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


SADF_CRITICAL = 1.5


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
    # Daniel & Moskowitz (2016): el momentum se desploma en "estados de pánico" (tras caídas
    # fuertes y con volatilidad disparada). En ese estado su peso se reduce a la mitad.
    panic = vol20 > 1.5 * vol60 and px / high - 1 < -0.20
    if panic:
        momentum *= 0.5
    reversion = 0.5 if r < 30 else -0.5 if r > 75 else 0.0
    score = max(-1.0, min(1.0, 0.45 * trend + 0.45 * momentum + 0.10 * reversion))
    # Phillips, Shi y Yu (2015) vía quantfin.sadf: régimen explosivo en el último año de log-precios.
    # Umbral aproximado 1.5 (el valor crítico exacto depende de n); detecta la burbuja, no cuándo revienta.
    sadf_stat = float(qa.sadf(np.log(np.asarray(closes[-252:], dtype=float))))
    return {"price": px, "sma50": s50, "sma200": s200, "mom_12_1": mom_12_1, "mom_3m": mom_3m, "rsi14": r,
            "sadf": sadf_stat, "bubble": sadf_stat > SADF_CRITICAL,
            "vol20": vol20, "vol60": vol60, "drawdown": px / high - 1, "trend": trend, "momentum": momentum,
            "reversion": reversion, "panic_state": panic, "score": score}


# ── playbook de estrategias (investigador cuant) ────────────────────────────

def _strat_trend(closes):  # precio sobre su media de 200 sesiones
    s = sma(closes, 200)
    return [None if v is None else int(c > v) for c, v in zip(closes, s)]


def _strat_cross(closes):  # cruce SMA 50/200
    f, s = sma(closes, 50), sma(closes, 200)
    return [None if a is None or b is None else int(a > b) for a, b in zip(f, s)]


def _strat_momentum(closes):  # momentum de 3 meses
    return [None if i < 63 else int(closes[i] > closes[i - 63]) for i in range(len(closes))]


def _strat_tsmom12(closes):  # Moskowitz, Ooi, Pedersen (2012): signo del rendimiento de 12 meses
    return [None if i < 252 else int(closes[i] > closes[i - 252]) for i in range(len(closes))]


def _strat_ema(closes):  # quantfin.senal_ema: cruce EMA 20/100 (Brock et al. 1992; Levine y Pedersen 2016)
    sig = qa.senal_ema(np.asarray(closes, dtype=float), 20, 100)
    return [None if i < 100 else int(v > 0) for i, v in enumerate(sig)]


def _strat_donchian(closes):  # quantfin.senal_donchian: ruptura del canal de 20 sesiones
    sig = qa.senal_donchian(np.asarray(closes, dtype=float), 20)
    return [None if i < 20 else int(v) for i, v in enumerate(sig)]


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
    "tsmom_12m": ("Time-series momentum 12 meses (Moskowitz et al. 2012)", _strat_tsmom12),
    "ema_20_100": ("Cruce de EMAs 20/100 (quantfin.senal_ema)", _strat_ema),
    "donchian_20": ("Ruptura de Donchian 20 (quantfin.senal_donchian)", _strat_donchian),
    "mean_reversion": ("Reversión a la media por RSI", _strat_reversion),
}


EULER_GAMMA = 0.5772156649015329


def _rets(equity: list[float]) -> list[float]:
    return [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity)) if equity[i - 1]]


def _moments(r: list[float]) -> tuple[float, float, float]:
    """Sharpe por periodo, asimetría y curtosis (no excesiva: normal = 3)."""
    if len(r) < 3:
        return 0.0, 0.0, 3.0
    mu, sd = statistics.fmean(r), statistics.pstdev(r)
    if sd == 0:
        return 0.0, 0.0, 3.0
    skew = statistics.fmean([((x - mu) / sd) ** 3 for x in r])
    kurt = statistics.fmean([((x - mu) / sd) ** 4 for x in r])
    return mu / sd, skew, kurt


def deflated_sharpe(chosen: list[float], trial_sharpes: list[float]) -> float:
    """Bailey & López de Prado (2014): P(Sharpe real > 0) corrigiendo por haber elegido el mejor de N
    intentos, la asimetría, la curtosis y la longitud de la muestra. Sharpe por periodo (no anualizado)."""
    sr, skew, kurt = _moments(chosen)
    n, t = len(trial_sharpes), len(chosen)
    if t < 3:
        return 0.0
    z = statistics.NormalDist().inv_cdf
    var = statistics.pvariance(trial_sharpes) if n > 1 else 0.0
    sr0 = math.sqrt(var) * ((1 - EULER_GAMMA) * z(1 - 1 / n) + EULER_GAMMA * z(1 - 1 / (n * math.e))) if n > 1 else 0.0
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if denom <= 0:
        return 0.0
    return statistics.NormalDist().cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom))


def select_strategy(candles: list[dict], holdout: float = 0.3, costs: CostModel = CostModel()) -> dict:
    """Elige la estrategia con SOLO el tramo in-sample y la juzga en el tramo reservado.

    'Aprender' sin hacer trampa: el ranking nunca ve los datos fuera de muestra.
    """
    closes = [c["c"] for c in candles]
    split = int(len(candles) * (1 - holdout))
    if split < 260 or len(candles) - split < 60:
        raise ValueError("not enough history to select a strategy")
    rows, is_returns = [], {}
    for key, (label, fn) in PLAYBOOK.items():
        sig = fn(closes)
        warm = next((i for i, v in enumerate(sig) if v is not None), len(sig))
        is_r = run_signals(candles, sig, min(warm, split - 2), split, costs=costs)
        oos_r = run_signals(candles, sig, split, costs=costs)
        is_m = perf_metrics([1.0] + [e / is_r["equity"][0] for e in is_r["equity"]])
        oos_m = perf_metrics([1.0] + [e / oos_r["equity"][0] for e in oos_r["equity"]])
        is_returns[key] = _rets(is_r["equity"])
        rows.append({"strategy": key, "label": label, "is_sharpe": is_m["sharpe"], "oos_sharpe": oos_m["sharpe"],
                     "oos_return": oos_m["total_return"], "current_signal": sig[-1]})
    best = max(rows, key=lambda r: r["is_sharpe"])  # selección in-sample
    trial_srs = [_moments(r)[0] for r in is_returns.values()]
    dsr = deflated_sharpe(is_returns[best["strategy"]], trial_srs)  # corrige por elegir 1 de N
    oos_ok, dsr_ok = best["oos_sharpe"] > 0, dsr >= 0.5
    return {**best, "deflated_sharpe": dsr, "oos_ok": oos_ok, "dsr_ok": dsr_ok, "validated": oos_ok and dsr_ok,
            "candidates": rows, "trust": 0.5 + 0.25 * oos_ok + 0.25 * dsr_ok}


# ── debate alcista / bajista (TradingAgents 2024; Huang et al. 2026) ────────

def debate(view: dict, regime: str) -> dict:
    """Argumentos a favor y en contra de cada activo a partir de señales INDEPENDIENTES.

    Huang et al. (2026) muestran que el valor del debate está en preservar el desacuerdo
    (la "convergencia complaciente" lo destruye). Aquí ningún agente revisa su señal a la
    vista de las demás: el desacuerdo se mide y se reporta, no se negocia.
    """
    s, st = view["signals"], view["strategy"]
    bull, bear = [], []
    (bull if s["trend"] > 0 else bear).append(
        f"precio {'sobre' if s['price'] > s['sma200'] else 'bajo'} su SMA200 (Faber 2007; Hurst et al. 2017)")
    (bull if s["mom_12_1"] > 0 else bear).append(f"momentum 12-1 de {s['mom_12_1']:+.1%} (Moskowitz et al. 2012)")
    if s["rsi14"] is not None and s["rsi14"] < 30:
        bull.append(f"sobreventa, RSI {s['rsi14']:.0f}")
    if s["rsi14"] is not None and s["rsi14"] > 75:
        bear.append(f"sobrecompra, RSI {s['rsi14']:.0f}")
    if s["panic_state"]:
        bear.append("estado de pánico: riesgo de desplome del momentum (Daniel y Moskowitz 2016)")
    if s["vol20"] > 1.3 * s["vol60"]:
        bear.append(f"volatilidad al alza ({s['vol20']:.0%} vs {s['vol60']:.0%})")
    if s["drawdown"] < -0.2:
        bear.append(f"a {s['drawdown']:.0%} de su máximo de 52 semanas")
    if s.get("bubble"):
        bear.append(f"régimen explosivo (SADF {s['sadf']:.2f} > {SADF_CRITICAL}): peso máximo a la mitad "
                    "(Phillips, Shi y Yu 2015)")
    if st["validated"]:
        (bull if st["current_signal"] else bear).append(
            f"estrategia {st['strategy']} validada (DSR {st['deflated_sharpe']:.2f}) dice {'dentro' if st['current_signal'] else 'fuera'}")
    else:
        bear.append(f"estrategia {st['strategy']} sin validar (DSR {st['deflated_sharpe']:.2f}, Sharpe OOS "
                    f"{st['oos_sharpe']:.2f}): posible sobreajuste (Bailey y López de Prado 2014)")
    tilt = REGIME_TILT[regime][view["desk"]]
    if tilt > 1:
        bull.append(f"el régimen {regime} favorece a esta mesa (×{tilt})")
    elif tilt < 1:
        bear.append(f"el régimen {regime} penaliza a esta mesa (×{tilt})")
    signs = [1 if s["trend"] > 0 else -1, 1 if s["momentum"] > 0 else -1, 1 if st["current_signal"] else -1]
    if s["reversion"]:
        signs.append(1 if s["reversion"] > 0 else -1)
    return {"bull": bull, "bear": bear, "disagreement": round(1 - abs(sum(signs)) / len(signs), 3),
            "verdict": "alcista" if len(bull) > len(bear) else "bajista" if len(bear) > len(bull) else "dividido"}


# ── estratega macro ─────────────────────────────────────────────────────────

def systemic_fragility(returns: np.ndarray, window: int = 63, step: int = 5) -> dict | None:
    """Kritzman, Li, Page y Rigobon (2011) vía quantfin.absorption_ratio: cuánta varianza absorbe el
    primer 20 % de componentes principales. Se compara el valor actual con su historia (z-score)."""
    if returns is None or returns.ndim != 2 or returns.shape[0] < window + 4 * step or returns.shape[1] < 3:
        return None
    series = [float(qa.absorption_ratio(returns[i - window:i])) for i in range(window, returns.shape[0] + 1, step)]
    hist, cur = series[:-1], series[-1]
    sd = statistics.pstdev(hist) if len(hist) > 1 else 0.0
    z = (cur - statistics.fmean(hist)) / sd if sd > 0 else 0.0
    return {"absorption_ratio": cur, "z": z, "fragile": z >= 1.0, "windows": len(series)}


def macro_regime(fed: list[float] | None, unemployment: list[float] | None, inflation: list[float] | None,
                 fragility: dict | None = None) -> dict:
    """Régimen a partir de series mensuales (más reciente al final). Sin datos → neutral."""
    notes, score = [], 0.0
    if fragility:
        notes.append(f"Absorption ratio {fragility['absorption_ratio']:.2f} (z {fragility['z']:+.1f})")
        if fragility["fragile"]:
            score -= 0.5
            notes.append("mercado frágil: correlaciones concentradas")
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


def covariance(returns: dict[str, list[float]]) -> tuple[list[str], np.ndarray, int] | None:
    """Covarianza diaria (alineada) reparada con quantfin.nearest_correlation (Higham 2002) si no es válida."""
    syms = [s for s, r in returns.items() if len(r) >= 60]
    if len(syms) < 2:
        return None
    t = min(len(returns[s]) for s in syms)
    m = np.array([returns[s][-t:] for s in syms], dtype=float).T
    cov = np.cov(m.T)
    sd = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    corr = cov / np.outer(sd, sd)
    if np.linalg.eigvalsh(corr).min() < -1e-10:  # matriz no válida (datos faltantes, ruido): repararla
        corr = qa.nearest_correlation(corr)
        cov = corr * np.outer(sd, sd)
    return syms, cov, t


def portfolio_vol(w: dict[str, float], cov_info, vols: dict[str, float]) -> tuple[float, str]:
    """Vol anual de la cartera. Con covarianza: sqrt(w'Σw) corregida por Pafka y Kondor (2003): el riesgo
    estimado es (1 − n/T) del real (quantfin.sesgo_optimizador). Sin ella: cota superior (correlación 1)."""
    if cov_info:
        syms, cov, t = cov_info
        if all(s in syms for s in w):
            idx = [syms.index(s) for s in w]
            vec = np.array(list(w.values()))
            est = float(np.sqrt(vec @ cov[np.ix_(idx, idx)] @ vec * 252))
            return est / qa.sesgo_optimizador(len(syms), t), "covarianza + Pafka-Kondor"
    return sum(w[s] * vols.get(s, 0.3) for s in w), "cota superior (correlación 1)"


def apply_risk(raw: dict[str, float], vols: dict[str, float], policy: RiskPolicy, cov_info=None,
               bubbles: set[str] | None = None) -> tuple[dict[str, float], list[dict]]:
    """Recorta pesos brutos a los límites. Devuelve (pesos, registro de cada control)."""
    checks: list[dict] = []
    w = {s: max(0.0, v) for s, v in raw.items() if s in BY_SYMBOL}  # allowlist y solo largos
    dropped = sorted(set(raw) - set(w) - {s for s, v in raw.items() if v <= 0})
    if dropped:
        checks.append({"check": "allowlist", "status": "blocked", "detail": f"fuera del universo: {dropped}"})
    for s in list(w):  # límite individual (a la mitad si el activo está en régimen explosivo)
        cap = BY_SYMBOL[s].max_weight * (0.5 if bubbles and s in bubbles else 1.0)
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
    port_vol, method = portfolio_vol(w, cov_info, vols)
    if port_vol > policy.target_vol:  # solo techo, nunca apalanca (DeMiguel et al. 2024)
        f = policy.target_vol / port_vol
        w = {s: v * f for s, v in w.items()}
        checks.append({"check": "objetivo de volatilidad", "status": "scaled",
                       "detail": f"vol {port_vol:.1%} ({method}) → {policy.target_vol:.0%} (×{f:.2f})"})
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

def risk_budget(cands: list[str], views: dict[str, dict], cov_info) -> tuple[dict[str, float], str]:
    """Reparto base del riesgo entre candidatos: paridad de riesgo con covarianza real
    (quantfin.risk_parity; Maillard et al. 2010) o, sin covarianza, inverso de la volatilidad."""
    if cov_info and len(cands) >= 2 and all(c in cov_info[0] for c in cands):
        syms, cov, _ = cov_info
        idx = [syms.index(c) for c in cands]
        w = qm.risk_parity(cov[np.ix_(idx, idx)])
        if np.all(np.isfinite(w)) and w.min() > 0:
            return dict(zip(cands, map(float, w))), "paridad de riesgo (covarianza)"
    inv = {c: 1 / max(views[c]["signals"]["vol60"], 0.04) for c in cands}
    tot = sum(inv.values())
    return {c: v / tot for c, v in inv.items()}, "inverso de la volatilidad"


def build_portfolio(views: dict[str, dict], regime: dict, sentiment: dict, desk_trust: dict[str, float],
                    cov_info=None) -> dict:
    """Pesos brutos ∝ convicción × confianza en la estrategia × confianza en la mesa × inclinación macro
    × presupuesto de riesgo (paridad de riesgo con covarianza si está disponible)."""
    tilt = REGIME_TILT[regime["regime"]]
    conv_by, cands = {}, []
    for s, v in views.items():
        a = BY_SYMBOL[s]
        conv = v["score"] + (sentiment["tilt"] if a.desk in ("equities", "crypto") else 0.0)
        if conv <= 0.05 or v["strategy"]["current_signal"] == 0 and v["strategy"]["validated"]:
            continue  # la estrategia validada dice "fuera": se respeta
        conv_by[s] = conv
        cands.append(s)
    if not cands:
        return {}
    budget, _ = risk_budget(cands, views, cov_info)
    raw = {s: conv_by[s] * views[s]["strategy"]["trust"] * desk_trust.get(BY_SYMBOL[s].desk, 1.0)
           * tilt[BY_SYMBOL[s].desk] * budget[s] for s in cands}
    tot = sum(raw.values())
    return {s: x / tot for s, x in raw.items()} if tot else {}


# ── trader (pesos → órdenes) ────────────────────────────────────────────────

MAX_IMPACT_BPS = 50.0


def plan_orders(target: dict[str, float], positions: dict[str, float], prices: dict[str, float], equity: float,
                policy: RiskPolicy, liquidity: dict[str, tuple[float, float]] | None = None
                ) -> tuple[list[dict], list[dict]]:
    """Ventas primero (liberan caja), luego compras; respeta banda y rotación máxima.

    `liquidity[s] = (vol_diaria, volumen_medio)`: con ello se estima el impacto con la ley de la raíz
    cuadrada (quantfin.impacto_raiz: Y·σ·√(Q/V)) y se recorta la orden si supera MAX_IMPACT_BPS."""
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
        impact = None
        if liquidity and s in liquidity and liquidity[s][1] > 0:
            sig_d, vol_avg = liquidity[s]
            impact = float(qa.impacto_raiz(sig_d, qty, vol_avg)) * 1e4
            if impact > MAX_IMPACT_BPS and sig_d > 0:
                q_max = vol_avg * (MAX_IMPACT_BPS / 1e4 / (0.7 * sig_d)) ** 2
                new_qty = round(q_max, 4) if frac else math.floor(q_max)
                checks.append({"check": f"impacto {s}", "status": "clamped",
                               "detail": f"{impact:.0f} pb > {MAX_IMPACT_BPS:.0f} pb: {qty} → {new_qty}"})
                qty, impact = new_qty, MAX_IMPACT_BPS
                if qty <= 0:
                    continue
        orders.append({"symbol": s, "side": "buy" if diff > 0 else "sell", "qty": qty, "price": px,
                       "notional": qty * px, "from_weight": round(cur_w, 4), "to_weight": round(target.get(s, 0.0), 4),
                       "impact_bps": None if impact is None else round(impact, 2)})
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
