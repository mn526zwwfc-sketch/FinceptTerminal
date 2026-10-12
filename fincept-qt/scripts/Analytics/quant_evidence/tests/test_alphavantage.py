"""
Tests for the Alpha Vantage path of the MERCADO screen: the local proxy
(app/alphavantage.py), its server route, and the page's response reader
(avParse in app/terminal.html, run with Node). All responses are synthetic;
nothing here calls Alpha Vantage.

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS = os.path.dirname(os.path.dirname(HERE))
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence.app import alphavantage as av  # noqa: E402
from quant_evidence.app import build_app  # noqa: E402
from quant_evidence.app.server import make_server  # noqa: E402

KEY = 'TESTKEY123'


def series(n, start=4.0):
    return {'name': 'Synthetic series', 'interval': 'daily', 'unit': 'percent',
            'data': [{'date': f'2030-01-{28 - i:02d}', 'value': f'{start + i / 100:.2f}'} for i in range(n)]}


class TestProxy(unittest.TestCase):
    def setUp(self):
        self._fetch, self._gap = av.fetch, av.MIN_INTERVAL
        av.MIN_INTERVAL = 0
        av._cache.clear()
        self.env = mock.patch.dict(os.environ, {'ALPHA_VANTAGE_API_KEY': KEY})
        self.env.start()
        self.calls = []

    def tearDown(self):
        av.fetch, av.MIN_INTERVAL = self._fetch, self._gap
        av._cache.clear()
        self.env.stop()

    def fake(self, payload):
        def f(params):
            self.calls.append(dict(params))
            return payload
        av.fetch = f

    def test_requires_key(self):
        with mock.patch.dict(os.environ, {'ALPHA_VANTAGE_API_KEY': ''}):
            self.assertFalse(av.configured())
            with self.assertRaises(PermissionError):
                av.call('MARKET_STATUS')

    def test_allowlist_and_params(self):
        self.fake({'markets': []})
        for fn, params in (('TIME_SERIES_INTRADAY', {'symbol': 'IBM'}), ('GLOBAL_QUOTE', {'symbol': 'IBM', 'apikey': 'x'}),
                           ('GLOBAL_QUOTE', {'symbol': 'IBM&function=X'}), ('GLOBAL_QUOTE', {'symbol': 5}),
                           ('GLOBAL_QUOTE', ['IBM'])):
            with self.assertRaises(ValueError, msg=(fn, params)):
                av.call(fn, params)
        for fn, params in (('GLOBAL_QUOTE', {}), ('GLOBAL_QUOTE', None), ('CURRENCY_EXCHANGE_RATE', {'from_currency': 'USD'}),
                           ('GOLD_SILVER_SPOT', {}), ('GLOBAL_QUOTE', {'symbol': 'IBM\n'})):
            with self.assertRaises(ValueError, msg=(fn, params)):
                av.call(fn, params)
        self.assertEqual(self.calls, [])

    def test_adds_key_and_json_datatype_and_caches(self):
        self.fake({'Global Quote': {'05. price': '10.0'}})
        r1 = av.call('GLOBAL_QUOTE', {'symbol': 'IBM'})
        r2 = av.call('GLOBAL_QUOTE', {'symbol': 'IBM'})
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0], {'symbol': 'IBM', 'function': 'GLOBAL_QUOTE', 'apikey': KEY, 'datatype': 'json'})
        self.assertFalse(r1['cached'])
        self.assertTrue(r2['cached'])
        self.assertNotIn(KEY, json.dumps(r1))

    def test_notices_are_not_cached(self):
        self.fake({'Note': 'Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day.'})
        av.call('MARKET_STATUS')
        av.call('MARKET_STATUS')
        self.assertEqual(len(self.calls), 2)

    def test_series_are_trimmed(self):
        self.fake(series(100))
        out = av.call('TREASURY_YIELD', {'interval': 'daily', 'maturity': '10year'})['payload']
        self.assertEqual(len(out['data']), av.MAX_SERIES)
        self.assertTrue(out['data_trimmed'])
        self.assertEqual(out['data'][0]['date'], '2030-01-28')

    def test_errors_hide_the_key(self):
        def boom(params):
            raise OSError('failed for ' + params['apikey'])
        av.fetch = boom
        with self.assertRaises(OSError) as cm:
            av.call('MARKET_STATUS')
        self.assertNotIn(KEY, str(cm.exception))


class TestRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server('127.0.0.1', 0, scan_repo=False)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None):
        import http.client
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        c.request(method, path, body=None if method == 'GET' else json.dumps(body),
                  headers={'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'})
        r = c.getresponse()
        data = json.loads(r.read())
        c.close()
        return r.status, data

    def test_health_flag_and_proxy(self):
        saved, gap = av.fetch, av.MIN_INTERVAL
        av.fetch, av.MIN_INTERVAL = (lambda params: {'markets': [{'region': 'Mexico', 'current_status': 'open'}]}), 0
        av._cache.clear()
        try:
            with mock.patch.dict(os.environ, {'ALPHA_VANTAGE_API_KEY': ''}):
                st, j = self.req('GET', '/api/health')
                self.assertFalse(j['data']['alpha_vantage'])
                st, j = self.req('POST', '/api/av', {'function': 'MARKET_STATUS'})
                self.assertFalse(j['success'])
                self.assertIn('ALPHA_VANTAGE_API_KEY', j['error'])
            with mock.patch.dict(os.environ, {'ALPHA_VANTAGE_API_KEY': KEY}):
                st, j = self.req('GET', '/api/health')
                self.assertTrue(j['data']['alpha_vantage'])
                st, j = self.req('POST', '/api/av', {'function': 'MARKET_STATUS', 'params': {}})
                self.assertTrue(j['success'])
                self.assertEqual(j['data']['payload']['markets'][0]['region'], 'Mexico')
                st, j = self.req('POST', '/api/av', {'function': 'LISTING_STATUS', 'params': {}})
                self.assertFalse(j['success'])
                for body in ([], 'x', 5, None):
                    st, j = self.req('POST', '/api/av', body)
                    self.assertEqual(st, 400, body)
                    self.assertFalse(j['success'])
        finally:
            av.fetch, av.MIN_INTERVAL = saved, gap
            av._cache.clear()


@unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
class TestPageReader(unittest.TestCase):
    """avParse is the guard that keeps notes, refusals and sample data off the screen."""

    @classmethod
    def setUpClass(cls):
        with open(build_app.TEMPLATES['terminal'], encoding='utf-8') as f:
            html = f.read()
        m = re.search(r'/\* AV-PARSE-BEGIN \*/([\s\S]*?)/\* AV-PARSE-END \*/', html)
        assert m, 'AV-PARSE block missing'
        cls.code = m.group(1)

    def parse(self, cases):
        js = ("let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{const {code,cases}=JSON.parse(d);"
              "const avParse=new Function(code+';return avParse;')();"
              "process.stdout.write(JSON.stringify(cases.map(c=>avParse(c[0],c[1]))));});")
        proc = subprocess.run(['node', '-e', js], input=json.dumps({'code': self.code, 'cases': cases}),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr[-500:])
        return json.loads(proc.stdout)

    def test_refusals_never_become_data(self):
        premium_sample = {'endpoint': 'Realtime Bulk Quotes',
                          'message': 'This is a premium endpoint. ***THE SAMPLE DATA SCHEMA BELOW IS ARTIFICIAL AND FOR ILLUSTRATION PURPOSES ONLY***.',
                          'data': [{'symbol': 'AAA', 'close': '1.0'}]}
        sample_quote = {'message': 'This is a premium endpoint. Sample data for illustration.', 'Global Quote': {'05. price': '1.0'}}
        rate = {'error': {'type': 'rate_limit', 'message': 'Please consider spreading out your free API requests more sparingly (1 request per second). ... (25 requests per day)'}}
        entitled = {'error': {'type': 'rate_limit', 'message': 'You are not yet entitled to index data access. Please subscribe to any of our premium plans.'}}
        rest_note = {'Note': 'Our standard API rate limit is 25 requests per day.'}
        rest_premium = {'Information': 'Thank you for using Alpha Vantage! This is a premium endpoint.'}
        out = self.parse([['GLOBAL_QUOTE', premium_sample], ['GLOBAL_QUOTE', sample_quote], ['MARKET_STATUS', rate],
                          ['TREASURY_YIELD', entitled], ['GLOBAL_QUOTE', rest_note], ['TOP_GAINERS_LOSERS', rest_premium],
                          ['GLOBAL_QUOTE', {'Error Message': 'Invalid API call.'}], ['GLOBAL_QUOTE', {'Global Quote': {}}],
                          ['GLOBAL_QUOTE', None], ['GLOBAL_QUOTE', 'symbol,price\nX,1'], ['MARKET_STATUS', {'unexpected': 1}],
                          ['GLOBAL_QUOTE', {'Information': 'Some other notice.'}]])
        kinds = [o.get('kind') for o in out]
        self.assertEqual(kinds, ['premium', 'premium', 'rate_limit', 'premium', 'rate_limit', 'premium',
                                 'invalid', 'invalid', 'empty', 'empty', 'shape', 'notice'])
        self.assertTrue(all(o['ok'] is False and 'data' not in o for o in out))

    def test_good_answers(self):
        quote = {'Global Quote': {'01. symbol': 'XYZ', '02. open': '10.0', '05. price': '10.5', '06. volume': '1000',
                                  '07. latest trading day': '2030-01-02', '08. previous close': '10.0',
                                  '09. change': '0.5', '10. change percent': '5.0000%'}}
        fx = {'Realtime Currency Exchange Rate': {'1. From_Currency Code': 'USD', '3. To_Currency Code': 'MXN',
                                                  '5. Exchange Rate': '17.5', '6. Last Refreshed': '2030-01-02 10:00:00',
                                                  '7. Time Zone': 'UTC', '8. Bid Price': '17.49', '9. Ask Price': '17.51'}}
        status = {'endpoint': 'Global Market Open & Close Status', 'markets': [
            {'market_type': 'Equity', 'region': 'Mexico', 'primary_exchanges': 'Mexico', 'local_open': '08:30',
             'local_close': '15:00', 'current_status': 'Open', 'notes': ''}]}
        wti = {'name': 'Crude Oil Prices WTI', 'unit': 'dollars per barrel',
               'data': [{'date': '2030-01-03', 'value': '.'}, {'date': '2030-01-02', 'value': '70.0'}, {'date': '2030-01-01', 'value': '69.0'}]}
        preview = {'preview': True, 'sample_data': json.dumps(series(2)), 'message': 'This is a preview because the response exceeded the 32000 token limit.'}
        broken_preview = {'preview': True, 'sample_data': '{"name": "x", "data": [{"date"'}
        gold = {'nominal': 'XAUUSD', 'timestamp': '2030-01-02 10:00:00', 'price': '2000.5'}
        movers = {'last_updated': '2030-01-02 16:15:59 US/Eastern',
                  'top_gainers': [{'ticker': 'AAA', 'price': '2.0', 'change_amount': '1.0', 'change_percentage': '100%', 'volume': '10'}],
                  'top_losers': [], 'most_actively_traded': [{'ticker': '', 'price': '1'}]}
        q, f, s, w, p, bp, g, mv = self.parse([['GLOBAL_QUOTE', quote], ['CURRENCY_EXCHANGE_RATE', fx], ['MARKET_STATUS', status],
                                               ['WTI', wti], ['TREASURY_YIELD', preview], ['TREASURY_YIELD', broken_preview],
                                               ['GOLD_SILVER_SPOT', gold], ['TOP_GAINERS_LOSERS', movers]])
        self.assertEqual((q['data']['price'], q['data']['change_pct'], q['data']['day']), (10.5, 5.0, '2030-01-02'))
        self.assertEqual((f['data']['rate'], f['data']['bid'], f['data']['ask']), (17.5, 17.49, 17.51))
        self.assertEqual(s['data']['markets'][0]['status'], 'open')
        self.assertEqual((w['data']['last'], w['data']['date'], w['data']['prev']), (70.0, '2030-01-02', 69.0))
        self.assertEqual(w['data']['series'], [69.0, 70.0])
        self.assertTrue(p['ok'])
        self.assertEqual((p['data']['last'], p['data']['prev']), (4.0, 4.01))
        self.assertEqual(bp['kind'], 'preview')
        self.assertEqual(g['data']['price'], 2000.5)
        self.assertEqual(len(mv['data']['gainers']), 1)
        self.assertEqual(mv['data']['active'], [])


class TestPageWiring(unittest.TestCase):
    def test_terminal_declares_connector_tools_it_calls(self):
        with open(build_app.TEMPLATES['terminal'], encoding='utf-8') as f:
            html = f.read()
        self.assertIn("var AV_SERVER = 'Alpha Vantage MCP Server';", html)
        for fn in av.FUNCTIONS:          # the page calls exactly the tools the proxy allows
            self.assertIn("'" + fn + "'", html, fn)


if __name__ == '__main__':
    unittest.main()
