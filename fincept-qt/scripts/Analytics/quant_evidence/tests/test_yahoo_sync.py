"""
Tests for app/yahoo_sync.py: symbol checks and database ids, monthly parsing
(adjusted closes, the current month dropped, Yahoo errors) and the output
files. No network: Yahoo answers are built here.

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .
"""

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS = os.path.dirname(os.path.dirname(HERE))
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence.app import yahoo_sync as ys  # noqa: E402


def _payload(months, adj=True, start=(2020, 1), gmtoffset=-14400):
    ts, closes = [], []
    y, m = start
    for i in range(months):
        ts.append(int(dt.datetime(y, m, 1, 4, tzinfo=dt.timezone.utc).timestamp()) - gmtoffset)
        closes.append(100.0 + i)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    ind = {'quote': [{'close': [c + 0.5 for c in closes]}]}
    if adj:
        ind['adjclose'] = [{'adjclose': closes}]
    return {'chart': {'result': [{'meta': {'currency': 'USD', 'longName': 'Ejemplo', 'gmtoffset': gmtoffset,
                                           'fullExchangeName': 'NYSEArca'},
                                  'timestamp': ts, 'indicators': ind}], 'error': None}}


class TestSymbols(unittest.TestCase):
    def test_symbol_ok(self):
        for s in ('SPY', 'WALMEX.MX', '^MXX', 'USDMXN=X', 'BRK-B', 'GC=F'):
            self.assertTrue(ys.symbol_ok(s), s)
        for s in ('', 'spy', 'A B', '../x', '^^X', 'X' * 20, 'SPY;rm'):
            self.assertFalse(ys.symbol_ok(s), s)

    def test_doc_id_round_trip(self):
        for s in ('SPY', '^MXX', 'USDMXN=X', 'WALMEX.MX'):
            d = ys.doc_id(s)
            self.assertRegex(d, r'^[A-Za-z0-9_\-.~:@+]+$')
            self.assertEqual(ys.symbol_from_id(d), s)
        self.assertEqual(ys.doc_id('^MXX'), '~MXX')
        self.assertEqual(ys.doc_id('USDMXN=X'), 'USDMXN:X')


class TestParse(unittest.TestCase):
    def test_adjusted_monthly_and_current_month_dropped(self):
        doc = ys.parse_monthly('SPY', _payload(30), today=dt.date(2022, 6, 15))
        self.assertTrue(doc['adjusted'])
        self.assertEqual(doc['dates'][0], '2020-01')
        self.assertEqual(doc['dates'][-1], '2022-05')          # June 2022 is the current month
        self.assertEqual(len(doc['dates']), len(doc['closes']))
        self.assertEqual(doc['closes'][0], 100.0)
        self.assertEqual((doc['currency'], doc['name'], doc['exchange']), ('USD', 'Ejemplo', 'NYSEArca'))

    def test_falls_back_to_close_without_adjclose(self):
        doc = ys.parse_monthly('^MXX', _payload(20, adj=False), today=dt.date(2030, 1, 1))
        self.assertFalse(doc['adjusted'])
        self.assertEqual(doc['closes'][0], 100.5)

    def test_skips_missing_points(self):
        p = _payload(20)
        p['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'][3] = None
        doc = ys.parse_monthly('SPY', p, today=dt.date(2030, 1, 1))
        self.assertEqual(len(doc['dates']), 19)

    def test_errors(self):
        with self.assertRaisesRegex(ValueError, 'No data found'):
            ys.parse_monthly('XXXX', {'chart': {'result': None, 'error': {'code': 'Not Found', 'description': 'No data found'}}})
        with self.assertRaisesRegex(ValueError, 'poca historia'):
            ys.parse_monthly('NEW', _payload(6), today=dt.date(2030, 1, 1))
        with self.assertRaises(ValueError):
            ys.parse_monthly('SPY', {})


class TestSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_writes_documents_and_summary(self):
        def fake(sym):
            if sym == 'BAD':
                raise OSError('HTTP Error 404')
            return _payload(24)
        s = ys.sync(['SPY', '^MXX', 'spy', 'BAD', 'no valid'], self.tmp, fetch=fake, pause=0)
        self.assertEqual([x['id'] for x in s['ok']], ['SPY', '~MXX'])
        self.assertEqual([x['symbol'] for x in s['failed']], ['BAD', 'no valid'])
        with open(os.path.join(self.tmp, 'prices', '~MXX.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['symbol'], '^MXX')
        with open(os.path.join(self.tmp, 'summary.json'), encoding='utf-8') as f:
            self.assertEqual(len(json.load(f)['ok']), 2)

    def test_main_accepts_doc_ids(self):
        ys_fetch = ys.fetch_chart
        ys.fetch_chart = lambda sym: _payload(24)
        try:
            out = ys.sync([ys.symbol_from_id('USDMXN:X')], self.tmp, fetch=ys.fetch_chart, pause=0)
        finally:
            ys.fetch_chart = ys_fetch
        self.assertEqual(out['ok'][0]['symbol'], 'USDMXN=X')


if __name__ == '__main__':
    unittest.main()
