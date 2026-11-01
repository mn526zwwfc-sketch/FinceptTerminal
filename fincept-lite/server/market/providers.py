"""Proveedores de datos de mercado.

Fincept resuelve las cotizaciones de dos formas: el backend expone
/market/price|history|search (respaldado por yfinance) y el terminal también
ejecuta scripts Python con yfinance localmente. Aquí replicamos ambas ideas con
dos proveedores intercambiables:

* YahooProvider — HTTP directo a los endpoints públicos de Yahoo Finance
  (v8/chart y v1/search). Sin API key.
* SimProvider   — mercado simulado (movimiento browniano geométrico) con
  semilla por símbolo: funciona sin internet y hace los tests deterministas.

MarketService elige proveedor según FINCEPT_DATA_MODE y cae al simulador si
Yahoo falla; cada respuesta lleva "source" para que la UI lo muestre.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import random
import time
from typing import Any

import httpx

from ..config import settings
from ..db import get_db

UA = "Mozilla/5.0 (compatible; FinceptLite/0.1; +https://github.com/Fincept-Corporation/FinceptTerminal)"

PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"}
INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo"}
DEFAULT_INTERVAL = {"1d": "5m", "5d": "15m", "1mo": "1h", "3mo": "1d", "6mo": "1d", "1y": "1d", "2y": "1wk",
                    "5y": "1wk", "10y": "1mo", "max": "1mo"}

# Precios base del simulador (aprox.) y nombres para símbolos conocidos.
SIM_UNIVERSE: dict[str, tuple[str, float, float]] = {
    # symbol: (name, base price, annual vol)
    "AAPL": ("Apple Inc.", 230.0, 0.28), "MSFT": ("Microsoft Corporation", 430.0, 0.25),
    "NVDA": ("NVIDIA Corporation", 140.0, 0.50), "AMZN": ("Amazon.com, Inc.", 200.0, 0.32),
    "GOOGL": ("Alphabet Inc.", 175.0, 0.30), "META": ("Meta Platforms, Inc.", 580.0, 0.38),
    "TSLA": ("Tesla, Inc.", 250.0, 0.60), "JPM": ("JPMorgan Chase & Co.", 220.0, 0.22),
    "V": ("Visa Inc.", 290.0, 0.20), "XOM": ("Exxon Mobil Corporation", 115.0, 0.24),
    "SPY": ("SPDR S&P 500 ETF", 580.0, 0.16), "QQQ": ("Invesco QQQ Trust", 500.0, 0.22),
    "^GSPC": ("S&P 500", 5800.0, 0.16), "^DJI": ("Dow Jones Industrial Average", 42000.0, 0.14),
    "^IXIC": ("NASDAQ Composite", 18500.0, 0.22), "^RUT": ("Russell 2000", 2200.0, 0.24),
    "^VIX": ("CBOE Volatility Index", 17.0, 0.90), "^FTSE": ("FTSE 100", 8200.0, 0.13),
    "^GDAXI": ("DAX", 19500.0, 0.17), "^IBEX": ("IBEX 35", 11800.0, 0.18),
    "^N225": ("Nikkei 225", 39000.0, 0.22), "^HSI": ("Hang Seng Index", 20000.0, 0.26),
    "^TNX": ("CBOE 10Y Treasury Yield", 4.2, 0.30),
    "EURUSD=X": ("EUR/USD", 1.08, 0.07), "GBPUSD=X": ("GBP/USD", 1.29, 0.08),
    "USDJPY=X": ("USD/JPY", 150.0, 0.10), "USDMXN=X": ("USD/MXN", 19.5, 0.12),
    "GC=F": ("Gold Futures", 2650.0, 0.15), "SI=F": ("Silver Futures", 31.0, 0.28),
    "CL=F": ("Crude Oil Futures", 72.0, 0.35), "NG=F": ("Natural Gas Futures", 2.6, 0.60),
    "BTC-USD": ("Bitcoin USD", 68000.0, 0.55), "ETH-USD": ("Ethereum USD", 2600.0, 0.70),
    "SOL-USD": ("Solana USD", 160.0, 0.90),
    "SAN.MC": ("Banco Santander, S.A.", 8.5, 0.30), "BBVA.MC": ("Banco Bilbao Vizcaya Argentaria", 11.5, 0.30),
    "ITX.MC": ("Industria de Diseño Textil, S.A.", 50.0, 0.25), "IBE.MC": ("Iberdrola, S.A.", 14.0, 0.20),
    "TEF.MC": ("Telefónica, S.A.", 4.3, 0.22), "REP.MC": ("Repsol, S.A.", 12.5, 0.28),
}


class ProviderError(Exception):
    pass


def _seed(symbol: str) -> int:
    return int(hashlib.sha256(symbol.encode()).hexdigest()[:12], 16)


def _quote_from_candles(symbol: str, name: str, candles: list[dict], prev_close: float, currency: str,
                        exchange: str, source: str) -> dict:
    last = candles[-1]
    price = last["c"]
    day = [c for c in candles if c["t"] >= candles[-1]["t"] - 86400] or candles[-1:]
    change = price - prev_close
    return {
        "symbol": symbol, "name": name, "price": round(price, 6), "prev_close": round(prev_close, 6),
        "change": round(change, 6), "change_pct": round(change / prev_close * 100, 4) if prev_close else 0.0,
        "open": day[0]["o"], "high": max(c["h"] for c in day), "low": min(c["l"] for c in day),
        "volume": sum(c["v"] for c in day), "currency": currency, "exchange": exchange,
        "ts": int(time.time()), "source": source,
    }


# ── Simulador ────────────────────────────────────────────────────────────────

class SimProvider:
    """GBM determinista por símbolo. El precio "vivo" avanza con el reloj."""

    name = "sim"

    def __init__(self) -> None:
        self._state: dict[str, dict[str, float]] = {}
        self._range52: dict[tuple[str, int], tuple[float, float]] = {}
        self._paths: dict[tuple[str, str, int], list[tuple]] = {}

    def _params(self, symbol: str) -> tuple[str, float, float]:
        if symbol in SIM_UNIVERSE:
            return SIM_UNIVERSE[symbol]
        rnd = random.Random(_seed(symbol))
        return (f"{symbol} (simulado)", round(rnd.uniform(10, 400), 2), rnd.uniform(0.2, 0.6))

    def _live_price(self, symbol: str) -> tuple[float, float]:
        name, base, vol = self._params(symbol)
        now = time.time()
        st = self._state.get(symbol)
        if st is None:
            rnd = random.Random(_seed(symbol) ^ int(now // 86400))
            prev_close = base * math.exp(rnd.gauss(0, vol / math.sqrt(252)))
            st = {"price": prev_close * math.exp(rnd.gauss(0, vol / math.sqrt(252) / 2)),
                  "prev_close": prev_close, "t": now}
            self._state[symbol] = st
        dt = max(0.0, now - st["t"])
        if dt > 0:
            # Volatilidad acelerada x40 para que la demo "se mueva" de forma visible.
            sigma = vol * math.sqrt(dt / (252 * 6.5 * 3600)) * 40
            st["price"] *= math.exp(random.gauss(0, sigma))
            st["t"] = now
        return st["price"], st["prev_close"]

    async def quote(self, symbol: str) -> dict:
        name, _, _ = self._params(symbol)
        price, prev = self._live_price(symbol)
        hist = await self.history(symbol, "1d", "5m")
        candles = hist["candles"]
        candles[-1]["c"] = price
        candles[-1]["h"] = max(candles[-1]["h"], price)
        candles[-1]["l"] = min(candles[-1]["l"], price)
        currency = "USD" if not symbol.endswith("=X") else symbol[3:6]
        q = _quote_from_candles(symbol, name, candles, prev, currency, "SIM", "sim")
        key = (symbol, int(time.time() // 86400))
        if key not in self._range52:
            closes = [c["c"] for c in (await self.history(symbol, "1y", "1d"))["candles"]]
            self._range52[key] = (max(closes), min(closes))
        hi, lo = self._range52[key]
        q.update(fifty_two_week_high=max(hi, price), fifty_two_week_low=min(lo, price), type=_guess_type(symbol))
        return q

    STEP = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600, "1h": 3600}
    SPAN_DAYS = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 91, "6mo": 182, "1y": 365, "2y": 730, "5y": 1826,
                 "10y": 3652, "max": 3652}
    MAX_DAILY, MAX_INTRADAY = 2520, 2000  # ~10 años de sesiones / barras intradía

    def _rel_path(self, symbol: str, interval: str, vol: float, n: int) -> list[tuple]:
        """Camino relativo (último cierre = 1.0), uno por símbolo+intervalo y día.

        Todos los periodos se cortan del MISMO camino, así 1y y 2y son coherentes
        (el 1y es la parte final del 2y), igual que con datos reales."""
        key = (symbol, interval, int(time.time() // 86400))
        if key in self._paths:
            return self._paths[key]
        step = 86400 if interval == "1d" else self.STEP.get(interval, 300)
        sigma = vol * math.sqrt(step / (252 * 86400 if step >= 86400 else 252 * 6.5 * 3600))
        rnd = random.Random(_seed(f"{symbol}|{interval}"))
        closes = [1.0]
        for _ in range(n - 1):  # caminata hacia atrás desde el último cierre
            closes.append(closes[-1] / math.exp(rnd.gauss(0.0002, sigma)))
        closes.reverse()
        rows = []
        for i, c in enumerate(closes):
            o = closes[i - 1] if i else c
            rows.append((o, max(o, c) * (1 + abs(rnd.gauss(0, sigma / 2))),
                         min(o, c) * (1 - abs(rnd.gauss(0, sigma / 2))), c, int(rnd.uniform(2e5, 5e6))))
        self._paths[key] = rows
        return rows

    @staticmethod
    def _trading_days(n: int) -> list[int]:
        out, d = [], int(time.time()) // 86400 * 86400
        while len(out) < n:
            if time.gmtime(d).tm_wday < 5:
                out.append(d)
            d -= 86400
        return out[::-1]

    @staticmethod
    def _aggregate(candles: list[dict], k: int) -> list[dict]:
        out = []
        for end in range(len(candles), 0, -k):
            g = candles[max(0, end - k): end]
            out.append({"t": g[0]["t"], "o": g[0]["o"], "h": max(c["h"] for c in g), "l": min(c["l"] for c in g),
                        "c": g[-1]["c"], "v": sum(c["v"] for c in g)})
        return out[::-1]

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> dict:
        name, _, vol = self._params(symbol)
        price, _ = self._live_price(symbol)
        days = self.SPAN_DAYS.get(period, 182)
        if interval in {"1d", "1wk", "1mo"}:
            n = max(2, min(self.MAX_DAILY, round(days * 252 / 365)))
            rows = self._rel_path(symbol, "1d", vol, self.MAX_DAILY)[-n:]
            stamps = self._trading_days(len(rows))
        else:
            step = self.STEP.get(interval, 300)
            n = max(2, min(self.MAX_INTRADAY, days * 86400 // step))
            rows = self._rel_path(symbol, interval, vol, self.MAX_INTRADAY)[-n:]
            now = int(time.time()) // step * step
            stamps = [now - (len(rows) - 1 - i) * step for i in range(len(rows))]
        candles = [{"t": t, "o": round(o * price, 6), "h": round(h * price, 6), "l": round(lo * price, 6),
                    "c": round(c * price, 6), "v": v} for t, (o, h, lo, c, v) in zip(stamps, rows)]
        if interval in {"1wk", "1mo"}:
            candles = self._aggregate(candles, 5 if interval == "1wk" else 21)
        return {"symbol": symbol, "name": name, "interval": interval, "period": period, "currency": "USD",
                "candles": candles, "source": "sim"}

    async def search(self, q: str, limit: int = 10) -> list[dict]:
        ql = q.lower()
        out = [{"symbol": s, "name": n, "exchange": "SIM", "type": _guess_type(s)}
               for s, (n, _, _) in SIM_UNIVERSE.items() if ql in s.lower() or ql in n.lower()]
        return out[:limit]

    async def info(self, symbol: str) -> dict:
        q = await self.quote(symbol)
        hist = await self.history(symbol, "1y", "1d")
        closes = [c["c"] for c in hist["candles"]]
        return {**q, "fifty_two_week_high": max(closes), "fifty_two_week_low": min(closes),
                "type": _guess_type(symbol)}


def _guess_type(symbol: str) -> str:
    if symbol.startswith("^"):
        return "INDEX"
    if symbol.endswith("=X"):
        return "CURRENCY"
    if symbol.endswith("=F"):
        return "FUTURE"
    if symbol.endswith("-USD"):
        return "CRYPTOCURRENCY"
    return "EQUITY"


# ── Yahoo Finance ───────────────────────────────────────────────────────────

class YahooProvider:
    name = "yahoo"
    CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    SEARCH = "https://query2.finance.yahoo.com/v1/finance/search"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._sem = asyncio.Semaphore(6)  # límite de concurrencia (como el cap de PythonRunner)
        # Backoff ante HTTP 429: respetamos el límite de Yahoo en lugar de insistir.
        self.cooldown_until = 0.0
        self._backoff = 30.0

    def status(self) -> dict:
        left = self.cooldown_until - time.time()
        return {"provider": "yahoo", "state": "cooldown" if left > 0 else "ok",
                "cooldown_seconds": max(0, int(left))}

    async def _get(self, url: str, params: dict) -> httpx.Response:
        if time.time() < self.cooldown_until:
            raise ProviderError("yahoo rate-limited (cooling down)")
        async with self._sem:
            try:
                r = await self.client.get(url, params=params)
            except httpx.HTTPError as e:
                raise ProviderError(f"network: {e.__class__.__name__}") from e
        if r.status_code == 429:
            wait = self._backoff
            self.cooldown_until = time.time() + wait
            self._backoff = min(self._backoff * 2, 900.0)
            print(f"[market] Yahoo HTTP 429 -> pausa {int(wait)} s; usando simulador", flush=True)
            raise ProviderError("yahoo HTTP 429")
        if r.status_code == 200:
            self._backoff = 30.0
        return r

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=12.0, headers={"User-Agent": UA}, follow_redirects=True)
        return self._client

    async def _chart(self, symbol: str, rng: str, interval: str) -> dict:
        r = await self._get(self.CHART.format(symbol=symbol), {"range": rng, "interval": interval})
        if r.status_code == 404:
            raise ProviderError(f"symbol not found: {symbol}")
        if r.status_code != 200:
            raise ProviderError(f"yahoo HTTP {r.status_code}")
        data = r.json().get("chart", {})
        if data.get("error") or not data.get("result"):
            raise ProviderError((data.get("error") or {}).get("description", "no data"))
        return data["result"][0]

    @staticmethod
    def _candles(res: dict) -> list[dict]:
        ts = res.get("timestamp") or []
        q = (res.get("indicators", {}).get("quote") or [{}])[0]
        out = []
        for i, t in enumerate(ts):
            c = (q.get("close") or [None])[i] if i < len(q.get("close") or []) else None
            if c is None:
                continue
            o = q["open"][i] if q.get("open") and q["open"][i] is not None else c
            h = q["high"][i] if q.get("high") and q["high"][i] is not None else c
            low = q["low"][i] if q.get("low") and q["low"][i] is not None else c
            v = q["volume"][i] if q.get("volume") and q["volume"][i] is not None else 0
            out.append({"t": t, "o": round(o, 6), "h": round(h, 6), "l": round(low, 6), "c": round(c, 6), "v": int(v)})
        return out

    async def quote(self, symbol: str) -> dict:
        res = await self._chart(symbol, "1d", "5m")
        m = res["meta"]
        price = m.get("regularMarketPrice")
        if price is None:
            raise ProviderError("no price")
        prev = m.get("chartPreviousClose") or m.get("previousClose") or price
        change = price - prev
        candles = self._candles(res)
        return {
            "symbol": m.get("symbol", symbol), "name": m.get("longName") or m.get("shortName") or symbol,
            "price": price, "prev_close": prev, "change": round(change, 6),
            "change_pct": round(change / prev * 100, 4) if prev else 0.0,
            "open": candles[0]["o"] if candles else price,
            "high": m.get("regularMarketDayHigh") or (max(c["h"] for c in candles) if candles else price),
            "low": m.get("regularMarketDayLow") or (min(c["l"] for c in candles) if candles else price),
            "volume": m.get("regularMarketVolume") or sum(c["v"] for c in candles),
            "currency": m.get("currency", "USD"), "exchange": m.get("fullExchangeName") or m.get("exchangeName", ""),
            "fifty_two_week_high": m.get("fiftyTwoWeekHigh"), "fifty_two_week_low": m.get("fiftyTwoWeekLow"),
            "market_time": m.get("regularMarketTime"), "type": m.get("instrumentType", _guess_type(symbol)),
            "ts": int(time.time()), "source": "yahoo",
        }

    async def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> dict:
        res = await self._chart(symbol, period, interval)
        m = res["meta"]
        return {"symbol": m.get("symbol", symbol), "name": m.get("longName") or m.get("shortName") or symbol,
                "interval": interval, "period": period, "currency": m.get("currency", "USD"),
                "candles": self._candles(res), "source": "yahoo"}

    async def search(self, q: str, limit: int = 10) -> list[dict]:
        r = await self._get(self.SEARCH, {"q": q, "quotesCount": limit, "newsCount": 0})
        if r.status_code != 200:
            raise ProviderError(f"yahoo HTTP {r.status_code}")
        return [
            {"symbol": x.get("symbol"), "name": x.get("longname") or x.get("shortname") or x.get("symbol"),
             "exchange": x.get("exchDisp") or x.get("exchange", ""), "type": x.get("quoteType", "")}
            for x in r.json().get("quotes", []) if x.get("symbol")
        ][:limit]

    async def info(self, symbol: str) -> dict:
        return await self.quote(symbol)


# ── Servicio con caché + fallback ───────────────────────────────────────────

class MarketService:
    def __init__(self) -> None:
        self.sim = SimProvider()
        self.yahoo = YahooProvider()
        self._quote_cache: dict[str, tuple[float, dict]] = {}

    @property
    def primary(self):
        return self.yahoo if settings.live else self.sim

    async def _with_fallback(self, method: str, *args) -> Any:
        if settings.live:
            try:
                return await getattr(self.yahoo, method)(*args)
            except ProviderError:
                pass
        return await getattr(self.sim, method)(*args)

    async def quote(self, symbol: str, max_age: float | None = None) -> dict:
        symbol = normalize_symbol(symbol)
        ttl = (settings.quote_ttl_live_ms if settings.live else settings.quote_ttl_sim_ms) / 1000
        ttl = ttl if max_age is None else max_age
        hit = self._quote_cache.get(symbol)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        q = await self._with_fallback("quote", symbol)
        self._quote_cache[symbol] = (time.time(), q)
        return q

    async def quotes(self, symbols: list[str], max_age: float | None = None) -> dict[str, dict]:
        uniq = list(dict.fromkeys(normalize_symbol(s) for s in symbols if s.strip()))
        results = await asyncio.gather(*(self.quote(s, max_age) for s in uniq), return_exceptions=True)
        return {s: r for s, r in zip(uniq, results) if isinstance(r, dict)}

    async def history(self, symbol: str, period: str = "6mo", interval: str | None = None) -> dict:
        symbol = normalize_symbol(symbol)
        period = period if period in PERIODS else "6mo"
        interval = interval if interval in INTERVALS else DEFAULT_INTERVAL[period]
        key = f"hist:{settings.data_mode}:{symbol}:{period}:{interval}"
        cached = get_db().cache_get(key)
        if cached:
            return cached
        h = await self._with_fallback("history", symbol, period, interval)
        ttl = 60 if interval in {"1m", "2m", "5m", "15m", "30m"} else 900
        if h["source"] != "sim":
            get_db().cache_put(key, h, ttl)
        return h

    async def search(self, q: str, limit: int = 10) -> list[dict]:
        key = f"search:{settings.data_mode}:{q.lower()}:{limit}"
        cached = get_db().cache_get(key)
        if cached is not None:
            return cached
        res = await self._with_fallback("search", q, limit)
        if res:
            get_db().cache_put(key, res, 86400)
        return res

    async def info(self, symbol: str) -> dict:
        return await self._with_fallback("info", normalize_symbol(symbol))


def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not s or len(s) > 24 or not all(ch.isalnum() or ch in "^=-._" for ch in s):
        raise ValueError(f"invalid symbol: {symbol!r}")
    return s


market = MarketService()
