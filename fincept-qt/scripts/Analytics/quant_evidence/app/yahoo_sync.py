"""
Monthly adjusted prices from Yahoo Finance for Laboratorio Fincept.

Laboratorio Fincept runs as a claude.ai artifact, which cannot call Yahoo
itself. A scheduled task runs this script, then writes one document per
symbol into the artifact's database (collection `prices`), where the page
reads it. Stdlib only:

    python -m quant_evidence.app.yahoo_sync SPY EWW ^MXX USDMXN=X --out-dir /tmp/prices

writes <out-dir>/prices/<doc id>.json per symbol that answered and
<out-dir>/summary.json with what succeeded and what failed.

Yahoo's chart endpoint is public but unofficial: no service guarantee, and its
terms limit the data to personal use. Adjusted closes include dividends and
splits. The current month is dropped because it is not complete.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

CHART_URL = ('https://query1.finance.yahoo.com/v8/finance/chart/{sym}'
             '?range=max&interval=1mo&events=div%2Csplit&includeAdjustedClose=true')
SYMBOL_RE = re.compile(r'^\^?[A-Z0-9][A-Z0-9.\-]{0,14}(=X|=F)?$')
MIN_MONTHS = 13
# Database ids allow letters, digits and _ - . ~ : @ + only.
_ID_MAP = {'^': '~', '=': ':'}
_SYM_MAP = {v: k for k, v in _ID_MAP.items()}


def symbol_ok(symbol: str) -> bool:
    return bool(SYMBOL_RE.match(symbol or ''))


def doc_id(symbol: str) -> str:
    """Database document id for a Yahoo symbol: '^MXX' -> '~MXX', 'USDMXN=X' -> 'USDMXN:X'."""
    return ''.join(_ID_MAP.get(c, c) for c in symbol)


def symbol_from_id(doc: str) -> str:
    return ''.join(_SYM_MAP.get(c, c) for c in doc)


def fetch_chart(symbol: str, timeout: float = 25.0) -> dict:
    """Raw chart JSON for one symbol. Replaced in tests."""
    url = CHART_URL.format(sym=urllib.parse.quote(symbol, safe=''))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (FinceptLab)', 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def parse_monthly(symbol: str, payload: dict, today: dt.date | None = None) -> dict:
    """The page's document for one symbol: month dates and adjusted closes, oldest first."""
    chart = (payload or {}).get('chart') or {}
    if chart.get('error'):
        err = chart['error']
        raise ValueError(f"Yahoo: {err.get('description') or err.get('code') or err}")
    res = (chart.get('result') or [None])[0]
    if not res:
        raise ValueError('Yahoo no devolvió datos.')
    ts = res.get('timestamp') or []
    ind = res.get('indicators') or {}
    adj = ((ind.get('adjclose') or [{}])[0] or {}).get('adjclose')
    close = ((ind.get('quote') or [{}])[0] or {}).get('close')
    series = adj if adj and any(v is not None for v in adj) else close
    if not series:
        raise ValueError('Yahoo no devolvió precios.')
    today = today or dt.datetime.now(dt.timezone.utc).date()
    current = (today.year, today.month)
    meta = res.get('meta') or {}
    off = int(meta.get('gmtoffset') or 0)
    months = {}
    for t, v in zip(ts, series):
        if v is None or not (v > 0):
            continue
        d = dt.datetime.fromtimestamp(t + off, dt.timezone.utc).date()
        if (d.year, d.month) >= current:
            continue
        months[(d.year, d.month)] = float(v)          # one point per month; a later row wins
    keys = sorted(months)
    if len(keys) < MIN_MONTHS:
        raise ValueError(f'Muy poca historia mensual ({len(keys)} meses).')
    return {
        'symbol': symbol,
        'name': meta.get('longName') or meta.get('shortName') or symbol,
        'currency': meta.get('currency') or '',
        'exchange': meta.get('fullExchangeName') or meta.get('exchangeName') or '',
        'source': 'Yahoo Finance',
        'adjusted': bool(adj and any(v is not None for v in adj)),
        'dates': [f'{y:04d}-{m:02d}' for y, m in keys],
        'closes': [round(months[k], 6) for k in keys],
        'updated_at': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
    }


def sync(symbols, out_dir: str, fetch=fetch_chart, pause: float = 0.6) -> dict:
    os.makedirs(os.path.join(out_dir, 'prices'), exist_ok=True)
    ok, failed, seen = [], [], set()
    for raw in symbols:
        sym = (raw or '').strip().upper()
        if sym in seen:
            continue
        seen.add(sym)
        if not symbol_ok(sym):
            failed.append({'symbol': raw, 'error': 'Símbolo no válido.'})
            continue
        try:
            doc = parse_monthly(sym, fetch(sym))
        except Exception as e:  # noqa: BLE001 - reported per symbol, the rest continue
            failed.append({'symbol': sym, 'error': str(e)[:200]})
            continue
        path = os.path.join(out_dir, 'prices', doc_id(sym) + '.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(doc, f, ensure_ascii=False, separators=(',', ':'))
        ok.append({'symbol': sym, 'id': doc_id(sym), 'file': path, 'months': len(doc['dates']), 'last': doc['dates'][-1]})
        if pause:
            time.sleep(pause)
    summary = {'ok': ok, 'failed': failed, 'ran_at': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()}
    with open(os.path.join(out_dir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('symbols', nargs='+', help="Yahoo symbols, e.g. SPY WALMEX.MX ^MXX USDMXN=X; doc ids ('~MXX') are accepted too")
    ap.add_argument('--out-dir', required=True)
    args = ap.parse_args(argv)
    summary = sync([symbol_from_id(s) for s in args.symbols], args.out_dir)
    print(json.dumps({'ok': len(summary['ok']), 'failed': summary['failed']}, ensure_ascii=False))
    return 0 if summary['ok'] or not args.symbols else 1


if __name__ == '__main__':
    sys.exit(main())
