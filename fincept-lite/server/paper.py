"""Paper trading: réplica de trading/PaperTrading + OrderMatcher.

* Cuenta simulada por usuario (100.000 USD), posiciones con precio medio,
  P&L realizado / no realizado.
* Órdenes market (se llenan al instante), limit y stop (quedan pendientes).
* OrderMatcher: escucha el tópico market:quote:* del DataHub y ejecuta las
  órdenes pendientes cuando el precio cruza el límite / stop. Mantiene una
  suscripción interna a los símbolos con órdenes abiertas para que el hub los
  siga refrescando aunque ninguna pantalla los muestre.
* Cada cambio se publica en `paper:<uid>:account` (push_only).
"""

from __future__ import annotations

import time

from .datahub import Subscriber, hub
from .db import get_db
from .market.providers import market, normalize_symbol

INITIAL_CASH = 100_000.0


class OrderError(ValueError):
    pass


def _ensure_account(uid: int) -> dict:
    db = get_db()
    acc = db.one("SELECT * FROM paper_accounts WHERE user_id=?", (uid,))
    if not acc:
        db.execute("INSERT INTO paper_accounts(user_id, cash, initial_cash, realized_pnl, created_at) VALUES (?,?,?,0,?)",
                   (uid, INITIAL_CASH, INITIAL_CASH, time.time()))
        acc = db.one("SELECT * FROM paper_accounts WHERE user_id=?", (uid,))
    return acc


async def account(uid: int) -> dict:
    acc = _ensure_account(uid)
    db = get_db()
    positions = db.all("SELECT symbol, qty, avg_price FROM paper_positions WHERE user_id=? AND qty<>0", (uid,))
    quotes = await market.quotes([p["symbol"] for p in positions], max_age=30) if positions else {}
    mv_total, upnl_total = 0.0, 0.0
    for p in positions:
        last = quotes.get(p["symbol"], {}).get("price", p["avg_price"])
        p["last"] = last
        p["market_value"] = last * p["qty"]
        p["unrealized_pnl"] = (last - p["avg_price"]) * p["qty"]
        p["unrealized_pct"] = (last / p["avg_price"] - 1) * 100 if p["avg_price"] else 0.0
        p["change_pct"] = quotes.get(p["symbol"], {}).get("change_pct", 0.0)
        mv_total += p["market_value"]
        upnl_total += p["unrealized_pnl"]
    equity = acc["cash"] + mv_total
    open_orders = db.one("SELECT COUNT(*) AS n FROM paper_orders WHERE user_id=? AND status='open'", (uid,))["n"]
    return {
        "cash": acc["cash"], "initial_cash": acc["initial_cash"], "equity": equity,
        "market_value": mv_total, "unrealized_pnl": upnl_total, "realized_pnl": acc["realized_pnl"],
        "total_pnl": equity - acc["initial_cash"], "total_pnl_pct": (equity / acc["initial_cash"] - 1) * 100,
        "positions": positions, "open_orders": open_orders, "ts": int(time.time()),
    }


def list_orders(uid: int, status: str | None = None, limit: int = 100) -> list[dict]:
    if status:
        return get_db().all("SELECT * FROM paper_orders WHERE user_id=? AND status=? ORDER BY id DESC LIMIT ?",
                            (uid, status, limit))
    return get_db().all("SELECT * FROM paper_orders WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))


async def publish_account(uid: int) -> None:
    await hub.publish(f"paper:{uid}:account", {**(await account(uid)), "orders": list_orders(uid, limit=30)})


def _fill(order_id: int, price: float) -> dict:
    """Ejecuta una orden de forma atómica. Devuelve la orden actualizada."""
    db = get_db()
    with db.transaction() as conn:
        o = dict(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())
        if o["status"] != "open":
            return o
        uid, sym, qty = o["user_id"], o["symbol"], o["qty"]
        acc = conn.execute("SELECT * FROM paper_accounts WHERE user_id=?", (uid,)).fetchone()
        pos = conn.execute("SELECT * FROM paper_positions WHERE user_id=? AND symbol=?", (uid, sym)).fetchone()
        held, avg = (pos["qty"], pos["avg_price"]) if pos else (0.0, 0.0)
        cost = qty * price
        if o["side"] == "buy":
            if cost > acc["cash"] + 1e-9:
                conn.execute("UPDATE paper_orders SET status='rejected', note=? WHERE id=?",
                             (f"insufficient buying power: need {cost:.2f}, cash {acc['cash']:.2f}", order_id))
                return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())
            new_qty = held + qty
            new_avg = (held * avg + cost) / new_qty
            conn.execute("UPDATE paper_accounts SET cash=cash-? WHERE user_id=?", (cost, uid))
        else:
            if qty > held + 1e-9:
                conn.execute("UPDATE paper_orders SET status='rejected', note=? WHERE id=?",
                             (f"cannot sell {qty:g}: position is {held:g} (no shorting)", order_id))
                return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())
            new_qty, new_avg = held - qty, avg
            conn.execute("UPDATE paper_accounts SET cash=cash+?, realized_pnl=realized_pnl+? WHERE user_id=?",
                         (cost, (price - avg) * qty, uid))
        conn.execute("INSERT OR REPLACE INTO paper_positions(user_id, symbol, qty, avg_price) VALUES (?,?,?,?)",
                     (uid, sym, new_qty, new_avg if new_qty else 0.0))
        conn.execute("UPDATE paper_orders SET status='filled', filled_price=?, filled_at=? WHERE id=?",
                     (price, time.time(), order_id))
        return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?", (order_id,)).fetchone())


async def place_order(uid: int, symbol: str, side: str, qty: float, order_type: str = "market",
                      limit_price: float | None = None, stop_price: float | None = None, source: str = "ui") -> dict:
    try:
        symbol = normalize_symbol(symbol)
    except ValueError as e:
        raise OrderError(str(e)) from e
    side, order_type = side.lower(), order_type.lower()
    if side not in {"buy", "sell"}:
        raise OrderError("side must be buy or sell")
    if order_type not in {"market", "limit", "stop"}:
        raise OrderError("type must be market, limit or stop")
    if not qty or qty <= 0 or qty > 1e7:
        raise OrderError("qty must be > 0")
    if order_type == "limit" and (not limit_price or limit_price <= 0):
        raise OrderError("limit orders need limit_price > 0")
    if order_type == "stop" and (not stop_price or stop_price <= 0):
        raise OrderError("stop orders need stop_price > 0")
    _ensure_account(uid)
    q = await market.quote(symbol, max_age=2)
    cur = get_db().execute(
        "INSERT INTO paper_orders(user_id, symbol, side, qty, type, limit_price, stop_price, status, created_at, source)"
        " VALUES (?,?,?,?,?,?,?,'open',?,?)",
        (uid, symbol, side, qty, order_type, limit_price, stop_price, time.time(), source),
    )
    oid = cur.lastrowid
    order = get_db().one("SELECT * FROM paper_orders WHERE id=?", (oid,))
    trigger = matcher.trigger_price(order, q["price"])
    if trigger is not None:
        order = _fill(oid, trigger)
    else:
        await matcher.watch(symbol)
    await publish_account(uid)
    order["quote_price"] = q["price"]
    order["quote_source"] = q["source"]
    return order


async def cancel_order(uid: int, order_id: int) -> dict:
    o = get_db().one("SELECT * FROM paper_orders WHERE id=? AND user_id=?", (order_id, uid))
    if not o:
        raise OrderError("order not found")
    if o["status"] != "open":
        raise OrderError(f"order is {o['status']}, cannot cancel")
    get_db().execute("UPDATE paper_orders SET status='cancelled' WHERE id=?", (order_id,))
    await publish_account(uid)
    return get_db().one("SELECT * FROM paper_orders WHERE id=?", (order_id,))


async def reset(uid: int) -> dict:
    db = get_db()
    db.execute("DELETE FROM paper_positions WHERE user_id=?", (uid,))
    db.execute("UPDATE paper_orders SET status='cancelled' WHERE user_id=? AND status='open'", (uid,))
    db.execute("DELETE FROM paper_accounts WHERE user_id=?", (uid,))
    await publish_account(uid)
    return await account(uid)


class OrderMatcher:
    def __init__(self) -> None:
        self._subs: dict[str, Subscriber] = {}

    @staticmethod
    def trigger_price(o: dict, price: float) -> float | None:
        """Precio de ejecución si la orden es ejecutable ahora; None si no."""
        if o["type"] == "market":
            return price
        if o["type"] == "limit":
            if o["side"] == "buy" and price <= o["limit_price"]:
                return price
            if o["side"] == "sell" and price >= o["limit_price"]:
                return price
        if o["type"] == "stop":
            if o["side"] == "buy" and price >= o["stop_price"]:
                return price
            if o["side"] == "sell" and price <= o["stop_price"]:
                return price
        return None

    async def watch(self, symbol: str) -> None:
        if symbol not in self._subs:
            async def _noop(_msg: dict) -> None:
                return None
            sub = Subscriber(_noop, label=f"matcher:{symbol}")
            self._subs[symbol] = sub
            await hub.subscribe(f"market:quote:{symbol}", sub)

    async def on_quote(self, topic: str, quote: dict) -> None:
        symbol = topic.rsplit(":", 1)[-1]
        orders = get_db().all("SELECT * FROM paper_orders WHERE symbol=? AND status='open'", (symbol,))
        touched = set()
        for o in orders:
            px = self.trigger_price(o, quote["price"])
            if px is not None:
                _fill(o["id"], px)
                touched.add(o["user_id"])
        for uid in touched:
            await publish_account(uid)
        if not get_db().one("SELECT id FROM paper_orders WHERE symbol=? AND status='open' LIMIT 1", (symbol,)):
            sub = self._subs.pop(symbol, None)
            if sub:
                hub.unsubscribe(topic, sub)

    async def restore(self) -> None:
        for row in get_db().all("SELECT DISTINCT symbol FROM paper_orders WHERE status='open'"):
            await self.watch(row["symbol"])


matcher = OrderMatcher()
