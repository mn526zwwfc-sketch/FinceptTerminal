"""Orquestador del fondo: un "comité de inversión" por ciclo.

Flujo de un ciclo (cada paso se publica en vivo en `fund:<uid>:status`):

  1. Memoria   → compara las opiniones del ciclo anterior con lo que hizo el
                 mercado y ajusta la confianza de cada mesa (aprendizaje).
  2. Riesgo    → cortacircuitos (drawdown, pérdidas seguidas, parada manual).
  3. Macro     → régimen desde DBnomics.        4. Sentimiento → titulares saneados.
  5. Analistas + cuant por activo (técnico + estrategia validada fuera de muestra).
  6. CIO       → cartera objetivo.               7. Riesgo → límites con veto.
  8. Trader    → órdenes; por defecto solo PROPONE. Ejecutar exige una orden
                 explícita (botón/endpoint) o el autopiloto, y siempre en PAPER.
  9. Memo      → Claude redacta el acta si hay credenciales; nunca decide.

Todo se guarda en fund_runs (auditoría completa, también de lo que se bloqueó).
"""

from __future__ import annotations

import asyncio
import json
import math
import logging
import time

import numpy as np

from .. import macro, news, paper
from ..datahub import hub
from ..db import get_db
from ..market.providers import market
from . import agents as A
from . import live as L
from . import training as T
from .research import cite

log = logging.getLogger("fincept.fund")
POLICY = A.RiskPolicy()
RUN_FRESH_SECONDS = 15 * 60
MIN_AUTOPILOT_MINUTES = 15
_locks: dict[int, asyncio.Lock] = {}


class FundError(Exception):
    pass


# ── estado persistente ──────────────────────────────────────────────────────

def get_state(uid: int) -> dict:
    db = get_db()
    row = db.one("SELECT * FROM fund_state WHERE user_id=?", (uid,))
    if not row:
        db.execute("INSERT INTO fund_state(user_id) VALUES (?)", (uid,))
        row = db.one("SELECT * FROM fund_state WHERE user_id=?", (uid,))
    row["desk_trust"] = json.loads(row["desk_trust"] or "{}")
    row["autopilot"], row["halted"] = bool(row["autopilot"]), bool(row["halted"])
    return row


def _save_state(uid: int, **fields) -> None:
    get_state(uid)  # garantiza que la fila existe: un UPDATE sobre nada fallaría en silencio
    if "desk_trust" in fields:
        fields["desk_trust"] = json.dumps(fields["desk_trust"])
    for k, v in fields.items():  # k viene de este módulo, nunca del cliente
        get_db().execute(f"UPDATE fund_state SET {k}=? WHERE user_id=?", (v, uid))


def last_run(uid: int, with_report: bool = True) -> dict | None:
    row = get_db().one("SELECT * FROM fund_runs WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,))
    if row and with_report:
        row["report"] = json.loads(row["report"] or "{}")
    return row


def list_runs(uid: int, limit: int = 30) -> list[dict]:
    rows = get_db().all("SELECT id, started, finished, trigger, status, equity, report FROM fund_runs "
                        "WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
    for r in rows:
        rep = json.loads(r.pop("report") or "{}")
        r["regime"] = rep.get("macro", {}).get("regime")
        r["orders"] = len(rep.get("orders", []))
        r["halted"] = rep.get("circuit_breaker", {}).get("halted", False)
    return rows


async def _emit(uid: int, stage: str, status: str, msg: str = "") -> None:
    await hub.publish(f"fund:{uid}:status", {"stage": stage, "status": status, "msg": msg, "ts": time.time()})


# ── datos ───────────────────────────────────────────────────────────────────

async def _fetch_histories() -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Históricos diarios de 5 años y su fuente ('yahoo' real o 'sim')."""
    res = await asyncio.gather(*(market.history(a.symbol, "5y", "1d") for a in A.UNIVERSE), return_exceptions=True)
    ok_ = [(a.symbol, r) for a, r in zip(A.UNIVERSE, res) if isinstance(r, dict) and len(r["candles"]) > 330]
    return {s: r["candles"] for s, r in ok_}, {s: r.get("source", "?") for s, r in ok_}


async def _histories() -> dict[str, list[dict]]:
    return (await _fetch_histories())[0]


def aligned_returns(hist: dict[str, list[dict]], days: int = 252) -> dict[str, list[float]]:
    """Rendimientos diarios en las mismas fechas para todos los activos (cripto cotiza en fin de semana)."""
    by_day = {s: {c["t"] // 86400: c["c"] for c in cs} for s, cs in hist.items()}
    common = sorted(set.intersection(*(set(d) for d in by_day.values()))) if by_day else []
    common = common[-(days + 1):]
    out = {}
    for s, d in by_day.items():
        px = [d[k] for k in common]
        out[s] = [px[i] / px[i - 1] - 1 for i in range(1, len(px)) if px[i - 1]]
    return out


def liquidity(hist: dict[str, list[dict]]) -> dict[str, tuple[float, float]]:
    """(volatilidad diaria, volumen medio de 20 sesiones) para el modelo de impacto."""
    out = {}
    for s, cs in hist.items():
        closes = [c["c"] for c in cs[-21:]]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
        vols = [c["v"] for c in cs[-20:] if c.get("v")]
        if len(rets) > 5 and vols:
            mu = sum(rets) / len(rets)
            out[s] = (math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets)), sum(vols) / len(vols))
    return out


MACRO_SOURCES = {  # por indicador, series candidatas en DBnomics: se usa la que tenga el dato más reciente
    "fed": ["FED/H15/RIFSPFF_N.M"],
    "unemployment": ["BLS/ln/LNS14000000", "Eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.US", "IMF/IFS/M.US.LUR_PT"],
    "inflation": ["Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA", "ECB/ICP/M.U2.N.000000.4.ANR"],
}
MACRO_MAX_AGE_MONTHS = 4  # un dato mensual con más retraso que esto no describe la economía de hoy


def months_old(period: str | None, now: float | None = None) -> int | None:
    """Meses entre un periodo 'AAAA-MM[-DD]' y hoy."""
    try:
        y, m = int(period[:4]), int(period[5:7])
    except (TypeError, ValueError):
        return None
    t = time.gmtime(now if now is not None else time.time())
    return (t.tm_year - y) * 12 + (t.tm_mon - m)


async def _macro_series() -> dict:
    """Series macro (más reciente al final) y, en `meta`, de dónde sale cada una y si está caducada."""
    async def fetch(sid: str) -> dict | None:
        try:
            o = await macro.observations(sid, 24)
            return {"series": sid, "last_period": o["last_period"], "values": [x["value"] for x in o["observations"]]}
        except (macro.MacroError, KeyError):
            return None

    async def best(key: str) -> dict | None:
        got = [r for r in await asyncio.gather(*(fetch(s) for s in MACRO_SOURCES[key])) if r and r["values"]]
        return max(got, key=lambda r: r["last_period"] or "") if got else None
    res = dict(zip(MACRO_SOURCES, await asyncio.gather(*(best(k) for k in MACRO_SOURCES))))
    meta = {}
    for k, r in res.items():
        if r:
            age = months_old(r["last_period"])
            meta[k] = {"series": r["series"], "last_period": r["last_period"], "age_months": age,
                       "stale": age is None or age > MACRO_MAX_AGE_MONTHS}
    return {k: (r["values"] if r else None) for k, r in res.items()} | {"meta": meta}


# ── memo del CIO (opcional, Claude) ─────────────────────────────────────────

def _deterministic_memo(rep: dict) -> str:
    m, top = rep["macro"], sorted(rep["target"].items(), key=lambda kv: -kv[1])[:5]
    lines = [f"Régimen {m['regime']} ({'; '.join(m['notes'])}).",
             f"Sentimiento de noticias {rep['sentiment']['avg_sentiment']:+.2f} sobre {rep['sentiment']['headlines']} "
             "titulares.",
             "Mayores posiciones objetivo: " + ", ".join(f"{s} {w:.1%}" for s, w in top) + "." if top else
             "Sin posiciones objetivo: todas las señales están neutrales o negativas.",
             f"Inversión objetivo {sum(rep['target'].values()):.0%}; el resto queda en caja.",
             f"{sum(v['strategy']['validated'] for v in rep['views'].values())} de {len(rep['views'])} estrategias "
             "superan el Deflated Sharpe y la prueba fuera de muestra; desacuerdo medio entre señales "
             f"{rep['disagreement']:.2f} (se preserva, no se promedia: Huang et al. 2026)."]
    tr = rep.get("training")
    if tr:
        s = tr["summary"]
        lines.append(f"Estrategias entrenadas hace {tr['age_days']:.1f} días: {s['with_edge']} de {s['trained']} activos "
                     f"con ventaja en validación, {s['validated']} validadas en la prueba final y {s['beats_buy_hold']} "
                     "por encima de comprar y mantener. Lo aprendido por mesa: "
                     + "; ".join(f"{d}: {v}" for d, v in tr["desks"].items()) + ".")
    if rep["circuit_breaker"]["halted"]:
        lines.append(f"CORTACIRCUITOS ACTIVO: {rep['circuit_breaker']['reason']}. Solo se permiten ventas.")
    return " ".join(lines)


async def _llm_memo(rep: dict) -> str | None:
    from ..ai_chat import claude_available, client
    from ..config import settings
    if not claude_available():
        return None
    brief = {k: rep[k] for k in ("macro", "target", "risk_checks", "circuit_breaker", "desk_trust")}
    brief["views"] = {s: {"score": round(v["score"], 2), "strategy": v["strategy"]["strategy"],
                          "validated": v["strategy"]["validated"]} for s, v in rep["views"].items()}
    brief["sentiment"] = {k: rep["sentiment"][k] for k in ("avg_sentiment", "headlines", "dropped_suspicious")}
    brief["training"] = rep.get("training")  # lo que aprendieron los agentes y los papers en que se basan
    try:
        resp = await client().beta.messages.create(
            model=settings.ai_model, max_tokens=4000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            thinking={"type": "adaptive"}, output_config={"effort": "low"},
            system=("You are the CIO of a paper-trading multi-asset fund. Write a concise investment committee memo "
                    "in Spanish (max 180 words) explaining the allocation below. You cannot change the allocation, "
                    "the risk limits or the orders; only explain them. Do not invent numbers. When it helps, mention what the "
                    "agents learned in training (per-desk lessons) and cite the papers listed there."),
            messages=[{"role": "user", "content": json.dumps(brief, default=str)}])
    except Exception as e:  # el memo es opcional: un fallo del LLM nunca para el ciclo
        log.warning("CIO memo failed: %s", e.__class__.__name__)
        return None
    if resp.stop_reason == "refusal":
        return None
    return "\n".join(b.text for b in resp.content if b.type == "text").strip() or None


# ── entrenamiento ───────────────────────────────────────────────────────────

async def _train(uid: int, hist: dict | None = None, sources: dict | None = None, trigger: str = "manual",
                 cost_bps: float | None = None) -> dict:
    if cost_bps is None:  # en modo real se entrena con la comisión real de IBKR para el capital configurado
        cost_bps = max(T.COST_BPS, L.live_cost_bps(L.config(uid))) if L.mode(uid) == "live" else T.COST_BPS
    await _emit(uid, "training", "running", "El equipo de investigación entrena sus estrategias (60/20/20 + DSR)")
    if hist is None:
        hist, sources = await _fetch_histories()
    result = await asyncio.to_thread(T.train_all, hist, sources, cost_bps)
    result["trigger"] = trigger
    T.save(uid, result)
    s = result["summary"]
    await _emit(uid, "training", "done", f"{s['with_edge']}/{s['trained']} activos con ventaja, {s['validated']} validados")
    return T.latest(uid)


def required_cost(uid: int) -> float:
    """Coste por operación con que tienen que estar entrenados los agentes en el modo actual."""
    return max(T.COST_BPS, L.live_cost_bps(L.config(uid))) if L.mode(uid) == "live" else T.COST_BPS


async def train(uid: int) -> dict:
    lock = _locks.setdefault(uid, asyncio.Lock())
    if lock.locked():
        raise FundError("Ya hay un ciclo o un entrenamiento en curso para esta cuenta.")
    async with lock:
        return await _train(uid)


# ── ciclo ───────────────────────────────────────────────────────────────────

async def run_cycle(uid: int, execute: bool = False, trigger: str = "manual") -> dict:
    lock = _locks.setdefault(uid, asyncio.Lock())
    if lock.locked():
        raise FundError("Ya hay un ciclo en curso para esta cuenta.")
    async with lock:
        return await _run_cycle(uid, execute, trigger)


async def _run_cycle(uid: int, execute: bool, trigger: str) -> dict:
    started = time.time()
    st = get_state(uid)
    mode = L.mode(uid)
    if mode == "live":
        execute = False  # dinero real: cada orden la aprueba una persona, nunca el ciclo ni el autopiloto
        reconciled = (await L.refresh(uid))["ok"]
        positions = L.ledger(uid, {})["positions"]
    else:
        acc = await paper.account(uid)
        positions = {p["symbol"]: p["qty"] for p in acc["positions"]}

    # 1. memoria / aprendizaje
    await _emit(uid, "memory", "running", "Evaluando las opiniones del ciclo anterior")
    prev = last_run(uid)
    quotes = await market.quotes([a.symbol for a in A.UNIVERSE] + list(positions))
    prices = {s: q["price"] for s, q in quotes.items()}
    if mode == "live":
        led = L.ledger(uid, prices)
        equity, cash = led["equity"], led["cash"]
        peak = max(L._row(uid)["peak_equity"] or 0.0, equity)
    else:
        equity, cash = acc["equity"], acc["cash"]
        peak = max(st["peak_equity"] or 0.0, equity)
    trust, learning = st["desk_trust"], {}
    same_mode = bool(prev) and prev["report"].get("mode", "paper") == mode
    losses = st["consecutive_losses"] if same_mode else 0  # cada modo lleva su propia racha y su propio máximo
    if prev and prev["report"].get("views"):
        trust, learning = A.update_desk_trust(trust, prev["report"]["views"], prev["report"].get("prices", {}),
                                              prices)
        if same_mode:
            losses = losses + 1 if prev["equity"] and equity < prev["equity"] * 0.999 else 0
    await _emit(uid, "memory", "done", f"{len(learning)} mesas evaluadas")

    # 2. cortacircuitos
    cb = A.circuit_breaker(equity, peak, losses, POLICY)
    daily = L.daily_check(uid, equity) if mode == "live" else None
    if daily and daily["breached"] and not st["halted"]:
        reason = f"pérdida diaria de {daily['loss']:.1%} (límite {daily['limit']:.1%})"
        set_halt(uid, True, reason)
        await L.cancel_open(uid, reason)  # también cancela en IBKR lo ya enviado
        st = get_state(uid)
    if st["halted"]:
        cb = {"halted": True, "reason": st["halt_reason"] or "parada manual", "drawdown": cb["drawdown"]}
    await _emit(uid, "risk_gate", "blocked" if cb["halted"] else "done", cb["reason"] or "operativa permitida")

    # 3-4. macro (tipos, paro, inflación + fragilidad sistémica) y sentimiento
    await _emit(uid, "macro", "running", "Tipos, paro e inflación (DBnomics) + absorption ratio")
    series, (hist, hist_src) = await asyncio.gather(_macro_series(), _fetch_histories())
    rets = aligned_returns(hist)
    matrix = np.array([r for r in rets.values()]).T if rets and len({len(r) for r in rets.values()}) == 1 else None
    fragility = await asyncio.to_thread(A.systemic_fragility, matrix) if matrix is not None else None
    regime = A.macro_regime(series["fed"], series["unemployment"], series["inflation"], fragility, series["meta"])
    await _emit(uid, "macro", "done", f"régimen {regime['regime']}")
    await _emit(uid, "sentiment", "running", "Analizando titulares")
    sent = A.news_sentiment(await news.top_news(60))
    await _emit(uid, "sentiment", "done", f"{sent['avg_sentiment']:+.2f} ({sent['dropped_suspicious']} descartados)")

    # 5. analistas por mesa + investigador cuant
    await _emit(uid, "analysts", "running", f"{len(A.UNIVERSE)} activos en {len(A.DESKS)} mesas")

    # 5a. entrenamiento: si no hay libro de estrategias o tiene más de 30 días, los agentes entrenan antes
    need_cost = required_cost(uid)
    training = T.latest(uid) or T.seed(uid, need_cost)  # agentes ya entrenados en agentes/, si no hay propios
    if (training is None or training["stale"]
            or training["protocol"]["cost_bps"] < need_cost - 1e-6):  # entrenado a un coste menor que el real
        training = await _train(uid, hist, hist_src, trigger="auto")
    book = training["book"] if training else {}

    def analyse() -> dict:
        out = {}
        for s, candles in hist.items():
            try:
                sig = A.asset_signals([c["c"] for c in candles])
                strat = T.apply_book(book.get(s), candles) or A.select_strategy(candles)
            except ValueError:
                continue
            out[s] = {"desk": A.BY_SYMBOL[s].desk, "signals": sig, "strategy": strat, "score": sig["score"]}
            out[s]["debate"] = A.debate(out[s], regime["regime"])
        return out
    views = await asyncio.to_thread(analyse)
    await _emit(uid, "analysts", "done", f"{len(views)} opiniones")

    # 6-7. CIO + gestor de riesgos
    cov_info = A.covariance({s: r for s, r in rets.items() if s in views})
    raw = A.build_portfolio(views, regime, sent, trust, cov_info)
    vols = {s: v["signals"]["vol60"] for s, v in views.items()}
    bubbles = {s for s, v in views.items() if v["signals"].get("bubble")}
    target, risk_checks = A.apply_risk(raw, vols, POLICY, cov_info, bubbles)
    await _emit(uid, "risk", "done", f"{len(risk_checks)} controles")

    # 8. trader
    orders, order_checks = A.plan_orders(target, positions, prices, equity, POLICY, liquidity(hist))
    if cb["halted"]:
        blocked = [o for o in orders if o["side"] == "buy"]
        orders = [o for o in orders if o["side"] == "sell"]
        if blocked:
            order_checks.append({"check": "cortacircuitos", "status": "blocked",
                                 "detail": f"{len(blocked)} compra(s) bloqueadas"})
    if mode == "live":  # las órdenes reales se crean abajo, pendientes de aprobación una a una
        orders = []
    rep = {
        "mode": mode, "daily": daily,
        "equity": equity, "cash": cash, "prices": {s: prices[s] for s in views if s in prices},
        "positions": positions, "macro": regime, "sentiment": sent, "learning": learning, "desk_trust": trust,
        "circuit_breaker": cb, "views": views, "raw_weights": raw, "target": target, "risk_checks": risk_checks,
        "orders": orders, "order_checks": order_checks, "policy": vars(POLICY), "fills": [],
        "data_source": next(iter(quotes.values()), {}).get("source", "?"),
        # Qué investigación respalda cada etapa (ver research.py y la pantalla FUND).
        "evidence": {
            "memory": cite("yu2024"), "macro": cite("sahm2019", "kritzman2011"), "sentiment": cite("tetlock2007", "greshake2023"),
            "analysts": cite("moskowitz2012", "jegadeesh1993", "daniel2016", "miyazaki2026"),
            "quant": cite("bailey2014", "bailey2016", "harvey2016", "hurst2017", "faber2007", "brock1992",
                          "levine2016", *(p["id"] for p in (training or {}).get("papers_used", []))),
            "cio": cite("maillard2010", "xiao2024", "huang2026", "glasserman2023"),
            "risk": cite("moreira2017", "demiguel2024", "li2025", "pafka2003", "higham2002", "phillips2015"),
            "execution": cite("bonart2026", "almgren2001"),
        },
        "quantfin": {"fragility": fragility, "bubbles": sorted(bubbles),
                     "risk_budget": A.risk_budget(list(raw), views, cov_info)[1] if raw else None,
                     "covariance": {"assets": len(cov_info[0]), "days": cov_info[2]} if cov_info else None},
        "training": T.brief(training) | {"id": training["id"], "age_days": training["age_days"]} if training else None,
        "disagreement": round(sum(v["debate"]["disagreement"] for v in views.values()) / max(1, len(views)), 3),
    }
    rep["memo"] = _deterministic_memo(rep)
    await _emit(uid, "cio", "running", "Redactando el acta del comité")
    llm = await _llm_memo(rep)
    if llm:
        rep["memo_llm"] = llm
    await _emit(uid, "cio", "done", "acta lista")

    if mode == "live":
        get_db().execute("UPDATE fund_live SET peak_equity=? WHERE user_id=?", (peak, uid))
        _save_state(uid, desk_trust=trust, consecutive_losses=losses, last_cycle_at=started)
    else:
        _save_state(uid, desk_trust=trust, peak_equity=peak, consecutive_losses=losses, last_cycle_at=started)
    cur = get_db().execute(
        "INSERT INTO fund_runs(user_id, started, finished, trigger, status, equity, report) VALUES (?,?,?,?,?,?,?)",
        (uid, started, time.time(), trigger, "proposed", equity, json.dumps(rep, default=str)))
    run_id = cur.lastrowid
    if mode == "live":
        live_orders, live_checks = L.plan(uid, run_id, target, views, prices,
                                          {s: q.get("source", "?") for s, q in quotes.items()},
                                          (training or {}).get("book", {}), liquidity(hist), POLICY,
                                          allow_buys=not cb["halted"], reconciled=reconciled)
        rep["live_orders"], rep["order_checks"] = live_orders, rep["order_checks"] + live_checks
    rep["team"] = _team(rep)
    get_db().execute("UPDATE fund_runs SET report=? WHERE id=?", (json.dumps(rep, default=str), run_id))
    if execute:
        await execute_run(uid, run_id)
    await _emit(uid, "done", "done", f"ciclo #{run_id}")
    return get_run(uid, run_id)


def _team(rep: dict) -> dict:
    """Cómo trabajó el equipo: lo que aportó cada agente de investigación y cada miembro del comité,
    y qué pasó con cada recomendación de investigación al llegar al comité."""
    views, target, live = rep["views"], rep["target"], rep.get("mode") == "live"
    ranked = sorted(views.items(), key=lambda kv: -kv[1]["score"])
    tr = rep.get("training") or {}
    research = [
        {"agent": "Estratega macro", "output": f"régimen {rep['macro']['regime']}: {'; '.join(rep['macro']['notes'])}"},
        {"agent": "Analista de sentimiento", "output": f"tono {rep['sentiment']['avg_sentiment']:+.2f} en "
                                                       f"{rep['sentiment']['headlines']} titulares, "
                                                       f"{rep['sentiment']['dropped_suspicious']} descartados"},
        {"agent": "Analistas por mesa", "output": "más alcistas: " + ", ".join(s for s, _ in ranked[:3])
                                                  + "; más bajistas: " + ", ".join(s for s, _ in ranked[-3:])},
        {"agent": "Investigador cuant", "output": (f"{tr['summary']['validated']} estrategias validadas de "
                                                   f"{tr['summary']['trained']} entrenadas" if tr else "sin entrenar")},
    ]
    blocked = {c["check"].split(" ", 1)[1]: c["detail"] for c in rep["order_checks"]
               if c["check"].startswith("real ") and c["status"] == "blocked"}
    recs = []
    for s, v in ranked:
        if v["score"] <= 0.05:
            continue
        w = target.get(s)
        recs.append({"symbol": s, "research": v["debate"]["verdict"], "score": round(v["score"], 2),
                     "committee": f"{w:.1%} objetivo" if w else "descartada por el CIO o el gestor de riesgos",
                     "live": (blocked.get(s) or ("cripto no se opera en IBKR en esta versión"
                                                 if s in L.NOT_IN_IBKR and w else None)) if live else None})
    n_orders = len(rep.get("live_orders") or []) if live else len(rep["orders"])
    committee = [
        {"agent": "CIO", "output": f"{len(target)} posiciones objetivo, {sum(target.values()):.0%} invertido"},
        {"agent": "Gestor de riesgos", "output": f"{len(rep['risk_checks'])} controles"
                                                 + (f"; CORTACIRCUITOS: {rep['circuit_breaker']['reason']}"
                                                    if rep["circuit_breaker"]["halted"] else "")},
        {"agent": "Trader", "output": f"{n_orders} órdenes " + ("reales pendientes de tu aprobación (IBKR)" if live
                                                                else "en paper")},
    ]
    return {"research": research, "committee": committee, "recommendations": recs}


def get_run(uid: int, run_id: int) -> dict:
    row = get_db().one("SELECT * FROM fund_runs WHERE id=? AND user_id=?", (run_id, uid))
    if not row:
        raise FundError("Ciclo no encontrado.")
    row["report"] = json.loads(row["report"] or "{}")
    return row


async def execute_run(uid: int, run_id: int) -> dict:
    """Ejecuta en PAPER las órdenes de un ciclo propuesto. Revalida todo antes de enviar (defensa en profundidad)."""
    if L.mode(uid) == "live":
        raise FundError("El fondo está en modo real: aprueba cada orden en la pantalla FUND (IBKR).")
    run = get_run(uid, run_id)
    if run["status"] != "proposed":
        raise FundError(f"El ciclo está '{run['status']}', no se puede ejecutar.")
    if time.time() - run["finished"] > RUN_FRESH_SECONDS:
        raise FundError("La propuesta tiene más de 15 minutos: lanza un ciclo nuevo con precios actuales.")
    st = get_state(uid)
    rep = run["report"]
    fills, rejected = [], []
    budget = POLICY.max_turnover * rep["equity"]
    for o in rep["orders"]:
        if o["symbol"] not in A.BY_SYMBOL and not (o["side"] == "sell" and o["symbol"] in rep["positions"]):
            rejected.append({**o, "reason": "fuera del universo"})
            continue
        if o["side"] == "buy" and (st["halted"] or rep["circuit_breaker"]["halted"]):
            rejected.append({**o, "reason": "cortacircuitos"})
            continue
        if o["side"] == "buy" and o["notional"] > budget:
            rejected.append({**o, "reason": "límite de rotación"})
            continue
        try:
            order = await paper.place_order(uid, o["symbol"], o["side"], o["qty"], "market", source="fund")
        except paper.OrderError as e:
            rejected.append({**o, "reason": str(e)})
            continue
        if order["status"] == "filled":
            budget -= o["notional"] if o["side"] == "buy" else 0
            fills.append({"symbol": o["symbol"], "side": o["side"], "qty": o["qty"], "price": order["filled_price"],
                          "order_id": order["id"]})
        else:
            rejected.append({**o, "reason": order.get("note") or order["status"]})
    rep["fills"], rep["rejected"] = fills, rejected
    status = "executed" if fills or not rep["orders"] else "rejected"
    get_db().execute("UPDATE fund_runs SET status=?, report=? WHERE id=?",
                     (status, json.dumps(rep, default=str), run_id))
    await _emit(uid, "execution", "done", f"{len(fills)} ejecutadas, {len(rejected)} rechazadas")
    return get_run(uid, run_id)


def set_halt(uid: int, halted: bool, reason: str | None = None) -> dict:
    _save_state(uid, halted=int(halted), halt_reason=reason if halted else None,
                **({} if halted else {"consecutive_losses": 0}))
    if halted:
        _save_state(uid, autopilot=0)
    return get_state(uid)


def set_autopilot(uid: int, on: bool, interval_min: int | None = None) -> dict:
    if interval_min is not None:
        _save_state(uid, interval_min=max(MIN_AUTOPILOT_MINUTES, min(1440, int(interval_min))))
    if on and get_state(uid)["halted"]:
        raise FundError("El fondo está parado: reanúdalo antes de activar el autopiloto.")
    _save_state(uid, autopilot=int(on))
    return get_state(uid)


async def autopilot_loop() -> None:
    """Lanza ciclos con ejecución (PAPER) para quien tenga el autopiloto activo."""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        for row in get_db().all("SELECT user_id, interval_min, last_cycle_at FROM fund_state "
                                "WHERE autopilot=1 AND halted=0"):
            if now - (row["last_cycle_at"] or 0) >= row["interval_min"] * 60:
                _save_state(row["user_id"], last_cycle_at=now)  # un fallo no provoca reintentos cada minuto
                try:
                    await run_cycle(row["user_id"], execute=True, trigger="autopilot")
                except Exception:
                    log.exception("autopilot cycle failed for user %s", row["user_id"])
