"""Modo real del fondo con Interactive Brokers: aprobación orden a orden y protecciones en el código.

Nada de esto depende del modelo ni de los agentes: son comprobaciones deterministas que se hacen
al proponer y otra vez al aprobar cada orden.

* El modo real arranca apagado. Para encenderlo hacen falta capital, máximo por orden, pérdida
  diaria máxima y cuenta configurados por la persona, datos de mercado reales
  (FINCEPT_DATA_MODE=live) y el gateway de IBKR con sesión iniciada.
* El fondo lleva su propio registro de lo que compró y vendió: nunca vende posiciones de la cuenta
  que no sean suyas y nunca gasta más que el capital asignado.
* Compras solo en activos con estrategia entrenada con datos reales y validada (sin periodo en
  sombra, por decisión del usuario). Ventas siempre permitidas (reducen riesgo).
* Cada orden es limitada (±0,5 % del precio de referencia), DAY, con número entero de acciones y
  como máximo el importe por orden configurado. Cripto no se opera en IBKR en esta versión.
* Al aprobar: precio fresco de fuente real con desvío ≤ 1 %, propuesta de menos de 15 minutos,
  confirmación textual exacta de la orden, fondo no parado y pérdida diaria no superada.
* La parada de emergencia cancela las órdenes enviadas. Todo intento queda auditado.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from ..config import settings
from ..db import get_db
from ..market.providers import market
from . import agents as A
from .ibkr import IBKRClient, IBKRError

LIVE_SOURCE = "yahoo"  # proveedor de datos reales; "sim" nunca sirve para dinero real
SLIPPAGE_BPS = 5.0
# Comisiones de IBKR Pro para acciones/ETF de EE. UU. (USD). Compruébalas en tu cuenta: pueden cambiar.
COMMISSION_PLANS = {"fixed": {"per_share": 0.005, "min": 1.00, "max_pct": 0.01},
                    "tiered": {"per_share": 0.0035, "min": 0.35, "max_pct": 0.01}}  # tiered sin tasas de bolsa
LIMIT_BAND = 0.005
MAX_DRIFT = 0.01
FRESH_SECONDS = 15 * 60
NOT_IN_IBKR = {a.symbol for a in A.UNIVERSE if a.desk == "crypto"}
IN_FLIGHT = ("submitted", "partially_filled", "needs_confirmation", "unreconciled")  # cuentan como comprometidas

client_factory = IBKRClient  # los tests lo sustituyen por un gateway simulado


class LiveError(Exception):
    pass


# ── estado y configuración ──────────────────────────────────────────────────

def _row(uid: int) -> dict:
    db = get_db()
    row = db.one("SELECT * FROM fund_live WHERE user_id=?", (uid,))
    if not row:
        db.execute("INSERT INTO fund_live(user_id) VALUES (?)", (uid,))
        row = db.one("SELECT * FROM fund_live WHERE user_id=?", (uid,))
    row["config"] = json.loads(row["config"] or "{}")
    return row


def config(uid: int) -> dict:
    return _row(uid)["config"]


def mode(uid: int) -> str:
    return _row(uid)["mode"]


def commission(cfg: dict, qty: float, price: float) -> float:
    """Comisión estimada de una orden en USD según el plan de IBKR configurado."""
    p = COMMISSION_PLANS[cfg.get("commission_plan", "fixed")]
    value = qty * price
    return min(max(p["per_share"] * qty, p["min"]), p["max_pct"] * value) if value > 0 else 0.0


def order_cost_bps(cfg: dict, qty: float, price: float) -> float:
    """Coste por lado de una orden en puntos básicos: comisión + deslizamiento."""
    value = qty * price
    return (commission(cfg, qty, price) / value * 1e4 if value else 0.0) + SLIPPAGE_BPS


def live_cost_bps(cfg: dict) -> float:
    """Coste por lado con que hay que entrenar para este capital: el de una posición típica (un cuarto del
    capital o el máximo por orden, lo menor) en un ETF de unos 50 USD."""
    if not cfg:
        return 0.0
    value = max(1.0, min(cfg["max_order"], cfg["capital"] / 4))
    return order_cost_bps(cfg, max(1.0, value / 50.0), value / max(1.0, value / 50.0))


def validate_config(cfg: dict) -> dict:
    try:
        capital, max_order = float(cfg["capital"]), float(cfg["max_order"])
        loss, account = float(cfg["daily_loss_pct"]), str(cfg["account"]).strip().upper()
        plan_ = str(cfg.get("commission_plan") or "fixed").lower()
    except (KeyError, TypeError, ValueError) as e:
        raise LiveError("Faltan datos: capital, max_order, daily_loss_pct y account.") from e
    if plan_ not in COMMISSION_PLANS:
        raise LiveError("Plan de comisiones desconocido: 'fixed' o 'tiered'.")
    if not 0 < capital <= 10_000_000:
        raise LiveError("El capital debe estar entre 0 y 10.000.000.")
    if not 0 < max_order <= capital:
        raise LiveError("El máximo por orden debe ser positivo y no superar el capital.")
    if not 0 < loss <= 0.2:
        raise LiveError("La pérdida diaria máxima debe estar entre 0 y 20 % (0.02 = 2 %).")
    if not re.fullmatch(r"[A-Z0-9]{4,20}", account):
        raise LiveError("Cuenta de IBKR no válida (p. ej. U1234567 o DU1234567 para la cuenta de prueba de IBKR).")
    return {"capital": capital, "max_order": max_order, "daily_loss_pct": loss, "account": account,
            "commission_plan": plan_}


def set_config(uid: int, cfg: dict) -> dict:
    clean = validate_config(cfg)
    if mode(uid) == "live":  # cambiar el capital a mitad de día falsearía la pérdida diaria
        raise LiveError("Vuelve a modo paper para cambiar el capital o los límites.")
    _row(uid)
    get_db().execute("UPDATE fund_live SET config=?, updated=? WHERE user_id=?", (json.dumps(clean), time.time(), uid))
    return clean


async def gateway_status(uid: int) -> dict:
    cfg = config(uid)
    try:
        c = client_factory()
    except IBKRError as e:
        return {"reachable": False, "authenticated": False, "error": str(e)}
    try:
        st = await c.status()
        accounts = await c.accounts() if st["authenticated"] else []
        return {"reachable": True, **st, "accounts": accounts,
                "account_ok": bool(cfg.get("account")) and cfg.get("account") in accounts}
    except IBKRError as e:
        return {"reachable": False, "authenticated": False, "error": str(e)}
    finally:
        await c.close()


async def set_mode(uid: int, new: str) -> dict:
    if new not in ("paper", "live"):
        raise LiveError("Modo desconocido.")
    if new == "live":
        problems = []
        if not config(uid):
            problems.append("configura capital, máximo por orden, pérdida diaria y cuenta")
        if settings.data_mode != "live":
            problems.append("el servidor usa datos simulados (arranca con FINCEPT_DATA_MODE=live)")
        gw = await gateway_status(uid)
        if not gw.get("authenticated"):
            problems.append(gw.get("error") or "el gateway de IBKR no tiene sesión iniciada")
        elif not gw.get("account_ok"):
            problems.append("la cuenta configurada no aparece en el gateway de IBKR")
        if problems:
            raise LiveError("No se puede activar el modo real: " + "; ".join(problems) + ".")
    else:  # al volver a paper, lo pendiente de aprobar caduca (lo ya enviado a IBKR sigue su curso)
        _audit_bulk(uid, "pending", "expired", "modo paper activado")
    get_db().execute("UPDATE fund_live SET mode=?, updated=? WHERE user_id=?", (new, time.time(), uid))
    return {"mode": new}


# ── registro propio del fondo ───────────────────────────────────────────────

def orders(uid: int, limit: int = 100) -> list[dict]:
    rows = get_db().all("SELECT * FROM fund_live_orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))
    for r in rows:
        r["detail"] = json.loads(r["detail"] or "[]")
    return rows


def ledger(uid: int, prices: dict[str, float]) -> dict:
    """Posiciones y caja DEL FONDO según sus propias órdenes ejecutadas (no la cuenta entera)."""
    cfg = config(uid)
    qty: dict[str, float] = {}
    cash = float(cfg.get("capital") or 0.0)
    fees = 0.0
    for o in get_db().all("SELECT symbol, side, filled_qty, avg_price FROM fund_live_orders "
                          "WHERE user_id=? AND filled_qty > 0", (uid,)):
        sign = 1 if o["side"] == "buy" else -1
        qty[o["symbol"]] = qty.get(o["symbol"], 0.0) + sign * o["filled_qty"]
        cash -= sign * o["filled_qty"] * (o["avg_price"] or 0.0)
        fee = commission(cfg, o["filled_qty"], o["avg_price"] or 0.0) if cfg else 0.0
        cash -= fee  # comisión estimada (la real puede diferir unos céntimos)
        fees += fee
    reserved, selling = 0.0, {}
    marks = ",".join("?" * len(IN_FLIGHT))
    for o in get_db().all(f"SELECT symbol, side, qty, filled_qty, limit_price FROM fund_live_orders "
                          f"WHERE user_id=? AND status IN ({marks})", (uid, *IN_FLIGHT)):
        left = max(0.0, o["qty"] - (o["filled_qty"] or 0.0))
        if o["side"] == "buy":
            reserved += left * o["limit_price"]  # capital comprometido en compras aún no ejecutadas
        else:
            selling[o["symbol"]] = selling.get(o["symbol"], 0.0) + left  # acciones ya en venta
    positions = {s: q for s, q in qty.items() if q > 1e-9}
    available = {s: q - selling.get(s, 0.0) for s, q in positions.items() if q - selling.get(s, 0.0) > 1e-9}
    equity = cash + sum(q * prices.get(s, 0.0) for s, q in positions.items())
    unreconciled = get_db().one("SELECT COUNT(*) AS n FROM fund_live_orders WHERE user_id=? AND status='unreconciled'",
                                (uid,))["n"]
    return {"capital": cfg.get("capital"), "currency": "USD", "cash": cash, "reserved": reserved, "fees": fees,
            "positions": positions, "available_to_sell": available, "selling": selling, "equity": equity,
            "unreconciled": unreconciled}


def _log(row_id: int, action: str, result: str, **extra) -> None:
    row = get_db().one("SELECT detail FROM fund_live_orders WHERE id=?", (row_id,))
    detail = json.loads(row["detail"] or "[]") + [{"at": time.time(), "action": action, "result": result, **extra}]
    get_db().execute("UPDATE fund_live_orders SET detail=?, updated=? WHERE id=?",
                     (json.dumps(detail, default=str), time.time(), row_id))


def _set_status(row_id: int, status: str, action: str, result: str, **cols) -> None:
    sets = ", ".join(f"{k}=?" for k in ("status", *cols))  # columnas fijas de este módulo
    get_db().execute(f"UPDATE fund_live_orders SET {sets} WHERE id=?", (status, *cols.values(), row_id))
    _log(row_id, action, result)


def _audit_bulk(uid: int, from_status: str, to_status: str, reason: str) -> None:
    for r in get_db().all("SELECT id FROM fund_live_orders WHERE user_id=? AND status=?", (uid, from_status)):
        _set_status(r["id"], to_status, "sistema", reason)


# ── propuesta (comité) ──────────────────────────────────────────────────────

def daily_check(uid: int, equity: float) -> dict:
    """Guarda el patrimonio del fondo al empezar el día (UTC) y dice si se ha superado la pérdida máxima."""
    row, today = _row(uid), datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if row["day"] != today or not row["day_start_equity"]:
        get_db().execute("UPDATE fund_live SET day=?, day_start_equity=? WHERE user_id=?", (today, equity, uid))
        start = equity
    else:
        start = row["day_start_equity"]
    limit = float(row["config"].get("daily_loss_pct") or 0)
    loss = 1 - equity / start if start else 0.0
    return {"day": today, "start_equity": start, "loss": loss, "limit": limit,
            "breached": bool(limit) and loss >= limit}


def live_gate(symbol: str, view: dict | None, book_entry: dict | None, cost_bps: float | None = None) -> str | None:
    """Motivo por el que NO se puede comprar este activo con dinero real (None = se puede).
    `cost_bps`: coste real por lado de la orden; la estrategia tiene que haberse validado al menos a ese coste."""
    if symbol in NOT_IN_IBKR:
        return "cripto no se opera en IBKR en esta versión"
    if not book_entry or not book_entry.get("trained"):
        return "sin estrategia entrenada"
    if book_entry.get("data_source") != LIVE_SOURCE:
        return "estrategia entrenada con datos simulados: reentrena con datos reales"
    if not book_entry.get("validated"):
        return "estrategia no validada (prueba final + Deflated Sharpe)"
    if view and not view["strategy"].get("trained"):
        return "el comité no usó la estrategia entrenada"
    trained_at = float(book_entry.get("cost_bps") or 10.0)
    if cost_bps is not None and cost_bps > trained_at + 1e-6:
        return (f"la comisión de esta orden ({cost_bps:.0f} pb por lado) supera el coste con que se validó la "
                f"estrategia ({trained_at:.0f} pb): reentrena al coste real o sube el tamaño de la orden")
    return None


def plan(uid: int, run_id: int, target: dict[str, float], views: dict, prices: dict[str, float],
         sources: dict[str, str], book: dict, liquidity: dict | None, policy,
         allow_buys: bool = True, reconciled: bool = True) -> tuple[list[dict], list[dict]]:
    """Convierte los pesos objetivo en órdenes reales pendientes de aprobación.

    Lo pendiente de ciclos anteriores caduca: solo se puede aprobar la propuesta más reciente (si no,
    dos ciclos seguidos permitirían aprobar dos veces la misma compra o vender dos veces las mismas acciones)."""
    for st in ("pending", "needs_confirmation"):
        _audit_bulk(uid, st, "expired", f"sustituida por el ciclo #{run_id}")
    cfg, checks = config(uid), []
    led = ledger(uid, prices)
    if not reconciled or led["unreconciled"]:
        allow_buys = False
        checks.append({"check": "conciliación IBKR", "status": "blocked",
                       "detail": "hay órdenes sin conciliar con IBKR: resuélvelas antes de comprar"})
    raw, plan_checks = A.plan_orders(target, led["positions"], prices, led["equity"], policy, liquidity)
    checks += plan_checks
    cash = led["cash"] - led["reserved"]
    out = []
    for o in raw:  # ventas primero (plan_orders ya las ordena así)
        s, side, px = o["symbol"], o["side"], prices.get(o["symbol"])
        if sources.get(s) != LIVE_SOURCE:
            checks.append({"check": f"real {s}", "status": "blocked", "detail": "precio no real (fuente simulada)"})
            continue
        if side == "buy" and not allow_buys:
            checks.append({"check": f"real {s}", "status": "blocked",
                           "detail": "compras bloqueadas (cortacircuitos u órdenes sin conciliar): solo ventas"})
            continue
        if side == "buy":
            why = live_gate(s, views.get(s), book.get(s))
            if why:
                checks.append({"check": f"real {s}", "status": "blocked", "detail": why})
                continue
            limit = px * (1 + LIMIT_BAND)
            qty = int(min(o["qty"], cfg["max_order"] // limit, max(cash, 0.0) // limit))
            if qty >= 1:
                why = live_gate(s, None, book.get(s), order_cost_bps(cfg, qty, limit))
                if why:
                    checks.append({"check": f"real {s}", "status": "blocked", "detail": why})
                    continue
        else:
            limit = px * (1 - LIMIT_BAND)
            qty = int(min(o["qty"], led["available_to_sell"].get(s, 0.0)))  # descuenta lo que ya está en venta
        if qty < 1:
            checks.append({"check": f"real {s}", "status": "info",
                           "detail": "menos de 1 acción tras límites de capital y de importe por orden"})
            continue
        if side == "buy":
            cash -= qty * limit
        fee = commission(cfg, qty, limit)
        cur = get_db().execute(
            "INSERT INTO fund_live_orders(user_id, run_id, symbol, side, qty, limit_price, ref_price, notional, "
            "status, created, updated, detail, commission) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, run_id, s, side, qty, round(limit, 2), px, qty * limit, "pending", time.time(), time.time(),
             json.dumps([{"at": time.time(), "action": "propuesta", "result": f"ciclo #{run_id}"}]), fee))
        out.append({"id": cur.lastrowid, "symbol": s, "side": side, "qty": qty, "limit_price": round(limit, 2),
                    "notional": qty * limit, "commission": fee, "cost_pct": fee / (qty * limit)})
    seen = {c["check"].split(" ", 1)[-1] for c in checks} | {o["symbol"] for o in out}
    for s, w in target.items():  # explica también lo que plan_orders descarta sin decir nada
        px = prices.get(s)
        if s not in seen and s in NOT_IN_IBKR:
            checks.append({"check": f"real {s}", "status": "blocked", "detail": "cripto no se opera en IBKR en esta versión"})
        elif s not in seen and px and w * led["equity"] < px:
            checks.append({"check": f"real {s}", "status": "info",
                           "detail": f"objetivo {w * led['equity']:.0f} USD no llega a 1 acción ({px:.2f} USD)"})
    return out, checks


def confirm_text(o: dict) -> str:
    return f"{o['side'].upper()} {int(o['qty'])} {o['symbol']} @ {o['limit_price']:.2f}"


# ── aprobación orden a orden ────────────────────────────────────────────────

def _get(uid: int, order_id: int) -> dict:
    o = get_db().one("SELECT * FROM fund_live_orders WHERE id=? AND user_id=?", (order_id, uid))
    if not o:
        raise LiveError("Orden no encontrada.")
    return o


async def _sent(order_id: int, res: dict) -> dict:
    """Guarda lo que devolvió IBKR: orden creada o avisos que la persona debe confirmar."""
    if res.get("reply_id"):
        get_db().execute("UPDATE fund_live_orders SET reply_id=?, warnings=? WHERE id=?",
                         (res["reply_id"], json.dumps(res["messages"], ensure_ascii=False), order_id))
        _set_status(order_id, "needs_confirmation", "IBKR pide confirmar avisos", " | ".join(res["messages"])[:2000])
    else:
        get_db().execute("UPDATE fund_live_orders SET reply_id=NULL, warnings=NULL WHERE id=?", (order_id,))
        _set_status(order_id, "submitted", "envío", f"IBKR orden {res['order_id']} ({res['status']})",
                    broker_order_id=res["order_id"])
    return get_db().one("SELECT * FROM fund_live_orders WHERE id=?", (order_id,))


async def approve(uid: int, order_id: int, confirm: str, run_finished: float, halted: bool, book: dict,
                  latest_run_id: int | None) -> dict:
    o = _get(uid, order_id)
    if o["status"] != "pending":
        raise LiveError(f"La orden está '{o['status']}', no se puede aprobar.")
    if confirm != confirm_text(o):
        _log(order_id, "aprobación", "rechazada: la confirmación no coincide")
        raise LiveError(f"Escribe exactamente: {confirm_text(o)}")

    def block(reason: str) -> None:
        _set_status(order_id, "blocked", "aprobación", reason)
        raise LiveError(reason)

    cfg = config(uid)
    if mode(uid) != "live":
        block("el fondo no está en modo real")
    if settings.data_mode != "live":
        block("el servidor usa datos simulados")
    if o["run_id"] != latest_run_id:
        block("hay una propuesta más reciente: aprueba las órdenes del último comité")
    if time.time() - run_finished > FRESH_SECONDS:
        block("la propuesta tiene más de 15 minutos: convoca un comité nuevo")
    if halted and o["side"] == "buy":
        block("fondo parado: solo se permiten ventas")
    rec = await refresh(uid)  # el registro del fondo tiene que estar al día antes de decidir
    if not rec["ok"]:
        block("no se pudo conciliar con IBKR: " + rec.get("error", ""))
    q = await market.quote(o["symbol"])
    if q.get("source") != LIVE_SOURCE:
        block("el precio actual no viene de una fuente real")
    if abs(q["price"] / o["ref_price"] - 1) > MAX_DRIFT:
        block(f"el precio se ha movido más de un {MAX_DRIFT:.0%} desde la propuesta")
    held = set(ledger(uid, {})["positions"]) - {o["symbol"]}
    prices = {s: x["price"] for s, x in (await market.quotes(sorted(held))).items()} if held else {}
    prices[o["symbol"]] = q["price"]
    led = ledger(uid, prices)
    if daily_check(uid, led["equity"])["breached"] and o["side"] == "buy":
        block("pérdida diaria máxima alcanzada")
    if o["side"] == "buy":
        if led["unreconciled"]:
            block("hay órdenes sin conciliar con IBKR: resuélvelas antes de comprar")
        why = live_gate(o["symbol"], None, book.get(o["symbol"]), order_cost_bps(cfg, o["qty"], o["limit_price"]))
        if why:
            block(why)
        if o["notional"] > cfg["max_order"] + 1e-6:
            block("supera el máximo por orden")
        if o["notional"] > led["cash"] - led["reserved"] + 1e-6:
            block("no queda capital asignado suficiente")
    elif o["qty"] > led["available_to_sell"].get(o["symbol"], 0) + 1e-9:
        block("el fondo no tiene esas acciones libres (nunca vende posiciones ajenas al fondo ni las ya en venta)")

    c = client_factory()
    try:
        st = await c.status()
        if not st["authenticated"]:
            block("el gateway de IBKR no tiene sesión iniciada")
        if cfg["account"] not in await c.accounts():
            block("la cuenta configurada no está en el gateway")
        conid = await c.conid(o["symbol"])
        if o["side"] == "sell":
            ibkr_qty = (await c.positions(cfg["account"])).get(conid, {}).get("qty", 0)
            if o["qty"] > ibkr_qty + 1e-9:
                block("IBKR muestra menos acciones de las que el fondo cree tener")
        res = await c.place_limit(cfg["account"], conid, o["side"], int(o["qty"]), o["limit_price"],
                                  coid=f"fincept-{uid}-{order_id}-{int(time.time())}")
    except IBKRError as e:
        _set_status(order_id, "error", "envío", str(e))
        raise LiveError(str(e)) from e
    finally:
        await c.close()
    return await _sent(order_id, res)


async def confirm_warnings(uid: int, order_id: int, run_finished: float, halted: bool) -> dict:
    """Segundo clic: la persona ha leído los avisos de IBKR y los confirma."""
    o = _get(uid, order_id)
    if o["status"] != "needs_confirmation" or not o["reply_id"]:
        raise LiveError(f"La orden está '{o['status']}': no hay avisos que confirmar.")
    if mode(uid) != "live" or (halted and o["side"] == "buy") or time.time() - run_finished > FRESH_SECONDS:
        _set_status(order_id, "expired", "avisos", "modo, parada o antigüedad ya no permiten enviarla")
        raise LiveError("La orden ya no se puede enviar: convoca un comité nuevo.")
    c = client_factory()
    try:
        res = await c.reply(o["reply_id"])
    except IBKRError as e:
        _set_status(order_id, "error", "confirmación de avisos", str(e))
        raise LiveError(str(e)) from e
    finally:
        await c.close()
    _log(order_id, "avisos confirmados por la persona", " | ".join(json.loads(o["warnings"] or "[]"))[:2000])
    return await _sent(order_id, res)


def reject(uid: int, order_id: int) -> dict:
    o = _get(uid, order_id)
    if o["status"] not in ("pending", "needs_confirmation"):
        raise LiveError(f"La orden está '{o['status']}'.")
    _set_status(order_id, "rejected", "decisión", "rechazada por la persona")
    return {"id": order_id, "status": "rejected"}


async def reconcile(uid: int, order_id: int, filled_qty: float, avg_price: float | None) -> dict:
    """La persona resuelve una orden que IBKR dejó de listar, con lo que ve en su cuenta de IBKR.

    Antes se envía la cancelación a IBKR: si la orden siguiera viva y se ejecutara después, el fondo
    tendría acciones que su registro no conoce."""
    o = _get(uid, order_id)
    if o["status"] != "unreconciled":
        raise LiveError(f"La orden está '{o['status']}': no hace falta conciliarla.")
    if not 0 <= filled_qty <= o["qty"]:
        raise LiveError(f"La cantidad ejecutada debe estar entre 0 y {o['qty']:g}.")
    if filled_qty and not (avg_price and avg_price > 0):
        raise LiveError("Indica el precio medio de ejecución.")
    try:
        c = client_factory()
        try:
            await c.cancel(config(uid)["account"], o["broker_order_id"])
            _log(order_id, "cancelación antes de conciliar", "enviada a IBKR")
        finally:
            await c.close()
    except IBKRError as e:  # p. ej. IBKR ya no la conoce: es lo esperable en una orden DAY caducada
        _log(order_id, "cancelación antes de conciliar", f"IBKR: {e}")
    status = "filled" if filled_qty == o["qty"] else "cancelled"
    _set_status(order_id, status, "conciliación manual", f"{filled_qty:g} ejecutadas a {avg_price or 0:g}",
                filled_qty=filled_qty, avg_price=avg_price if filled_qty else None)
    return _get(uid, order_id)


async def refresh(uid: int) -> dict:
    """Concilia con IBKR las órdenes enviadas. Una orden que IBKR ya no lista pasa a 'unreconciled':
    mientras haya alguna, no se compra (el capital podría estar ya gastado)."""
    sent = get_db().all("SELECT * FROM fund_live_orders WHERE user_id=? AND status IN ('submitted','partially_filled')",
                        (uid,))
    if not sent:
        return {"ok": True, "changed": 0}
    try:
        c = client_factory()
    except IBKRError as e:
        return {"ok": False, "changed": 0, "error": str(e)}
    try:
        book = await c.orders()
        if any(str(o["broker_order_id"]) not in book for o in sent):
            book |= await c.orders()  # IBKR a veces devuelve la lista incompleta en la primera llamada
    except IBKRError as e:
        return {"ok": False, "changed": 0, "error": str(e)}
    finally:
        await c.close()
    changed = 0
    for o in sent:
        b = book.get(str(o["broker_order_id"]))
        if not b:
            _set_status(o["id"], "unreconciled", "IBKR", "IBKR ya no lista esta orden: compruébala en tu cuenta")
            changed += 1
            continue
        status = {"Filled": "filled", "Cancelled": "cancelled", "Inactive": "cancelled"}.get(
            b["status"], "partially_filled" if b["filled"] > 0 else "submitted")
        if status != o["status"] or b["filled"] != o["filled_qty"]:
            _set_status(o["id"], status, "IBKR", f"{b['status']}: {b['filled']:g} a {b['avg_price']}",
                        filled_qty=b["filled"], avg_price=b["avg_price"])
            changed += 1
    return {"ok": True, "changed": changed}


async def cancel_open(uid: int, reason: str) -> int:
    """Parada de emergencia: caduca lo pendiente y cancela en IBKR lo enviado."""
    for st in ("pending", "needs_confirmation"):
        _audit_bulk(uid, st, "expired", reason)
    sent = get_db().all("SELECT * FROM fund_live_orders WHERE user_id=? AND status IN ('submitted','partially_filled')",
                        (uid,))
    if not sent:
        return 0
    n = 0
    try:
        c = client_factory()
    except IBKRError:
        return 0
    try:
        for o in sent:
            try:
                await c.cancel(config(uid)["account"], o["broker_order_id"])
                _log(o["id"], "cancelación", reason)
                n += 1
            except IBKRError as e:
                _log(o["id"], "cancelación", f"falló: {e}")
    finally:
        await c.close()
    await refresh(uid)  # refleja enseguida lo que IBKR ya canceló
    return n


async def status(uid: int, with_gateway: bool = True) -> dict:
    row = _row(uid)
    held = ledger(uid, {})["positions"]
    prices = {s: q["price"] for s, q in (await market.quotes(list(held))).items()} if held else {}
    return {"mode": row["mode"], "config": row["config"], "data_mode": settings.data_mode,
            "cost_bps": live_cost_bps(row["config"]) if row["config"] else None,
            "commission_plans": COMMISSION_PLANS,
            "gateway": await gateway_status(uid) if with_gateway else None,
            "ledger": ledger(uid, prices), "orders": orders(uid, 50),
            "tradable": sorted(a.symbol for a in A.UNIVERSE if a.symbol not in NOT_IN_IBKR),
            "rules": {"limit_band": LIMIT_BAND, "max_drift": MAX_DRIFT, "fresh_minutes": FRESH_SECONDS // 60}}
