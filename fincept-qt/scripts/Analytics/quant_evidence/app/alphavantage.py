"""
Alpha Vantage proxy for the local app's MERCADO screen.

The page asks for one allowlisted Alpha Vantage function at a time; this
module adds the API key (ALPHA_VANTAGE_API_KEY, the same variable as
fincept-qt/scripts/alphavantage_data.py), spaces calls one second apart
(the free plan allows one request per second and 25 per day), caches
successful answers briefly and trims long daily series. It returns Alpha
Vantage's JSON as is: the page interprets rate-limit notes, premium-only
answers and errors, and never shows a number that did not arrive.

The key never leaves this process: it is not echoed in answers or errors.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

BASE_URL = 'https://www.alphavantage.co/query'
TIMEOUT = 15
MIN_INTERVAL = 1.1        # seconds between upstream calls (free plan: 1 request per second)
CACHE_SECONDS = 60
MAX_SERIES = 40           # daily series are trimmed to the newest points the page uses

# Allowlisted functions -> accepted parameters. Everything else is refused.
FUNCTIONS = {
    'MARKET_STATUS': (),
    'GLOBAL_QUOTE': ('symbol',),
    'CURRENCY_EXCHANGE_RATE': ('from_currency', 'to_currency'),
    'TREASURY_YIELD': ('interval', 'maturity'),
    'WTI': ('interval',),
    'GOLD_SILVER_SPOT': ('symbol',),
    'TOP_GAINERS_LOSERS': (),
}
# Parameters Alpha Vantage cannot answer without (the others have upstream defaults).
REQUIRED = {'GLOBAL_QUOTE': ('symbol',), 'CURRENCY_EXCHANGE_RATE': ('from_currency', 'to_currency'), 'GOLD_SILVER_SPOT': ('symbol',)}
JSON_DATATYPE = {'GLOBAL_QUOTE', 'CURRENCY_EXCHANGE_RATE', 'TREASURY_YIELD', 'WTI'}
_VALUE = re.compile(r'[A-Za-z0-9.\-^]{1,20}')
# Answers that explain a refusal instead of carrying data: never cached.
_NOTICE_KEYS = ('Note', 'Information', 'Error Message', 'error', 'message')


def api_key() -> str:
    return os.environ.get('ALPHA_VANTAGE_API_KEY', '').strip()


def configured() -> bool:
    return bool(api_key())


def fetch(params: dict) -> dict:
    """Raw Alpha Vantage JSON for one request. Replaced in tests."""
    url = BASE_URL + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'FinceptQuantTerminal', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode('utf-8'))


def _clean_params(function: str, params) -> dict:
    if function not in FUNCTIONS:
        raise ValueError(f'Función de Alpha Vantage no permitida: {function!r}.')
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError('params debe ser un objeto JSON.')
    allowed = FUNCTIONS[function]
    out = {}
    for k, v in params.items():
        if k not in allowed:
            raise ValueError(f'Parámetro no permitido para {function}: {k!r}.')
        if not isinstance(v, str) or not _VALUE.fullmatch(v):
            raise ValueError(f'Valor no válido para {k}.')
        out[k] = v
    missing = [k for k in REQUIRED.get(function, ()) if k not in out]
    if missing:
        raise ValueError(f'Falta {missing[0]} para {function}.')
    return out


def _trim(payload):
    if isinstance(payload, dict) and isinstance(payload.get('data'), list) and len(payload['data']) > MAX_SERIES:
        payload = dict(payload, data=payload['data'][:MAX_SERIES], data_trimmed=True)
    return payload


_lock = threading.Lock()
_last_call = [0.0]           # time.monotonic() of the last upstream call
_cache: dict = {}            # ident -> (monotonic time, wall time, payload)


def _cached(function: str, ident):
    hit = _cache.get(ident)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return {'function': function, 'payload': hit[2], 'cached': True, 'fetched_at': int(hit[1])}
    return None


def call(function: str, params=None) -> dict:
    """One Alpha Vantage answer: {'function', 'payload', 'cached', 'fetched_at'}."""
    key = api_key()
    if not key:
        raise PermissionError('Alpha Vantage no está configurado: define la variable ALPHA_VANTAGE_API_KEY '
                              'antes de abrir la app (python quant_studio.py).')
    clean = _clean_params(function, params)
    ident = (function, tuple(sorted(clean.items())))
    hit = _cached(function, ident)            # cached answers never wait behind an upstream call
    if hit:
        return hit
    with _lock:
        hit = _cached(function, ident)        # another request may have fetched it meanwhile
        if hit:
            return hit
        # Monotonic clock: a wall-clock step back must not stall every request behind a long sleep.
        wait = _last_call[0] + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(min(wait, MIN_INTERVAL))
        query = dict(clean, function=function, apikey=key)
        if function in JSON_DATATYPE:
            query['datatype'] = 'json'
        try:
            payload = fetch(query)
        except Exception as e:  # noqa: BLE001 - reported to the page without the key
            raise OSError(f'Alpha Vantage no respondió: {type(e).__name__}: {e}'.replace(key, '***')[:300]) from None
        finally:
            _last_call[0] = time.monotonic()
        payload = _trim(payload)
        now = time.time()
        if isinstance(payload, dict) and not any(k in payload for k in _NOTICE_KEYS):
            _cache[ident] = (time.monotonic(), now, payload)
        return {'function': function, 'payload': payload, 'cached': False, 'fetched_at': int(now)}
