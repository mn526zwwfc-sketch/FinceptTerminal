"""Modo real con Interactive Brokers: todo contra un gateway simulado, nunca contra IBKR de verdad."""
import asyncio
import json
import time

import httpx
import pytest

from server.config import settings
from server.db import get_db
from server.fund import engine, live
from server.fund.ibkr import IBKRClient, IBKRError

CONIDS = {"SPY": 756733, "TLT": 15547841, "GLD": 51529211}
ACCOUNT = "DU123456"


class FakeGateway:
    def __init__(self):
        self.calls, self.orders, self.positions, self.authenticated, self.next_id = [], {}, {}, True, 1000
        self.sent = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.removeprefix("/v1/api")
        self.calls.append((req.method, path))
        if path == "/iserver/auth/status":
            return httpx.Response(200, json={"authenticated": self.authenticated, "connected": True})
        if path == "/iserver/accounts":
            return httpx.Response(200, json={"accounts": [ACCOUNT]})
        if path == "/iserver/secdef/search":
            sym = req.url.params["symbol"]
            return httpx.Response(200, json=[{"conid": str(CONIDS[sym]), "sections": [{"secType": "STK"}]}])
        if path == f"/iserver/account/{ACCOUNT}/orders" and req.method == "POST":
            self.sent.append(json.loads(req.content)["orders"][0])
            return httpx.Response(200, json=[{"id": "reply-1", "message": ["Aviso de precaución de IBKR"]}])
        if path == "/iserver/reply/reply-1":
            oid = str(self.next_id)
            self.next_id += 1
            o = self.sent[-1]
            self.orders[oid] = {"orderId": int(oid), "status": "Submitted", "filledQuantity": 0, "avgPrice": 0,
                                "_qty": o["quantity"], "_px": o["price"]}
            return httpx.Response(200, json=[{"order_id": oid, "order_status": "Submitted"}])
        if path == "/iserver/account/orders":
            return httpx.Response(200, json={"orders": [{k: v for k, v in o.items() if not k.startswith("_")}
                                                        for o in self.orders.values()]})
        if req.method == "DELETE" and path.startswith(f"/iserver/account/{ACCOUNT}/order/"):
            self.orders[path.rsplit("/", 1)[1]]["status"] = "Cancelled"
            return httpx.Response(200, json={"msg": "ok"})
        if path == f"/portfolio/{ACCOUNT}/positions/0":
            return httpx.Response(200, json=[{"conid": c, "position": q} for c, q in self.positions.items()])
        return httpx.Response(404, text="no such endpoint")

    def fill(self, oid: str):
        o = self.orders[oid]
        o.update(status="Filled", filledQuantity=o["_qty"], avgPrice=o["_px"])


@pytest.fixture
def gw(monkeypatch):
    g = FakeGateway()
    monkeypatch.setattr(live, "client_factory",
                        lambda: IBKRClient("https://localhost:5000/v1/api", transport=httpx.MockTransport(g.handler)))
    return g


@pytest.fixture
def real_prices(monkeypatch):
    px = {"SPY": 500.0, "TLT": 90.0, "GLD": 200.0, "BTC-USD": 60000.0}

    async def quote(sym, max_age=None):
        return {"symbol": sym, "price": px[sym], "source": "yahoo"}

    async def quotes(syms, max_age=None):
        return {s: await quote(s) for s in syms}
    monkeypatch.setattr(live.market, "quote", quote)
    monkeypatch.setattr(live.market, "quotes", quotes)
    return px


def _live_user(uid, monkeypatch, capital=10_000.0, max_order=1_000.0, real_data=True):
    if real_data:  # solo afecta a las comprobaciones: los precios los ponen los fixtures (sin red)
        monkeypatch.setattr(settings, "data_mode", "live")
    if live.mode(uid) != "live":
        live.set_config(uid, {"capital": capital, "max_order": max_order, "daily_loss_pct": 0.02, "account": ACCOUNT})
        get_db().execute("UPDATE fund_live SET mode='live' WHERE user_id=?", (uid,))


GOOD_BOOK = {"SPY": {"trained": True, "validated": True, "data_source": "yahoo"},
             "TLT": {"trained": True, "validated": True, "data_source": "sim"},
             "GLD": {"trained": True, "validated": False, "data_source": "yahoo"}}
VIEWS = {s: {"strategy": {"trained": True}} for s in GOOD_BOOK}


def run(coro):
    return asyncio.run(coro)


# ── configuración y activación ──────────────────────────────────────────────

def test_config_validation():
    with pytest.raises(live.LiveError, match="máximo por orden"):
        live.validate_config({"capital": 1000, "max_order": 2000, "daily_loss_pct": 0.02, "account": ACCOUNT})
    with pytest.raises(live.LiveError, match="pérdida diaria"):
        live.validate_config({"capital": 1000, "max_order": 100, "daily_loss_pct": 0.5, "account": ACCOUNT})
    with pytest.raises(live.LiveError, match="Cuenta"):
        live.validate_config({"capital": 1000, "max_order": 100, "daily_loss_pct": 0.02, "account": "x; drop"})
    assert live.validate_config({"capital": "1000", "max_order": 100, "daily_loss_pct": 0.02,
                                 "account": "du123456"})["account"] == "DU123456"


def test_gateway_must_be_local():
    with pytest.raises(IBKRError, match="loopback"):
        IBKRClient("https://ibkr.example.com/v1/api")


def test_live_mode_refuses_without_config_real_data_and_gateway(user, gw):
    gw.authenticated = False
    with pytest.raises(live.LiveError) as e:
        run(live.set_mode(user["id"], "live"))
    msg = str(e.value)
    assert "configura capital" in msg and "datos simulados" in msg and "sesión iniciada" in msg
    assert live.mode(user["id"]) == "paper"


def test_live_mode_turns_on_when_everything_is_ready(user, gw, monkeypatch):
    monkeypatch.setattr(settings, "data_mode", "live")
    live.set_config(user["id"], {"capital": 5000, "max_order": 500, "daily_loss_pct": 0.02, "account": ACCOUNT})
    assert run(live.set_mode(user["id"], "live"))["mode"] == "live"


# ── propuesta ───────────────────────────────────────────────────────────────

def test_plan_only_buys_validated_real_data_strategies(user, gw, monkeypatch, real_prices):
    uid = user["id"]
    _live_user(uid, monkeypatch, capital=10_000, max_order=1_000)
    target = {"SPY": 0.08, "TLT": 0.08, "GLD": 0.07, "BTC-USD": 0.05}  # bajo el 30 % de rotación
    src = {s: "yahoo" for s in target}
    orders, checks = live.plan(uid, 1, target, VIEWS, real_prices, src, GOOD_BOOK, None, engine.POLICY)
    assert [(o["symbol"], o["side"], o["qty"]) for o in orders] == [("SPY", "buy", 1)]  # 800 / 502,5
    reasons = {c["check"]: c["detail"] for c in checks if c["status"] == "blocked"}
    assert "datos simulados" in reasons["real TLT"] and "no validada" in reasons["real GLD"]
    assert "cripto" in reasons["real BTC-USD"]
    assert orders[0]["limit_price"] == round(500 * 1.005, 2)
    blocked, checks = live.plan(uid, 2, {"SPY": 0.3}, VIEWS, real_prices, {"SPY": "sim"}, GOOD_BOOK, None,
                                engine.POLICY)
    assert not blocked and "precio no real" in checks[-1]["detail"]


# ── aprobación orden a orden ────────────────────────────────────────────────

def _pending(uid, real_prices, monkeypatch, run_id=1, target=None, max_order=1_000.0):
    _live_user(uid, monkeypatch, max_order=max_order)
    orders, _ = live.plan(uid, run_id, target if target is not None else {"SPY": 0.3}, VIEWS, real_prices,
                          {"SPY": "yahoo"}, GOOD_BOOK, None, engine.POLICY)
    return orders[0]


def _approve(uid, o, run_id=1, finished=None, halted=False, confirm=None):
    return run(live.approve(uid, o["id"], confirm or live.confirm_text(o), finished or time.time(), halted,
                            GOOD_BOOK, run_id))


def _send(uid, o, run_id=1):
    """Aprobar + confirmar los avisos de IBKR (dos clics de la persona)."""
    first = _approve(uid, o, run_id)
    assert first["status"] == "needs_confirmation"
    return run(live.confirm_warnings(uid, o["id"], time.time(), False))


def test_approve_requires_exact_confirmation_and_a_second_click_for_ibkr_warnings(user, gw, monkeypatch, real_prices):
    uid = user["id"]
    o = _pending(uid, real_prices, monkeypatch)
    with pytest.raises(live.LiveError, match="Escribe exactamente"):
        _approve(uid, o, confirm="sí")
    assert live.orders(uid)[0]["status"] == "pending" and not gw.sent  # nada enviado
    text = live.confirm_text(o)
    assert text == "BUY 1 SPY @ 502.50"
    first = _approve(uid, o)
    assert first["status"] == "needs_confirmation" and "Aviso de precaución" in first["warnings"]
    assert gw.orders == {}  # IBKR no crea la orden hasta que la persona confirma los avisos
    sent = gw.sent[0]
    assert {k: v for k, v in sent.items() if k != "cOID"} == {"conid": CONIDS["SPY"], "orderType": "LMT",
                                                              "price": 502.5, "side": "BUY", "quantity": 1, "tif": "DAY"}
    assert sent["cOID"].startswith(f"fincept-{uid}-{o['id']}-")  # único aunque se reinicie la base de datos
    done = run(live.confirm_warnings(uid, o["id"], time.time(), False))
    assert done["status"] == "submitted" and done["broker_order_id"] == "1000"
    assert "avisos confirmados por la persona" in [d["action"] for d in live.orders(uid)[0]["detail"]]
    with pytest.raises(live.LiveError, match="submitted"):  # no se puede aprobar dos veces
        _approve(uid, o)


@pytest.mark.parametrize("case,reason", [
    ("stale", "15 minutos"), ("halted", "parado"), ("drift", "se ha movido"), ("paper", "modo real"),
    ("sim_data", "datos simulados"), ("logged_out", "sesión iniciada"), ("superseded", "más reciente"),
])
def test_approve_blocks_and_audits(user, gw, monkeypatch, real_prices, case, reason):
    uid = user["id"]
    o = _pending(uid, real_prices, monkeypatch)
    finished, halted, latest = time.time(), False, 1
    if case == "stale":
        finished -= 16 * 60
    elif case == "halted":
        halted = True
    elif case == "drift":
        real_prices["SPY"] = 510.0
    elif case == "paper":
        get_db().execute("UPDATE fund_live SET mode='paper' WHERE user_id=?", (uid,))
    elif case == "sim_data":
        monkeypatch.setattr(settings, "data_mode", "sim")
    elif case == "logged_out":
        gw.authenticated = False
    elif case == "superseded":
        latest = 2
    with pytest.raises(live.LiveError, match=reason):
        _approve(uid, o, run_id=latest, finished=finished, halted=halted)
    row = live.orders(uid)[0]
    assert row["status"] == "blocked" and reason in row["detail"][-1]["result"] and not gw.sent


def test_a_new_cycle_expires_older_pending_orders(user, gw, monkeypatch, real_prices):
    uid = user["id"]
    old = _pending(uid, real_prices, monkeypatch, run_id=1)
    new = _pending(uid, real_prices, monkeypatch, run_id=2)
    rows = {r["id"]: r for r in live.orders(uid)}
    assert rows[old["id"]]["status"] == "expired" and "ciclo #2" in rows[old["id"]]["detail"][-1]["result"]
    with pytest.raises(live.LiveError, match="expired"):  # la misma compra no se puede aprobar dos veces
        _approve(uid, old, run_id=2)
    assert _send(uid, new, run_id=2)["status"] == "submitted"


def test_fills_update_the_ledger_and_sells_never_exceed_free_fund_shares(user, gw, monkeypatch, real_prices):
    uid = user["id"]
    o = _pending(uid, real_prices, monkeypatch, target={"SPY": 0.1}, max_order=2_000)
    assert o["qty"] == 2
    _send(uid, o)
    gw.fill("1000")
    assert run(live.refresh(uid)) == {"ok": True, "changed": 1}
    led = live.ledger(uid, real_prices)
    assert led["positions"] == {"SPY": 2} and led["cash"] == pytest.approx(10_000 - 2 * 502.5)
    gw.positions = {CONIDS["SPY"]: 52}  # 50 son tuyas: el fondo solo puede vender las 2 que compró
    sell = live.plan(uid, 2, {}, VIEWS, real_prices, {"SPY": "yahoo"}, GOOD_BOOK, None, engine.POLICY)[0][0]
    assert (sell["side"], sell["qty"]) == ("sell", 2)
    _send(uid, sell, run_id=2)  # enviada, aún sin ejecutar
    led = live.ledger(uid, real_prices)
    assert led["selling"] == {"SPY": 2} and led["available_to_sell"] == {}
    again, checks = live.plan(uid, 3, {}, VIEWS, real_prices, {"SPY": "yahoo"}, GOOD_BOOK, None, engine.POLICY)
    assert again == []  # no vende otra vez las acciones que ya están en venta
    get_db().execute("UPDATE fund_live_orders SET status='pending', qty=5, run_id=3 WHERE id=?", (sell["id"],))
    bad = dict(sell, qty=5)  # manipulación: intentar vender más de lo que es del fondo
    with pytest.raises(live.LiveError, match="nunca vende posiciones ajenas"):
        _approve(uid, bad, run_id=3)


def test_orders_ibkr_stops_listing_block_buys_until_resolved(user, gw, monkeypatch, real_prices):
    uid = user["id"]
    o = _pending(uid, real_prices, monkeypatch)
    _send(uid, o)
    gw.orders.clear()  # p. ej. orden DAY de una sesión anterior del gateway
    assert run(live.refresh(uid))["changed"] == 1
    assert live.orders(uid)[0]["status"] == "unreconciled" and live.ledger(uid, real_prices)["unreconciled"] == 1
    orders, checks = live.plan(uid, 2, {"SPY": 0.3}, VIEWS, real_prices, {"SPY": "yahoo"}, GOOD_BOOK, None,
                               engine.POLICY)
    assert orders == [] and any("sin conciliar" in c["detail"] for c in checks)
    with pytest.raises(live.LiveError, match="precio medio"):
        live.reconcile(uid, o["id"], 1, None)
    done = live.reconcile(uid, o["id"], 1, 501.0)  # la persona mira su cuenta de IBKR: se ejecutó
    assert done["status"] == "filled" and live.ledger(uid, real_prices)["positions"] == {"SPY": 1}


def test_gateway_down_blocks_approval(user, gw, monkeypatch, real_prices):
    uid = user["id"]
    first = _pending(uid, real_prices, monkeypatch)
    _send(uid, first)
    o = _pending(uid, real_prices, monkeypatch, run_id=2)

    def down():
        raise IBKRError("gateway caído")
    monkeypatch.setattr(live, "client_factory", down)
    with pytest.raises(live.LiveError, match="conciliar"):
        _approve(uid, o, run_id=2)


def test_limits_cannot_change_while_live(user, monkeypatch):
    _live_user(user["id"], monkeypatch)
    with pytest.raises(live.LiveError, match="paper"):
        live.set_config(user["id"], {"capital": 1, "max_order": 1, "daily_loss_pct": 0.02, "account": ACCOUNT})


def test_emergency_stop_cancels_sent_orders_and_expires_pending(user, gw, monkeypatch, real_prices):
    uid = user["id"]
    o = _pending(uid, real_prices, monkeypatch)
    _send(uid, o)
    live.plan(uid, 2, {"SPY": 0.3}, VIEWS, real_prices, {"SPY": "yahoo"}, GOOD_BOOK, None, engine.POLICY)
    assert run(live.cancel_open(uid, "parada de emergencia")) == 1
    assert ("DELETE", f"/iserver/account/{ACCOUNT}/order/1000") in gw.calls
    assert {r["status"] for r in live.orders(uid)} == {"cancelled", "expired"}  # refrescado al momento


def test_daily_loss_limit(user, monkeypatch):
    _live_user(user["id"], monkeypatch)
    assert not live.daily_check(user["id"], 10_000)["breached"]  # fija el patrimonio de inicio del día
    assert not live.daily_check(user["id"], 9_850)["breached"]
    assert live.daily_check(user["id"], 9_790)["breached"]


# ── API y comité ────────────────────────────────────────────────────────────

def test_approval_requires_a_human_session(client, user, gw, monkeypatch, real_prices):
    o = _pending(user["id"], real_prices, monkeypatch)
    api_only = {"X-API-Key": user["api_key"]}
    r = client.post(f"/fund/live/orders/{o['id']}/approve", headers=api_only, json={"confirm": "x"})
    assert r.status_code == 403
    r = client.post(f"/fund/live/orders/{o['id']}/reject", headers=user["headers"]).json()
    assert r["success"] and r["data"]["status"] == "rejected"


def test_no_mcp_tool_can_approve_real_orders():
    from server.tools import REGISTRY
    assert not [n for n in REGISTRY if "live" in n or "approve" in n or "ibkr" in n]


def test_live_cycle_proposes_only_and_never_trades_paper(client, user, gw, monkeypatch):
    h = user["headers"]
    _live_user(user["id"], monkeypatch, real_data=False)  # servidor de tests: datos simulados, sin red
    data = client.post("/fund/cycle", headers=h, json={"execute": True}).json()["data"]
    rep = data["report"]
    assert rep["mode"] == "live" and rep["orders"] == [] and data["status"] == "proposed"
    # el servidor de tests usa históricos simulados: ninguna compra real puede pasar
    assert not [o for o in rep["live_orders"] if o["side"] == "buy"]
    assert any("simulad" in c["detail"] for c in rep["order_checks"] if c["check"].startswith("real "))
    assert rep["team"]["research"] and rep["team"]["committee"][-1]["agent"] == "Trader"
    r = client.post(f"/fund/runs/{data['id']}/execute", headers=h).json()
    assert not r["success"] and "modo real" in r["message"]
    st = client.get("/fund/live", headers=h).json()["data"]
    assert st["mode"] == "live" and st["config"]["account"] == ACCOUNT and st["gateway"]["account_ok"]
    assert st["data_mode"] == "sim"
    off = client.put("/fund/live/mode", headers=h, json={"mode": "paper"}).json()
    assert off["success"] and off["data"]["mode"] == "paper"
