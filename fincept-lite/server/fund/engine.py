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
import logging
import time

from .. import macro, news, paper
from ..datahub import hub
from ..db import get_db
from ..market.providers import market
from . import agents as A

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

async def _histories() -> dict[str, list[dict]]:
    res = await asyncio.gather(*(market.history(a.symbol, "5y", "1d") for a in A.UNIVERSE), return_exceptions=True)
    return {a.symbol: r["candles"] for a, r in zip(A.UNIVERSE, res) if isinstance(r, dict) and len(r["candles"]) > 330}


async def _macro_series() -> dict:
    async def values(sid: str) -> list[float] | None:
        try:
            return [o["value"] for o in (await macro.observations(sid, 24))["observations"]]
        except (macro.MacroError, KeyError):
            return None
    fed, une, hicp = await asyncio.gather(values("FED/H15/RIFSPFF_N.M"), values("BLS/ln/LNS14000000"),
                                          values("Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA"))
    return {"fed": fed, "unemployment": une, "inflation": hicp}


# ── memo del CIO (opcional, Claude) ─────────────────────────────────────────

def _deterministic_memo(rep: dict) -> str:
    m, top = rep["macro"], sorted(rep["target"].items(), key=lambda kv: -kv[1])[:5]
    lines = [f"Régimen {m['regime']} ({'; '.join(m['notes'])}).",
             f"Sentimiento de noticias {rep['sentiment']['avg_sentiment']:+.2f} sobre {rep['sentiment']['headlines']} "
             "titulares.",
             "Mayores posiciones objetivo: " + ", ".join(f"{s} {w:.1%}" for s, w in top) + "." if top else
             "Sin posiciones objetivo: todas las señales están neutrales o negativas.",
             f"Inversión objetivo {sum(rep['target'].values()):.0%}; el resto queda en caja."]
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
    try:
        resp = await client().beta.messages.create(
            model=settings.ai_model, max_tokens=4000, betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            thinking={"type": "adaptive"}, output_config={"effort": "low"},
            system=("You are the CIO of a paper-trading multi-asset fund. Write a concise investment committee memo "
                    "in Spanish (max 180 words) explaining the allocation below. You cannot change the allocation, "
                    "the risk limits or the orders; only explain them. Do not invent numbers."),
            messages=[{"role": "user", "content": json.dumps(brief, default=str)}])
    except Exception as e:  # el memo es opcional: un fallo del LLM nunca para el ciclo
        log.warning("CIO memo failed: %s", e.__class__.__name__)
        return None
    if resp.stop_reason == "refusal":
        return None
    return "\n".join(b.text for b in resp.content if b.type == "text").strip() or None


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
    acc = await paper.account(uid)
    equity = acc["equity"]
    positions = {p["symbol"]: p["qty"] for p in acc["positions"]}

    # 1. memoria / aprendizaje
    await _emit(uid, "memory", "running", "Evaluando las opiniones del ciclo anterior")
    prev = last_run(uid)
    quotes = await market.quotes([a.symbol for a in A.UNIVERSE] + list(positions))
    prices = {s: q["price"] for s, q in quotes.items()}
    trust, learning = st["desk_trust"], {}
    losses = st["consecutive_losses"]
    if prev and prev["report"].get("views"):
        trust, learning = A.update_desk_trust(trust, prev["report"]["views"], prev["report"].get("prices", {}),
                                              prices)
        losses = losses + 1 if prev["equity"] and equity < prev["equity"] * 0.999 else 0
    peak = max(st["peak_equity"] or 0.0, equity)
    await _emit(uid, "memory", "done", f"{len(learning)} mesas evaluadas")

    # 2. cortacircuitos
    cb = A.circuit_breaker(equity, peak, losses, POLICY)
    if st["halted"]:
        cb = {"halted": True, "reason": st["halt_reason"] or "parada manual", "drawdown": cb["drawdown"]}
    await _emit(uid, "risk_gate", "blocked" if cb["halted"] else "done", cb["reason"] or "operativa permitida")

    # 3-4. macro y sentimiento
    await _emit(uid, "macro", "running", "Leyendo tipos, paro e inflación (DBnomics)")
    series = await _macro_series()
    regime = A.macro_regime(series["fed"], series["unemployment"], series["inflation"])
    await _emit(uid, "macro", "done", f"régimen {regime['regime']}")
    await _emit(uid, "sentiment", "running", "Analizando titulares")
    sent = A.news_sentiment(await news.top_news(60))
    await _emit(uid, "sentiment", "done", f"{sent['avg_sentiment']:+.2f} ({sent['dropped_suspicious']} descartados)")

    # 5. analistas por mesa + investigador cuant
    await _emit(uid, "analysts", "running", f"{len(A.UNIVERSE)} activos en {len(A.DESKS)} mesas")
    hist = await _histories()

    def analyse() -> dict:
        out = {}
        for s, candles in hist.items():
            try:
                sig = A.asset_signals([c["c"] for c in candles])
                strat = A.select_strategy(candles)
            except ValueError:
                continue
            out[s] = {"desk": A.BY_SYMBOL[s].desk, "signals": sig, "strategy": strat, "score": sig["score"]}
        return out
    views = await asyncio.to_thread(analyse)
    await _emit(uid, "analysts", "done", f"{len(views)} opiniones")

    # 6-7. CIO + gestor de riesgos
    raw = A.build_portfolio(views, regime, sent, trust)
    vols = {s: v["signals"]["vol60"] for s, v in views.items()}
    target, risk_checks = A.apply_risk(raw, vols, POLICY)
    await _emit(uid, "risk", "done", f"{len(risk_checks)} controles")

    # 8. trader
    orders, order_checks = A.plan_orders(target, positions, prices, equity, POLICY)
    if cb["halted"]:
        blocked = [o for o in orders if o["side"] == "buy"]
        orders = [o for o in orders if o["side"] == "sell"]
        if blocked:
            order_checks.append({"check": "cortacircuitos", "status": "blocked",
                                 "detail": f"{len(blocked)} compra(s) bloqueadas"})
    rep = {
        "equity": equity, "cash": acc["cash"], "prices": {s: prices[s] for s in views if s in prices},
        "positions": positions, "macro": regime, "sentiment": sent, "learning": learning, "desk_trust": trust,
        "circuit_breaker": cb, "views": views, "raw_weights": raw, "target": target, "risk_checks": risk_checks,
        "orders": orders, "order_checks": order_checks, "policy": vars(POLICY), "fills": [],
        "data_source": next(iter(quotes.values()), {}).get("source", "?"),
    }
    rep["memo"] = _deterministic_memo(rep)
    await _emit(uid, "cio", "running", "Redactando el acta del comité")
    llm = await _llm_memo(rep)
    if llm:
        rep["memo_llm"] = llm
    await _emit(uid, "cio", "done", "acta lista")

    _save_state(uid, desk_trust=trust, peak_equity=peak, consecutive_losses=losses, last_cycle_at=started)
    cur = get_db().execute(
        "INSERT INTO fund_runs(user_id, started, finished, trigger, status, equity, report) VALUES (?,?,?,?,?,?,?)",
        (uid, started, time.time(), trigger, "proposed", equity, json.dumps(rep, default=str)))
    run_id = cur.lastrowid
    if execute:
        await execute_run(uid, run_id)
    await _emit(uid, "done", "done", f"ciclo #{run_id}")
    return get_run(uid, run_id)


def get_run(uid: int, run_id: int) -> dict:
    row = get_db().one("SELECT * FROM fund_runs WHERE id=? AND user_id=?", (run_id, uid))
    if not row:
        raise FundError("Ciclo no encontrado.")
    row["report"] = json.loads(row["report"] or "{}")
    return row


async def execute_run(uid: int, run_id: int) -> dict:
    """Ejecuta en PAPER las órdenes de un ciclo propuesto. Revalida todo antes de enviar (defensa en profundidad)."""
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
