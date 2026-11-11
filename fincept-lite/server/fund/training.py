"""Entrenamiento de los agentes: forman sus estrategias con el código, las skills y la investigación.

Qué significa "entrenar" aquí (sin magia): no se ajustan redes neuronales ni se reentrena el
LLM. Cada agente recibe un perfil con sus skills, los papers de la base de conocimiento que le
corresponden y el código que los implementa; y el investigador cuant convierte esos papers en
estrategias concretas y las somete a un protocolo que no puede hacer trampa:

1. Biblioteca de estrategias sacada de la base de conocimiento: tendencia (Faber 2007; Hurst et al.
   2017), cruces de medias y EMAs (Brock et al. 1992; Levine y Pedersen 2016), Donchian, time-series
   momentum (Moskowitz et al. 2012), reversión RSI y reversión Ornstein-Uhlenbeck (Uhlenbeck y
   Ornstein 1930), cada una con y sin objetivo de volatilidad (Harvey et al. 2018; solo como techo,
   DeMiguel et al. 2024). Todas usan funciones de quantfin.
2. Por activo, 60 % de la historia para entrenar, 20 % para validar y 20 % de prueba final
   (skill backtesting-frameworks: datos a tiempo, costes, fuera de muestra). La posición decidida
   al cierre se ejecuta en la apertura siguiente y cada cambio paga 10 pb.
3. El mejor parámetro de cada familia se elige solo con el tramo de entrenamiento; el Deflated
   Sharpe (Bailey y López de Prado 2014) penaliza haber probado todas las configuraciones.
4. Las familias con Sharpe > 0 en validación forman un conjunto (hasta 3), ponderado por su
   Sharpe de validación. La prueba final mide el conjunto en datos que nadie ha usado para elegir.
5. Cada mesa aprende qué familias funcionan en su clase de activo; el libro queda guardado y el
   comité lo usa en los ciclos siguientes hasta que se vuelva a entrenar.
"""

from __future__ import annotations

import json
from pathlib import Path
import math
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
from quantfin import avanzados as qa

from ..db import get_db
from . import agents as A
from .research import knowledge_base
from .skills import APPLIED as SKILL_APPLIED
from .skills import load_skill

TRAIN_FRAC, VALID_FRAC = 0.6, 0.2
COST_BPS = 10.0  # comisión 5 + deslizamiento 5 por unidad de rotación
WARMUP = 260  # la ventana más larga (252) + margen
MIN_BARS = 700
MAX_MEMBERS = 3
VOL_TARGET = 0.15
BOOK_MAX_AGE_DAYS = 30


# ── biblioteca de estrategias (de la base de conocimiento) ──────────────────

def _sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def _b_trend(c, fit_end, p):
    s = _sma(c, p["n"])
    return np.where(np.isnan(s), np.nan, (c > s).astype(float)), {}


def _b_cross(c, fit_end, p):
    f, s = _sma(c, p["fast"]), _sma(c, p["slow"])
    return np.where(np.isnan(s), np.nan, (f > s).astype(float)), {}


def _b_ema(c, fit_end, p):
    sig = qa.senal_ema(c, p["fast"], p["slow"])
    out = (sig > 0).astype(float)
    out[: p["slow"]] = np.nan
    return out, {}


def _b_donchian(c, fit_end, p):
    out = qa.senal_donchian(c, p["n"]).astype(float)
    out[: p["n"]] = np.nan
    return out, {}


def _b_tsmom(c, fit_end, p):
    n, out = p["lookback"], np.full(len(c), np.nan)
    out[n:] = (c[n:] > c[:-n]).astype(float)
    return out, {}


def _b_rsi(c, fit_end, p):
    r, out, pos = A.rsi(list(c)), np.full(len(c), np.nan), 0.0
    for i, v in enumerate(r):
        if v is None:
            continue
        pos = 1.0 if v < p["buy"] else 0.0 if v > p["sell"] else pos
        out[i] = pos
    return out, {}


def _ou_spread(c):
    lc = np.log(c)
    return lc - qa.ema(lc, 50)


def _b_ou(c, fit_end, p, fitted=None):
    x = _ou_spread(c)
    if fitted is None:  # parámetros del proceso OU estimados SOLO con el tramo de entrenamiento
        seg = x[50:fit_end]
        if len(seg) < 100:
            return None, {}
        with np.errstate(all="ignore"):
            theta, mu, sigma, _ = qa.ajustar_ou(seg, dt=1 / 252)
        if not all(map(math.isfinite, (theta, mu, sigma))) or theta <= 0 or sigma <= 0:
            return None, {}
        fitted = {"theta": float(theta), "mu": float(mu), "sigma": float(sigma)}
    sd = fitted["sigma"] / math.sqrt(2 * fitted["theta"])
    z = (x - fitted["mu"]) / sd
    out, pos = np.full(len(c), np.nan), 0.0
    for i in range(50, len(c)):
        pos = 1.0 if z[i] < -p["entry"] else 0.0 if z[i] > 0 else pos
        out[i] = pos
    return out, fitted


@dataclass(frozen=True)
class Family:
    key: str
    label: str
    refs: tuple  # ids de la base de conocimiento
    functions: tuple  # funciones de quantfin que usa
    grid: tuple
    build: Callable
    style: str  # tendencia | reversión


FAMILIES = [
    Family("trend_sma", "Precio sobre su media móvil", ("faber2007", "hurst2017"), (), ({"n": 100}, {"n": 200}),
           _b_trend, "tendencia"),
    Family("sma_cross", "Cruce de medias simples", ("brock1992", "faber2007"), (),
           ({"fast": 20, "slow": 100}, {"fast": 50, "slow": 200}), _b_cross, "tendencia"),
    Family("ema_cross", "Cruce de EMAs", ("brock1992", "levine2016"), ("senal_ema", "ema"),
           ({"fast": 10, "slow": 50}, {"fast": 20, "slow": 100}, {"fast": 50, "slow": 200}), _b_ema, "tendencia"),
    Family("donchian", "Ruptura del canal de Donchian", ("brock1992", "qfr25"), ("senal_donchian",),
           ({"n": 20}, {"n": 55}), _b_donchian, "tendencia"),
    Family("tsmom", "Time-series momentum", ("moskowitz2012", "hurst2017"), ("tsmom",),
           ({"lookback": 63}, {"lookback": 126}, {"lookback": 252}), _b_tsmom, "tendencia"),
    Family("rsi_reversion", "Reversión por RSI (regla clásica, sin paper propio en la base)", (), (), ({"buy": 30, "sell": 55}, {"buy": 25, "sell": 50}),
           _b_rsi, "reversión"),
    Family("ou_reversion", "Reversión Ornstein-Uhlenbeck", ("uhlenbeck1930",), ("ajustar_ou", "zscore_pairs"),
           ({"entry": 1.0}, {"entry": 2.0}), _b_ou, "reversión"),
]
BY_FAMILY = {f.key: f for f in FAMILIES}
VT_REFS = ("harvey2018", "moreira2017", "demiguel2024")


def config_key(fam: str, params: dict, vt: bool) -> str:
    return fam + "(" + ",".join(f"{v}" for v in params.values()) + ")" + ("+vt" if vt else "")


def positions(fam: Family, closes: np.ndarray, fit_end: int, params: dict, vt: bool,
              fitted: dict | None = None) -> tuple[np.ndarray | None, dict]:
    """Exposición 0..1 decidida al cierre de cada sesión (NaN durante el calentamiento)."""
    if fam.key == "ou_reversion":
        pos, fitted = fam.build(closes, fit_end, params, fitted)
    else:
        pos, fitted = fam.build(closes, fit_end, params)
    if pos is None:
        return None, {}
    if vt:  # objetivo de volatilidad como techo: nunca apalanca (DeMiguel et al. 2024)
        r = np.diff(closes) / closes[:-1]
        lev = np.insert(qa.vol_target(r, VOL_TARGET, 20), 0, np.nan)
        lev[:21] = np.nan
        pos = pos * np.minimum(1.0, lev)
    return pos, fitted


# ── evaluación sin anticipación ─────────────────────────────────────────────

def strategy_returns(candles: list[dict], pos: np.ndarray, cost_bps: float = COST_BPS) -> np.ndarray:
    """Rendimiento de la sesión j = posición decidida al cierre j-1 × (apertura j+1 / apertura j − 1) − costes."""
    o = np.array([c.get("o") or c["c"] for c in candles], dtype=float)
    oo = np.append(o[1:] / o[:-1] - 1, 0.0)  # apertura→apertura; la última sesión no tiene siguiente
    p = np.nan_to_num(pos, nan=0.0)
    held = np.insert(p[:-1], 0, 0.0)
    turnover = np.abs(np.diff(np.insert(held, 0, 0.0)))
    return held * oo - turnover * cost_bps / 1e4


def metrics(r: np.ndarray) -> dict:
    if len(r) < 2:
        return {"sharpe": 0.0, "total_return": 0.0, "max_drawdown": 0.0, "days": len(r)}
    sd = float(r.std())
    eq = np.cumprod(1 + r)
    dd = float((eq / np.maximum.accumulate(eq) - 1).min())
    return {"sharpe": float(r.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0,
            "total_return": float(eq[-1] - 1), "max_drawdown": dd, "days": int(len(r))}


def _segments(n: int) -> tuple[int, int, int]:
    return WARMUP, int(n * TRAIN_FRAC), int(n * (TRAIN_FRAC + VALID_FRAC))


def train_asset(candles: list[dict], cost_bps: float = COST_BPS) -> dict:
    """Entrena el libro de estrategias de un activo. Ver el docstring del módulo."""
    n = len(candles)
    if n < MIN_BARS:
        return {"trained": False, "reason": f"solo {n} sesiones (mínimo {MIN_BARS})"}
    closes = np.array([c["c"] for c in candles], dtype=float)
    a, t1, t2 = _segments(n)
    trials = []
    for fam in FAMILIES:
        for params in fam.grid:
            for vt in (False, True):
                pos, fitted = positions(fam, closes, t1, params, vt)
                if pos is None:
                    continue
                r = strategy_returns(candles, pos, cost_bps)
                trials.append({"family": fam.key, "params": params, "vt": vt, "fitted": fitted, "pos": pos,
                               "train": r[a:t1], "valid": r[t1:t2], "test": r[t2:]})
    if not trials:
        return {"trained": False, "reason": "ninguna estrategia se pudo calcular"}
    per_period = [float(t["train"].mean() / t["train"].std()) if t["train"].std() > 0 else 0.0 for t in trials]
    families = []
    for fam in FAMILIES:  # selección SOLO con el tramo de entrenamiento
        cands = [t for t in trials if t["family"] == fam.key]
        if not cands:
            continue
        best = max(cands, key=lambda t: metrics(t["train"])["sharpe"])
        tm, vm = metrics(best["train"]), metrics(best["valid"])
        dsr = A.deflated_sharpe(best["train"].tolist(), per_period)
        families.append({"family": fam.key, "label": fam.label, "style": fam.style,
                         "config": config_key(fam.key, best["params"], best["vt"]), "params": best["params"],
                         "vt": best["vt"], "fitted": best["fitted"], "train_sharpe": tm["sharpe"],
                         "valid_sharpe": vm["sharpe"], "deflated_sharpe": dsr, "dsr_ok": dsr >= 0.5,
                         "_trial": best})
    members = sorted((f for f in families if f["valid_sharpe"] > 0 and f["train_sharpe"] > 0),
                     key=lambda f: -f["valid_sharpe"])[:MAX_MEMBERS]
    total = sum(f["valid_sharpe"] for f in members)
    for f in members:
        f["weight"] = f["valid_sharpe"] / total
    bh = metrics(strategy_returns(candles, np.ones(n), cost_bps)[t2:])
    out = {"trained": True, "bars": n, "trials": len(trials), "segments": {"train": [a, t1], "valid": [t1, t2],
                                                                            "test": [t2, n]},
           "families": [{k: v for k, v in f.items() if not k.startswith("_")} for f in families],
           "buy_hold_test": bh}
    if not members:
        out |= {"members": [], "validated": False, "edge": False,
                "verdict": "sin ventaja: ninguna familia gana en validación; el comité usa solo las señales"}
        return out
    ens_pos = sum(f["weight"] * np.nan_to_num(f["_trial"]["pos"], nan=0.0) for f in members)
    ens_r = strategy_returns(candles, ens_pos, cost_bps)
    test = metrics(ens_r[t2:])
    oos_ok, dsr_ok = test["sharpe"] > 0, any(f["dsr_ok"] for f in members)
    out |= {"members": [{k: f[k] for k in ("family", "label", "config", "params", "vt", "fitted", "weight",
                                            "train_sharpe", "valid_sharpe", "deflated_sharpe")} for f in members],
            "valid": metrics(ens_r[t1:t2]), "test": test, "exposure_now": float(ens_pos[-1]),
            "beats_buy_hold": test["sharpe"] > bh["sharpe"], "oos_ok": oos_ok, "dsr_ok": dsr_ok,
            "validated": oos_ok and dsr_ok, "edge": True,
            "verdict": ("validada" if oos_ok and dsr_ok else "positiva fuera de muestra pero sin superar el DSR"
                        if oos_ok else "falla en la prueba final")}
    return out


def apply_book(entry: dict, candles: list[dict]) -> dict | None:
    """Señal actual del conjunto entrenado, con el formato de agents.select_strategy."""
    if not entry or not entry.get("trained") or not entry.get("members"):
        return None
    closes = np.array([c["c"] for c in candles], dtype=float)
    exposure = 0.0
    for m in entry["members"]:
        fam = BY_FAMILY[m["family"]]
        pos, _ = positions(fam, closes, len(closes), m["params"], m["vt"], m.get("fitted") or None)
        if pos is None:
            return None
        exposure += m["weight"] * float(np.nan_to_num(pos[-1], nan=0.0))
    validated = bool(entry["validated"])
    return {"strategy": "entrenada:" + "+".join(m["config"] for m in entry["members"]),
            "label": " + ".join(m["label"] for m in entry["members"]),
            "is_sharpe": max(m["train_sharpe"] for m in entry["members"]),
            "oos_sharpe": entry["test"]["sharpe"], "oos_return": entry["test"]["total_return"],
            "current_signal": int(exposure >= 0.5), "exposure": exposure,
            "deflated_sharpe": max(m["deflated_sharpe"] for m in entry["members"]),
            "oos_ok": entry["oos_ok"], "dsr_ok": entry["dsr_ok"], "validated": validated,
            "candidates": [{"strategy": f["config"], "is_sharpe": f["train_sharpe"], "oos_sharpe": f["valid_sharpe"]}
                           for f in entry["families"]],
            "trust": 0.5 + 0.25 * entry["oos_ok"] + 0.25 * entry["dsr_ok"], "trained": True}


# ── perfiles de los agentes ─────────────────────────────────────────────────

AGENTS = [
    {"id": "macro", "name": "Estratega macro", "skills": ["macro-rates-monitor", "economic-calendar-fetcher"],
     "topics": ["Burbujas, regímenes y riesgo sistémico", "Renta fija"], "tags": ["Estratega macro"],
     "code": ["agents.macro_regime", "agents.systemic_fragility"]},
    {"id": "sentiment", "name": "Analista de sentimiento", "skills": ["llm-trading-agent-security"],
     "topics": ["Eficiencia y estructura del mercado"], "tags": ["Analista de sentimiento", "Seguridad"],
     "code": ["agents.news_sentiment", "agents.sanitize_headline"]},
    {"id": "analysts", "name": "Analistas por mesa", "skills": ["equity-research", "yfinance-data", "option-vol-analysis"],
     "topics": ["Acciones", "Materias primas", "Divisas", "Cripto y DeFi", "Mercados de predicción",
                "Volatilidad, derivados y crédito"], "tags": ["Analistas por mesa", "Analistas / gestor de riesgos"],
     "code": ["agents.asset_signals", "agents.debate"]},
    {"id": "quant", "name": "Investigador cuant", "skills": ["backtesting-frameworks"],
     "topics": ["Tendencia y señales", "Anomalías y sesgos de backtest", "Validación de backtests y machine learning"],
     "tags": ["Investigador cuant", "Laboratorio quant"],
     "code": ["training.train_asset", "training.apply_book", "agents.deflated_sharpe"]},
    {"id": "cio", "name": "CIO", "skills": [], "topics": [], "tags": ["CIO", "CIO / diseño", "Arquitectura", "Memoria"],
     "code": ["agents.build_portfolio", "agents.risk_budget", "engine._llm_memo"]},
    {"id": "risk", "name": "Gestor de riesgos", "skills": ["backtesting-frameworks", "option-vol-analysis",
                                                           "llm-trading-agent-security"],
     "topics": ["Portafolios y limpieza de covarianza", "Riesgo y portafolio", "Burbujas, regímenes y riesgo sistémico"],
     "tags": ["Gestor de riesgos", "Analistas / gestor de riesgos"],
     "code": ["agents.apply_risk", "agents.covariance", "agents.portfolio_vol", "agents.circuit_breaker"]},
    {"id": "trader", "name": "Trader", "skills": ["llm-trading-agent-security"], "topics": ["Ejecución y microestructura"],
     "tags": ["Trader"], "code": ["agents.plan_orders"]},
]
PLATFORM_SKILLS = ["fastapi", "mcp-builder"]  # construyen la terminal, no deciden inversiones


# Decisión del usuario: el equipo no usa la optimización media-varianza de Markowitz. Las funciones siguen
# en la librería quantfin (no se toca), pero ningún agente las recibe ni recibe su paper.
EXCLUDED_FUNCTIONS = {"min_varianza", "mejora_sharpe"}


def excluded(entry: dict) -> bool:
    fns = set(entry.get("functions") or [])
    return bool(fns) and fns <= EXCLUDED_FUNCTIONS


def _belongs(entry: dict, agent: dict) -> bool:
    if excluded(entry):
        return False
    topic = entry.get("topic") or ""
    return (topic in agent["topics"] or (entry.get("agent") or "") in agent["tags"]
            or any(topic == f"Fondo · {t}" for t in agent["tags"]))


def agent_profiles() -> list[dict]:
    """Lo que sabe cada agente: skills (con sus reglas), papers y código que los aplica."""
    kb = knowledge_base()
    out = []
    for ag in AGENTS:
        papers = [e for e in kb if _belongs(e, ag)]
        out.append({"id": ag["id"], "name": ag["name"], "skills": [load_skill(s) for s in ag["skills"]],
                    "papers": [{"id": e["id"], "year": e["year"], "title": e["title"], "finding": e["finding"],
                                "functions": e["functions"]} for e in papers],
                    "functions": sorted({f for e in papers for f in e["functions"]}), "code": ag["code"]})
    return out


def _desk_doctrine(book: dict) -> dict:
    """Qué familias funcionan en cada mesa (media del Sharpe de validación de su mejor configuración)."""
    out = {}
    for desk in A.DESKS:
        rows = [b for s, b in book.items() if A.BY_SYMBOL[s].desk == desk and b.get("trained")]
        if not rows:
            continue
        fam = {}
        for b in rows:
            for f in b["families"]:
                fam.setdefault(f["family"], []).append(f["valid_sharpe"])
        ranked = sorted(((k, sum(v) / len(v)) for k, v in fam.items()), key=lambda kv: -kv[1])
        works = [k for k, v in ranked if v > 0]
        out[desk] = {"assets": len(rows), "validated": sum(b.get("validated", False) for b in rows),
                     "ranking": [{"family": k, "avg_valid_sharpe": v} for k, v in ranked],
                     "lesson": (f"funcionan {', '.join(works[:3])}" if works else "ninguna familia gana en validación")
                     + (f"; no funcionan {', '.join(k for k, v in ranked if v <= 0)}"
                        if any(v <= 0 for _, v in ranked) else "")}
    return out


def train_all(hist: dict[str, list[dict]], sources: dict[str, str] | None = None,
              cost_bps: float = COST_BPS) -> dict:
    """`sources[s]` = proveedor de los datos ('yahoo' real, 'sim' simulado): el modo real solo usa
    estrategias entrenadas con datos reales."""
    t0, sources = time.time(), sources or {}
    book = {s: train_asset(c, cost_bps) | {"desk": A.BY_SYMBOL[s].desk, "data_source": sources.get(s, "desconocida"),
                                           "cost_bps": cost_bps}
            for s, c in hist.items() if s in A.BY_SYMBOL}
    trained = {s: b for s, b in book.items() if b.get("trained")}
    kb = {e["id"]: e for e in knowledge_base()}
    used = sorted({r for b in trained.values() for m in b.get("members", [])
                   for r in BY_FAMILY[m["family"]].refs + (VT_REFS if m["vt"] else ())} & set(kb))
    return {
        "created": time.time(), "seconds": round(time.time() - t0, 2),
        "protocol": {"train": TRAIN_FRAC, "valid": VALID_FRAC, "test": round(1 - TRAIN_FRAC - VALID_FRAC, 2),
                     "cost_bps": cost_bps, "execution": "apertura siguiente", "max_members": MAX_MEMBERS,
                     "families": [{"family": f.key, "label": f.label, "style": f.style, "refs": list(f.refs),
                                   "functions": list(f.functions), "configs": len(f.grid) * 2} for f in FAMILIES],
                     "vol_target_refs": list(VT_REFS)},
        "book": book, "desks": _desk_doctrine(book),
        "data_sources": sorted(set(sources.values())) or ["desconocida"],
        "summary": {"assets": len(book), "trained": len(trained),
                    "with_edge": sum(b.get("edge", False) for b in trained.values()),
                    "validated": sum(b.get("validated", False) for b in trained.values()),
                    "beats_buy_hold": sum(b.get("beats_buy_hold", False) for b in trained.values())},
        "papers_used": [{"id": i, "title": kb[i]["title"], "year": kb[i]["year"]} for i in used],
        "skills_applied": {k: v for k, v in SKILL_APPLIED.items() if k not in PLATFORM_SKILLS},
    }


# ── persistencia ────────────────────────────────────────────────────────────

def save(uid: int, result: dict) -> int:
    cur = get_db().execute("INSERT INTO fund_training(user_id, created, report) VALUES (?,?,?)",
                           (uid, result["created"], json.dumps(result, default=str)))
    return cur.lastrowid


def latest(uid: int) -> dict | None:
    row = get_db().one("SELECT id, created, report FROM fund_training WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,))
    if not row:
        return None
    rep = json.loads(row["report"])
    rep["id"], rep["age_days"] = row["id"], (time.time() - row["created"]) / 86400
    rep["stale"] = rep["age_days"] > BOOK_MAX_AGE_DAYS
    return rep


SEED_DIR = Path(__file__).resolve().parents[2] / "agentes"


def seed(uid: int, min_cost_bps: float) -> dict | None:
    """Si el usuario aún no ha entrenado, carga los agentes ya entrenados de `agentes/` (los genera
    server.fund.export_agents con datos reales). Usa el libro con el menor coste que cubra el necesario,
    y solo si tiene menos de BOOK_MAX_AGE_DAYS días: después, el comité reentrena con datos frescos."""
    best = None
    for path in sorted(SEED_DIR.glob("entrenamiento_*pb.json")):
        try:
            res = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cost = res.get("protocol", {}).get("cost_bps", 0)
        fresh = (time.time() - res.get("created", 0)) / 86400 <= BOOK_MAX_AGE_DAYS
        if fresh and cost >= min_cost_bps - 1e-6 and (best is None or cost < best["protocol"]["cost_bps"]):
            best = res
    if best is None:
        return None
    save(uid, best | {"trigger": "precargado"})
    return latest(uid)


def brief(training: dict | None) -> dict | None:
    """Resumen compacto para el acta del CIO (y para el LLM, que solo explica)."""
    if not training:
        return None
    return {"trained_at": training["created"], "summary": training["summary"],
            "desks": {d: v["lesson"] for d, v in training["desks"].items()},
            "papers": [f"{p['title'][:60]} ({p['year']})" for p in training["papers_used"]][:8]}
