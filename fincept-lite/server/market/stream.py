"""Precios en tiempo real por WebSocket (como los `trading/websocket/*` del terminal original).

* **Kraken** (cripto, sin clave): canal público `ticker` de wss://ws.kraken.com/v2.
* **Alpaca** (acciones y ETF de EE. UU., con tu clave gratuita): operaciones del feed IEX en
  wss://stream.data.alpaca.markets/v2/iex. IEX es una sola bolsa: el precio es real y al instante, pero
  no es la cinta consolidada. Claves en ALPACA_API_KEY y ALPACA_API_SECRET.

Cada tick actualiza la cotización del servicio de mercado y se publica en el DataHub
(`market:quote:<SYM>`), así que toda la terminal lo ve: pantallas, cartera en paper y fondo.
Si un flujo se cae, se reconecta con espera creciente y las cotizaciones vuelven solas a Yahoo.
FINCEPT_STREAMS=0 los desactiva.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time

log = logging.getLogger("fincept.stream")
STALE_SECONDS = 20.0  # un tick más viejo que esto ya no se considera tiempo real
REAL_TIME_SOURCES = {"kraken", "alpaca"}
MIN_PUBLISH_GAP = 0.5  # segundos entre publicaciones del mismo símbolo


class Stream:
    """Conexión WebSocket con reconexión. Las subclases implementan `_session` y `handle`."""

    name = "stream"
    url = ""

    def __init__(self, market, hub) -> None:
        self.market, self.hub = market, hub
        self.state, self.ticks, self.last_tick, self.error = "apagado", 0, 0.0, None
        self._last_pub: dict[str, float] = {}

    def enabled(self) -> bool:
        return True

    def status(self) -> dict:
        return {"state": self.state, "ticks": self.ticks, "error": self.error,
                "last_tick_age": round(time.time() - self.last_tick, 1) if self.last_tick else None}

    async def emit(self, quote: dict) -> None:
        """Guarda el tick y lo publica (con un tope de frecuencia por símbolo)."""
        sym = quote["symbol"]
        self.ticks += 1
        self.last_tick = time.time()
        self.market.set_stream_quote(quote)
        if self.last_tick - self._last_pub.get(sym, 0.0) >= MIN_PUBLISH_GAP:
            self._last_pub[sym] = self.last_tick
            topic = f"market:quote:{sym}"
            if topic in self.hub.topics:  # solo si alguien lo mira o lo ha mirado
                await self.hub.publish(topic, quote)

    async def run(self) -> None:
        import websockets
        wait = 2.0
        while True:
            if not self.enabled():
                self.state = "sin clave"
                await asyncio.sleep(30)
                continue
            try:
                self.state = "conectando"
                async with websockets.connect(self.url, open_timeout=15, ping_interval=20) as ws:
                    await self._session(ws)
            except asyncio.CancelledError:
                self.state = "apagado"
                raise
            except Exception as e:  # red, cierre del servidor, mensaje inesperado: se reconecta
                self.error = f"{type(e).__name__}: {str(e)[:120]}"
                log.warning("%s: %s", self.name, self.error)
            self.state = "reconectando"
            await asyncio.sleep(wait)
            wait = min(wait * 2, 60.0)
            if time.time() - self.last_tick < 60:
                wait = 2.0

    async def _session(self, ws) -> None:
        raise NotImplementedError


class KrakenStream(Stream):
    name, url = "kraken", "wss://ws.kraken.com/v2"

    def __init__(self, market, hub, symbols: list[str]) -> None:
        super().__init__(market, hub)
        self.pairs = {s.replace("-USD", "/USD"): s for s in symbols if s.endswith("-USD")}

    def parse(self, msg: dict) -> list[dict]:
        if msg.get("channel") != "ticker":
            return []
        out = []
        for d in msg.get("data") or []:
            sym = self.pairs.get(d.get("symbol"))
            last = d.get("last")
            if not sym or not last:
                continue
            chg = float(d.get("change") or 0.0)  # variación de las últimas 24 h
            out.append({"symbol": sym, "name": sym.replace("-USD", "") + " / USD", "price": float(last),
                        "prev_close": float(last) - chg, "change": round(chg, 6),
                        "change_pct": round(float(d.get("change_pct") or 0.0), 4), "open": float(last) - chg,
                        "high": d.get("high"), "low": d.get("low"), "volume": d.get("volume"),
                        "bid": d.get("bid"), "ask": d.get("ask"), "currency": "USD", "exchange": "Kraken (24 h)",
                        "type": "CRYPTOCURRENCY", "ts": int(time.time()), "source": "kraken"})
        return out

    async def _session(self, ws) -> None:
        await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": list(self.pairs)}}))
        self.state, self.error = "en vivo", None
        async for raw in ws:
            for q in self.parse(json.loads(raw)):
                await self.emit(q)


class AlpacaStream(Stream):
    name, url = "alpaca", "wss://stream.data.alpaca.markets/v2/iex"
    MAX_SYMBOLS = 30  # límite del plan gratuito

    def __init__(self, market, hub) -> None:
        super().__init__(market, hub)
        self.subscribed: set[str] = set()

    def enabled(self) -> bool:
        return bool(os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_API_SECRET"))

    @staticmethod
    def tradable(symbol: str) -> bool:
        """Acciones y ETF de EE. UU.: sin índices (^), divisas (=X), futuros (=F), cripto ni sufijo de bolsa."""
        return symbol.replace("-", "").isalnum() and not symbol.endswith("-USD") and "." not in symbol \
            and len(symbol) <= 6

    def wanted(self) -> set[str]:
        syms = [t.split(":", 2)[2] for t, st in self.hub.topics.items() if t.startswith("market:quote:") and st.subscribers]
        return set(sorted(s for s in syms if self.tradable(s))[: self.MAX_SYMBOLS])

    async def parse(self, msgs: list[dict]) -> list[dict]:
        out = []
        for m in msgs:
            if m.get("T") != "t" or not m.get("p"):
                continue
            base = await self.market.base_quote(m["S"])  # nombre, cierre previo, rango del día… (de Yahoo)
            if not base:
                continue
            price, prev = float(m["p"]), base.get("prev_close") or float(m["p"])
            out.append({**base, "price": price, "change": round(price - prev, 6),
                        "change_pct": round((price / prev - 1) * 100, 4) if prev else 0.0,
                        "high": max(base.get("high") or price, price), "low": min(base.get("low") or price, price),
                        "exchange": "IEX (Alpaca)", "ts": int(time.time()), "source": "alpaca"})
        return out

    async def _session(self, ws) -> None:
        await ws.send(json.dumps({"action": "auth", "key": os.environ["ALPACA_API_KEY"],
                                  "secret": os.environ["ALPACA_API_SECRET"]}))
        self.subscribed = set()
        last_sync = 0.0
        while True:
            if time.time() - last_sync > 5:  # sigue a lo que la terminal está mirando
                last_sync = time.time()
                want = self.wanted()
                if want - self.subscribed:
                    await ws.send(json.dumps({"action": "subscribe", "trades": sorted(want - self.subscribed)}))
                if self.subscribed - want:
                    await ws.send(json.dumps({"action": "unsubscribe", "trades": sorted(self.subscribed - want)}))
                self.subscribed = want
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            msgs = json.loads(raw)
            for m in msgs:
                if m.get("T") == "error":
                    raise RuntimeError(f"Alpaca: {m.get('msg')} ({m.get('code')})")
                if m.get("T") == "success" and m.get("msg") == "authenticated":
                    self.state, self.error = "en vivo", None
            for q in await self.parse(msgs):
                await self.emit(q)


class StreamManager:
    def __init__(self) -> None:
        self.streams: list[Stream] = []
        self._tasks: list[asyncio.Task] = []

    def start(self, market, hub, crypto_symbols: list[str]) -> None:
        if os.environ.get("FINCEPT_STREAMS", "1") == "0":
            return
        self.streams = [KrakenStream(market, hub, crypto_symbols), AlpacaStream(market, hub)]
        self._tasks = [asyncio.create_task(s.run()) for s in self.streams]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks, self.streams = [], []

    def status(self) -> dict:
        return {s.name: s.status() for s in self.streams}


streams = StreamManager()
