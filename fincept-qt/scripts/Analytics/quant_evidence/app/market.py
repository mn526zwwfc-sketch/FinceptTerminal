"""
Live market quotes for the terminal's MERCADO screen (local app only).

Quotes come from Yahoo Finance's public chart endpoint, the same data the
repository's yfinance_data.py reads, fetched with the standard library so the
app keeps no third-party dependency. Nothing is ever filled in: a symbol that
fails to load is returned with an error and no numbers.

    snapshot()        every group, cached for CACHE_SECONDS
    quote(symbol)     one symbol: last, previous close, change, 1-month series
"""

from __future__ import annotations

import json
import math
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

CACHE_SECONDS = 60
TIMEOUT = 10
CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d'
SOURCE = {'label': 'Yahoo Finance', 'url': 'https://finance.yahoo.com/'}

# (symbol, short code shown in the terminal, Spanish name, related strategy id or None)
GROUPS = [
    {'key': 'mx', 'name': 'MÉXICO', 'items': [
        ('^MXX', 'IPC', 'S&P/BMV IPC', 'ipc_calendar'),
        ('MXN=X', 'USDMXN', 'Dólar / peso mexicano', None),
        ('AMXB.MX', 'AMX', 'América Móvil', None),
        ('WALMEX.MX', 'WALMEX', 'Walmart de México', None),
        ('GFNORTEO.MX', 'GFNORTE', 'Banorte', None),
        ('FEMSAUBD.MX', 'FEMSA', 'FEMSA', None),
        ('GMEXICOB.MX', 'GMEXICO', 'Grupo México', None),
        ('CEMEXCPO.MX', 'CEMEX', 'Cemex', None),
    ]},
    {'key': 'us', 'name': 'EE. UU.', 'items': [
        ('^GSPC', 'SPX', 'S&P 500', 'buy_hold_single_country'),
        ('^IXIC', 'NASDAQ', 'Nasdaq Composite', None),
        ('^DJI', 'DJIA', 'Dow Jones Industrial', None),
        ('^RUT', 'RTY', 'Russell 2000', None),
        ('^TNX', 'UST10', 'Bono del Tesoro 10 años (rend. %)', None),
        ('^VIX', 'VIX', 'Volatilidad implícita S&P 500', 'vol_managed_market'),
    ]},
    {'key': 'global', 'name': 'GLOBAL Y MATERIAS PRIMAS', 'items': [
        ('^STOXX50E', 'SX5E', 'Euro Stoxx 50', None),
        ('^FTSE', 'UKX', 'FTSE 100', None),
        ('^GDAXI', 'DAX', 'DAX', None),
        ('^N225', 'NKY', 'Nikkei 225', None),
        ('^HSI', 'HSI', 'Hang Seng', None),
        ('EURUSD=X', 'EURUSD', 'Euro / dólar', None),
        ('CL=F', 'WTI', 'Petróleo WTI (futuro)', None),
        ('GC=F', 'ORO', 'Oro (futuro)', None),
        ('HG=F', 'COBRE', 'Cobre (futuro)', None),
        ('BTC-USD', 'BTC', 'Bitcoin', None),
    ]},
    {'key': 'factors', 'name': 'FACTORES (ETF)', 'items': [
        ('MTUM', 'MTUM', 'iShares MSCI USA Momentum', 'momentum'),
        ('VLUE', 'VLUE', 'iShares MSCI USA Value', 'value'),
        ('QUAL', 'QUAL', 'iShares MSCI USA Quality', 'profitability_quality'),
        ('USMV', 'USMV', 'iShares MSCI USA Min Vol', 'betting_against_beta'),
        ('SIZE', 'SIZE', 'iShares MSCI USA Size', 'factor_fund_long_only'),
        ('SPY', 'SPY', 'SPDR S&P 500 (referencia)', 'buy_hold_single_country'),
    ]},
]


def fetch_chart(symbol: str) -> dict:
    """Raw chart JSON for one symbol. Replaced in tests."""
    url = CHART_URL.format(sym=urllib.parse.quote(symbol, safe=''))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (FinceptQuantTerminal)',
                                               'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode('utf-8'))


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def parse_chart(symbol: str, payload: dict) -> dict:
    """Last price, previous close and the daily closes of the last month.

    The previous close is the last completed daily bar before the latest
    trading day, so the change matches what a quote screen shows."""
    chart = (payload or {}).get('chart') or {}
    if chart.get('error'):
        err = chart['error']
        raise ValueError(err.get('description') or err.get('code') or 'error del proveedor')
    res = (chart.get('result') or [None])[0]
    if not res:
        raise ValueError('sin datos del proveedor')
    meta = res.get('meta') or {}
    ts = res.get('timestamp') or []
    closes = (((res.get('indicators') or {}).get('quote') or [{}])[0].get('close')) or []
    bars = [(int(t), _num(c)) for t, c in zip(ts, closes) if _num(c) is not None]
    last = _num(meta.get('regularMarketPrice'))
    mtime = meta.get('regularMarketTime')
    if last is None and bars:
        last, mtime = bars[-1][1], bars[-1][0]
    if last is None:
        raise ValueError('sin precio')
    prev = None
    if bars:
        last_day = datetime.fromtimestamp(bars[-1][0], timezone.utc).date()
        mkt_day = datetime.fromtimestamp(int(mtime), timezone.utc).date() if mtime else last_day
        if last_day >= mkt_day:   # the newest bar is the current session
            prev = bars[-2][1] if len(bars) >= 2 else None
        else:
            prev = bars[-1][1]
    change = None if prev is None else last - prev
    first = bars[0][1] if bars else None
    return {
        'symbol': symbol,
        'last': last,
        'prev_close': prev,
        'change': change,
        'change_pct': None if not prev else change / prev * 100,
        'month_pct': None if not first else (last / first - 1) * 100,
        'currency': meta.get('currency'),
        'exchange': meta.get('exchangeName') or meta.get('fullExchangeName'),
        'market_time': int(mtime) if mtime else None,
        'series': [round(c, 6) for _, c in bars],
    }


def quote(symbol: str) -> dict:
    try:
        return parse_chart(symbol, fetch_chart(symbol))
    except Exception as e:  # noqa: BLE001 - reported per symbol, never replaced by a number
        return {'symbol': symbol, 'error': f'{type(e).__name__}: {e}'[:200]}


_cache: dict = {'t': 0.0, 'data': None}
_lock = threading.Lock()


def snapshot(force: bool = False) -> dict:
    with _lock:
        if not force and _cache['data'] and time.time() - _cache['t'] < CACHE_SECONDS:
            return _cache['data']
        symbols = [it[0] for g in GROUPS for it in g['items']]
        with ThreadPoolExecutor(max_workers=8) as ex:
            quotes = dict(zip(symbols, ex.map(quote, symbols)))
        groups = []
        for g in GROUPS:
            rows = []
            for sym, code, name, strat in g['items']:
                rows.append(dict(quotes[sym], code=code, name=name, strategy_id=strat))
            groups.append({'key': g['key'], 'name': g['name'], 'rows': rows})
        ok = sum(1 for q in quotes.values() if 'error' not in q)
        data = {'fetched_at': int(time.time()), 'source': SOURCE, 'ok': ok, 'total': len(symbols),
                'groups': groups}
        _cache.update(t=time.time(), data=data)
        return data
