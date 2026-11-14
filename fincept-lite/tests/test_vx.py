"""Monitores multi-mercado y ficha de instrumento (/vx) en modo simulado."""
import pytest

from server import universe as U


def test_universe_covers_every_asset_class(client, user):
    cls = client.get("/vx/universe", headers=user["headers"]).json()["data"]
    assert [c["id"] for c in cls] == ["indices", "acciones", "divisas", "tasas", "materias", "cripto", "etf"]
    assert len(U.all_symbols()) > 90 and U.find("USDMXN=X")["group"] == "Peso mexicano"


@pytest.mark.parametrize("cls", [c["id"] for c in U.CLASSES])
def test_monitor(client, user, cls):
    d = client.get(f"/vx/monitor/{cls}", headers=user["headers"]).json()["data"]
    assert len(d["rows"]) == len(U.symbols(cls)) and d["sources"] == ["sim"]
    r = d["rows"][0]
    assert r["last"] > 0 and len(r["spark"]) == 30 and 0 <= r["pos52"] <= 1 and r["lo52"] <= r["last"] <= r["hi52"]
    if cls == "tasas":
        assert d["rows"][0]["is_yield"] and d["curve"] is None  # con datos simulados no se dibuja una curva
    if cls == "divisas":
        m = d["cross"]
        i, j = m["ccys"].index("USD"), m["ccys"].index("MXN")
        usdmxn = next(x["last"] for x in d["rows"] if x["symbol"] == "USDMXN=X")
        assert m["matrix"][i][j] == pytest.approx(usdmxn, rel=1e-4) and m["matrix"][i][i] == 1


def test_security_card_and_fund_context(client, user):
    d = client.get("/vx/security/SPY", headers=user["headers"]).json()["data"]
    assert d["class"] == "etf" and len(d["candles"]) == 260 and len(d["candles"][0]) == 6
    st = d["stats"]
    assert st["sma200"] and 0 <= st["rsi14"] <= 100 and st["max_drawdown"] <= 0 and st["beta"] is not None
    assert st["signals"]["sadf"] is not None and d["fund"]["desk"] == "equities"
    wk = client.get("/vx/security/SPY?period=5y", headers=user["headers"]).json()["data"]
    assert wk["interval"] == "1wk" and len(wk["candles"]) > 200
    assert client.get("/vx/security/AAPL", headers=user["headers"]).json()["data"]["fund"] is None
    assert client.get("/vx/security/BAD SYMBOL!", headers=user["headers"]).status_code == 422


def test_news_macro_kb_lab(client, user):
    assert client.get("/vx/news", headers=user["headers"]).json()["data"][0]["title"]
    m = client.get("/vx/macro", headers=user["headers"]).json()["data"]
    assert [i["id"] for i in m["indicators"]] == ["fed", "unemployment", "inflation"] and m["curve"] is None
    assert len(client.get("/vx/kb", headers=user["headers"]).json()["data"]) > 80
    lab = client.get("/vx/lab", headers=user["headers"]).json()["data"]
    names = {f["name"] for f in lab}
    assert len(lab) == 37 and not names & {"min_varianza", "mejora_sharpe"}  # sin Markowitz
    assert all("error" not in f["example_result"] for f in lab)


def test_fund_cycle_and_actions_through_the_engine(client, user):
    before = client.get("/vx/fund", headers=user["headers"]).json()["data"]
    assert before["run"] is None and len(before["agents"]) == 7 and before["mode"] == "paper"
    run = client.post("/fund/cycle", headers=user["headers"], json={}).json()["data"]
    d = client.get("/vx/fund", headers=user["headers"]).json()["data"]
    assert d["run"]["id"] == run["id"] and d["training"]["summary"]["trained"] > 0 and d["run"]["report"]["team"]
    ctx = client.get("/vx/security/SPY", headers=user["headers"]).json()["data"]["fund"]
    assert ctx["view"]["verdict"] in {"alcista", "bajista", "dividido"} and "book" in ctx
    o = client.post("/paper/orders", headers=user["headers"], json={"symbol": "SPY", "side": "buy", "qty": 1}).json()
    assert o["success"] and client.get("/paper/account", headers=user["headers"]).json()["data"]["positions"]


def test_yield_curve_from_real_yields():
    from server import vx as api
    rows = [{"symbol": s, "last": y, "source": "yahoo"} for s, y in
            [("^IRX", 3.72), ("^FVX", 3.80), ("^TNX", 4.15), ("^TYX", 4.70)]]
    c = api.yield_curve(rows)
    assert [p["tenor"] for p in c["points"]] == [0.25, 5.0, 10.0, 30.0] and c["slope_10y_3m"] == pytest.approx(0.43)
    assert len(c["fit"]) == 11 and all(2 < p["yield"] < 6 for p in c["fit"])
    assert api.yield_curve([dict(r, source="sim") for r in rows]) is None
