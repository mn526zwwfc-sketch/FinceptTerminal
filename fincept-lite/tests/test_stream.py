"""Precios en tiempo real: Kraken (cripto) y Alpaca (acciones de EE. UU.), sin red."""
import asyncio
import time

from server.config import settings
from server.datahub import DataHub
from server.fund import live
from server.market.providers import MarketService
from server.market.stream import AlpacaStream, KrakenStream


def run(c):
    return asyncio.run(c)


def test_kraken_ticker_becomes_a_quote():
    k = KrakenStream(MarketService(), DataHub(), ["BTC-USD", "ETH-USD", "SPY"])
    assert k.pairs == {"BTC/USD": "BTC-USD", "ETH/USD": "ETH-USD"}
    msg = {"channel": "ticker", "type": "update", "data": [
        {"symbol": "BTC/USD", "last": 70000.5, "bid": 70000.0, "ask": 70001.0, "high": 71000, "low": 69000,
         "volume": 1234.5, "change": -700.0, "change_pct": -0.99},
        {"symbol": "DOGE/USD", "last": 0.1}]}
    (q,) = k.parse(msg)
    assert q["symbol"] == "BTC-USD" and q["price"] == 70000.5 and q["prev_close"] == 70700.5
    assert q["source"] == "kraken" and q["change_pct"] == -0.99
    assert k.parse({"channel": "status", "data": [{}]}) == []


def test_alpaca_trade_overlays_the_delayed_quote():
    m = MarketService()

    async def base(sym):
        return {"symbol": sym, "name": "SPDR S&P 500", "price": 750.0, "prev_close": 748.0, "high": 751.0,
                "low": 745.0, "currency": "USD", "source": "yahoo"}
    m.base_quote = base
    a = AlpacaStream(m, DataHub())
    (q,) = run(a.parse([{"T": "t", "S": "SPY", "p": 752.5, "s": 100}, {"T": "subscription", "trades": ["SPY"]}]))
    assert q["price"] == 752.5 and q["change"] == 4.5 and q["high"] == 752.5 and q["source"] == "alpaca"
    assert q["name"] == "SPDR S&P 500"
    assert [s for s in ["SPY", "BRK-B", "^GSPC", "EURUSD=X", "GC=F", "BTC-USD", "SAN.MC", "AMXB.MX"]
            if AlpacaStream.tradable(s)] == ["SPY", "BRK-B"]


def test_alpaca_needs_keys(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    assert not AlpacaStream(MarketService(), DataHub()).enabled()
    monkeypatch.setenv("ALPACA_API_KEY", "k")
    monkeypatch.setenv("ALPACA_API_SECRET", "s")
    assert AlpacaStream(MarketService(), DataHub()).enabled()


def test_fresh_ticks_win_and_stale_ticks_are_ignored(monkeypatch):
    monkeypatch.setattr(settings, "data_mode", "live")
    m = MarketService()

    async def delayed(method, *a):
        return {"symbol": "BTC-USD", "price": 1.0, "source": "yahoo", "ts": int(time.time())}
    m._with_fallback = delayed
    m.set_stream_quote({"symbol": "BTC-USD", "price": 70000.0, "source": "kraken", "ts": int(time.time())})
    assert run(m.quote("BTC-USD"))["source"] == "kraken"
    m.set_stream_quote({"symbol": "BTC-USD", "price": 70000.0, "source": "kraken", "ts": int(time.time()) - 60})
    assert run(m.quote("BTC-USD"))["source"] == "kraken"  # par tranquilo, flujo vivo: su último precio vale
    m._alive["kraken"] = time.time() - 60
    assert run(m.quote("BTC-USD"))["source"] == "yahoo"  # flujo caído: vuelve a la cotización con retraso


def test_ticks_are_published_only_to_watched_topics():
    hub, m = DataHub(), MarketService()
    k = KrakenStream(m, hub, ["BTC-USD"])
    q = {"symbol": "BTC-USD", "price": 1.0, "source": "kraken", "ts": int(time.time())}

    async def go():
        await k.emit(q)
        assert "market:quote:BTC-USD" not in hub.topics and m.stream_quote("BTC-USD") == q
        await hub.publish("market:quote:BTC-USD", {"price": 0})
        k._last_pub.clear()
        await k.emit(q)
        assert hub.peek("market:quote:BTC-USD") == q
        await k.emit(dict(q, price=2.0))  # demasiado seguido: se guarda pero no se publica
        assert hub.peek("market:quote:BTC-USD") == q and m.stream_quote("BTC-USD")["price"] == 2.0
    run(go())
    assert k.status()["ticks"] == 3


def test_real_time_sources_count_as_real_prices_for_live_trading():
    assert {"yahoo", "alpaca", "kraken"} == live.REAL_SOURCES and "sim" not in live.REAL_SOURCES
