from server import paper


def test_market_endpoints_sim(client, user):
    h = user["headers"]
    q = client.get("/market/price/aapl", headers=h).json()["data"]
    assert q["symbol"] == "AAPL" and q["price"] > 0 and q["source"] == "sim"
    hist = client.get("/market/history/MSFT?period=1y&interval=1d", headers=h).json()["data"]
    assert len(hist["candles"]) > 200 and {"t", "o", "h", "l", "c", "v"} <= set(hist["candles"][0])
    batch = client.get("/market/batch/prices?symbols=AAPL,MSFT,BTC-USD", headers=h).json()["data"]
    assert {b["symbol"] for b in batch} == {"AAPL", "MSFT", "BTC-USD"}
    s = client.get("/market/search?q=apple").json()["data"]
    assert s[0]["symbol"] == "AAPL"
    assert client.get("/market/price/BAD$SYM", headers=h).json()["success"] is False


def test_market_buy_then_oversell_rejected(client, user):
    h = user["headers"]
    r = client.post("/paper/orders", headers=h, json={"symbol": "AAPL", "side": "buy", "qty": 10}).json()
    assert r["success"] and r["data"]["status"] == "filled"
    acc = client.get("/paper/account", headers=h).json()["data"]
    pos = {p["symbol"]: p for p in acc["positions"]}
    assert pos["AAPL"]["qty"] == 10
    assert abs(acc["cash"] - (100_000 - 10 * r["data"]["filled_price"])) < 1e-6
    bad = client.post("/paper/orders", headers=h, json={"symbol": "AAPL", "side": "sell", "qty": 11}).json()
    assert bad["success"] is False and "no shorting" in bad["message"]


def test_buying_power_check(client, user):
    r = client.post("/paper/orders", headers=user["headers"],
                    json={"symbol": "BTC-USD", "side": "buy", "qty": 1000}).json()
    assert r["success"] is False and "insufficient buying power" in r["message"]


def test_limit_order_waits_then_matcher_fills(client, user):
    h = user["headers"]
    px = client.get("/market/price/NVDA", headers=h).json()["data"]["price"]
    limit = round(px * 0.5, 2)  # muy por debajo: queda pendiente
    o = client.post("/paper/orders", headers=h, json={"symbol": "NVDA", "side": "buy", "qty": 2, "type": "limit",
                                                       "limit_price": limit}).json()["data"]
    assert o["status"] == "open"
    # Simulamos que llega una cotización que cruza el límite (como haría el DataHub).
    client.portal.call(paper.matcher.on_quote, "market:quote:NVDA", {"symbol": "NVDA", "price": limit - 1})
    orders = client.get("/paper/orders", headers=h).json()["data"]
    filled = next(x for x in orders if x["id"] == o["id"])
    assert filled["status"] == "filled" and filled["filled_price"] == limit - 1


def test_cancel_open_order(client, user):
    h = user["headers"]
    o = client.post("/paper/orders", headers=h, json={"symbol": "MSFT", "side": "buy", "qty": 1, "type": "limit",
                                                       "limit_price": 1.0}).json()["data"]
    assert client.delete(f"/paper/orders/{o['id']}", headers=h).json()["data"]["status"] == "cancelled"
    again = client.delete(f"/paper/orders/{o['id']}", headers=h).json()
    assert again["success"] is False


def test_quantlib_and_backtest_routes(client, user):
    h = user["headers"]
    g = client.post("/quantlib/pricing/bs/greeks", headers=h,
                    json={"spot": 100, "strike": 100, "time_to_expiry": 1, "rate": 0.05, "volatility": 0.2}).json()
    assert abs(g["data"]["price"] - 10.4506) < 1e-3
    bt = client.post("/backtest/sma", headers=h, json={"symbol": "SPY", "period": "2y", "fast": 10, "slow": 30}).json()
    assert bt["success"] and bt["data"]["equity_curve"]


def test_sim_periods_are_slices_of_one_path():
    import asyncio

    from server.market.providers import SimProvider

    async def go():
        sim = SimProvider()
        h1, h2 = await sim.history("AAPL", "1y", "1d"), await sim.history("AAPL", "2y", "1d")
        c1, c2 = [c["c"] for c in h1["candles"]], [c["c"] for c in h2["candles"]]
        # mismo camino: el 1y es la cola del 2y (salvo el escalado al precio vivo, que es común)
        ratio = c2[-1] / c1[-1]
        assert len(c2) > len(c1) and all(abs(a * ratio - b) < 1e-6 * b for a, b in zip(c1, c2[-len(c1):]))
        wk = await sim.history("AAPL", "2y", "1wk")
        assert 95 <= len(wk["candles"]) <= 106 and wk["candles"][-1]["t"] > wk["candles"][0]["t"]
    asyncio.run(go())
