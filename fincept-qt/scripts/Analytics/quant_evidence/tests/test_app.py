"""
Tests for Fincept Quant Studio (quant_evidence/app): packaging, the local
API and its path / host protections. Stdlib only:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .
"""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS = os.path.dirname(os.path.dirname(HERE))
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence.app import build_app, market  # noqa: E402
from quant_evidence.app.server import make_server, resolve_repo_path  # noqa: E402
from quant_evidence.evaluator import evaluate_decision  # noqa: E402


class TestBuild(unittest.TestCase):
    def test_build_writes_page_and_sources(self):
        with tempfile.TemporaryDirectory() as d:
            info = build_app.build(d, standalone=False, scan_repo=False)
            with open(info['page'], encoding='utf-8') as f:
                html = f.read()
            index = build_app.code_index()
            self.assertEqual(info['files'], len(index))
            self.assertTrue(os.path.isfile(os.path.join(d, 'code', '0.txt')))
            self.assertEqual(len(os.listdir(os.path.join(d, 'code'))), len(index))
        for marker in ('/*__ENGINE__*/', '/*__KB__*/', '/*__REPO__*/', '/*__CODE_INDEX__*/'):
            self.assertNotIn(marker, html)
        self.assertTrue(html.startswith('<title>Fincept Quant Terminal</title>'))
        self.assertLess(len(html), 2_000_000)

    def test_both_interfaces_render(self):
        term = build_app.render_page([], scan_repo=False, standalone=False, ui='terminal')
        studio = build_app.render_page([], scan_repo=False, standalone=False, ui='studio')
        self.assertIn('MONITOR &lt;1&gt;', term)
        self.assertIn('Decide con', studio)
        with self.assertRaises(ValueError):
            build_app.render_page([], scan_repo=False, ui='nope')

    @unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
    def test_inline_scripts_parse(self):
        for ui in ('terminal', 'studio'):
            html = build_app.render_page([], scan_repo=False, standalone=False, ui=ui)
            scripts = re.findall(r'<script>([\s\S]*?)</script>', html)
            js = ("let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{"
                  "for (const s of JSON.parse(d)) new Function(s);});")
            proc = subprocess.run(['node', '-e', js], input=json.dumps(scripts), capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, (ui, proc.stderr[-500:]))

    def test_terminal_has_no_third_party_branding(self):
        with open(build_app.TEMPLATES['terminal'], encoding='utf-8') as f:
            self.assertNotIn('bloomberg', f.read().lower())

    def test_code_index_starts_with_new_package(self):
        index = build_app.code_index()
        self.assertEqual(index[0]['group'], 'nuevo')
        paths = [e['path'] for e in index]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn('fincept-qt/scripts/Analytics/quant_evidence/evaluator.py', paths)
        self.assertTrue(any(e['group'] == 'repo' for e in index))
        self.assertTrue(all(e['id'] == i for i, e in enumerate(index)))

    def test_standalone_page_has_doctype(self):
        html = build_app.render_page([], scan_repo=False, standalone=True)
        self.assertTrue(html.startswith('<!doctype html>'))


def _chart(closes, price, ts0=1_790_000_000, mtime=None, currency='MXN'):
    ts = [ts0 + i * 86400 for i in range(len(closes))]
    return {'chart': {'error': None, 'result': [{
        'meta': {'regularMarketPrice': price, 'regularMarketTime': mtime or ts[-1] + 3600,
                 'currency': currency, 'exchangeName': 'MEX'},
        'timestamp': ts, 'indicators': {'quote': [{'close': closes}]}}]}}


class TestMarket(unittest.TestCase):
    def setUp(self):
        self._fetch = market.fetch_chart
        market._cache.update(t=0.0, data=None)

    def tearDown(self):
        market.fetch_chart = self._fetch
        market._cache.update(t=0.0, data=None)

    def test_parse_uses_previous_session_close(self):
        q = market.parse_chart('^MXX', _chart([100.0, None, 102.0, 104.0], 105.0))
        self.assertEqual(q['last'], 105.0)
        self.assertEqual(q['prev_close'], 102.0)        # newest bar is today's session
        self.assertAlmostEqual(q['change_pct'], 105 / 102 * 100 - 100)
        self.assertAlmostEqual(q['month_pct'], 5.0)
        self.assertEqual(q['series'], [100.0, 102.0, 104.0])
        # Market time after the newest bar (bar not yet printed): previous close is that bar.
        q = market.parse_chart('^MXX', _chart([100.0, 104.0], 105.0, mtime=1_790_000_000 + 5 * 86400))
        self.assertEqual(q['prev_close'], 104.0)

    def test_errors_never_become_numbers(self):
        with self.assertRaises(ValueError):
            market.parse_chart('X', {'chart': {'error': {'code': 'Not Found', 'description': 'No data'}, 'result': None}})

        def fake(sym):
            if sym == 'MXN=X':
                raise OSError('sin red')
            return _chart([10.0, 11.0], 12.0)
        market.fetch_chart = fake
        snap = market.snapshot(force=True)
        rows = {r['symbol']: r for g in snap['groups'] for r in g['rows']}
        self.assertIn('error', rows['MXN=X'])
        self.assertNotIn('last', rows['MXN=X'])
        self.assertEqual(rows['^MXX']['last'], 12.0)
        self.assertEqual(snap['ok'], snap['total'] - 1)
        ids = {r['strategy_id'] for r in rows.values() if r['strategy_id']}
        from quant_evidence.knowledge_base import get_strategy
        for sid in ids:
            self.assertIsNotNone(get_strategy(sid), sid)

    def test_page_has_no_embedded_quotes(self):
        html = build_app.render_page([], scan_repo=False, standalone=False, ui='terminal')
        self.assertIn('MERCADO &lt;7&gt;', html)
        self.assertNotIn('regularMarketPrice', html)


class TestPathGuard(unittest.TestCase):
    def test_rejects_escapes(self):
        for bad in ('../../etc/passwd', '/etc/passwd', 'fincept-qt/../README.md', 'README.md', '', 'a\x00b'):
            self.assertIsNone(resolve_repo_path(bad), bad)
        self.assertIsNotNone(resolve_repo_path('fincept-qt/scripts/Analytics/quant_evidence/stats.py'))


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server('127.0.0.1', 0, scan_repo=False)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=90)
        h = {'Host': f'127.0.0.1:{self.port}'}
        if body is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        c.request(method, path, body=None if body is None else json.dumps(body), headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        ctype = r.getheader('Content-Type') or ''
        return r.status, (json.loads(data) if 'json' in ctype else data.decode('utf-8'))

    def test_page_and_health(self):
        st, html = self.req('GET', '/')
        self.assertEqual(st, 200)
        self.assertIn('Fincept Quant Terminal', html)
        st, html = self.req('GET', '/studio')
        self.assertEqual(st, 200)
        self.assertIn('Fincept Quant Studio', html)
        st, j = self.req('GET', '/api/health')
        self.assertEqual(j['data']['app'], 'quant-studio')

    def test_evaluate_matches_engine(self):
        d = {'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8, 'n_trials': 50, 'periods_per_year': 12}
        st, j = self.req('POST', '/api/evaluate', d)
        self.assertTrue(j['success'])
        ref = evaluate_decision(d)
        self.assertAlmostEqual(j['data']['scores']['final'], ref['scores']['final'])
        self.assertEqual(j['data']['verdict']['code'], ref['verdict']['code'])

    def test_tool_endpoint(self):
        st, j = self.req('POST', '/api/tool/deflated_sharpe', {'sharpe_annual': 2.5, 'n_trials': 100, 'years': 5,
                                                              'periods_per_year': 250, 'var_trials_sr': 0.5,
                                                              'skew': -3, 'kurtosis': 10})
        self.assertAlmostEqual(j['data']['dsr'], 0.90, places=2)
        st, j = self.req('POST', '/api/tool/export_web', {})
        self.assertEqual(st, 404)

    def test_tree_and_file(self):
        st, j = self.req('GET', '/api/repo/tree?path=fincept-qt/scripts/Analytics/quant_evidence')
        self.assertTrue(j['success'])
        self.assertIn('stats.py', [f['name'] for f in j['data']['files']])
        st, j = self.req('GET', '/api/repo/file?path=fincept-qt/scripts/Analytics/quant_evidence/stats.py')
        self.assertIn('def deflated_sharpe_ratio', j['data']['text'])
        st, txt = self.req('GET', '/code/0.txt')
        self.assertEqual(st, 200)

    def test_traversal_is_forbidden(self):
        for p in ('../../../../etc/passwd', '/etc/passwd', 'fincept-qt/../README.md', 'fincept-qt%2F..%2F..%2Fetc%2Fpasswd'):
            st, j = self.req('GET', '/api/repo/file?path=' + p)
            self.assertEqual(st, 403, p)
            self.assertFalse(j['success'])
        st, j = self.req('GET', '/api/repo/tree?path=..')
        self.assertEqual(st, 403)

    def test_host_and_content_type_guards(self):
        st, j = self.req('GET', '/api/health', headers={'Host': 'evil.example:80'})
        self.assertEqual(st, 403)
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request('POST', '/api/evaluate', body='strategy_id=momentum',
                  headers={'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/x-www-form-urlencoded'})
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 403)

    def test_market_endpoint(self):
        saved = market.fetch_chart
        market.fetch_chart = lambda sym: _chart([1.0, 2.0], 3.0, currency='USD')
        market._cache.update(t=0.0, data=None)
        try:
            st, j = self.req('GET', '/api/market?refresh=1')
        finally:
            market.fetch_chart = saved
            market._cache.update(t=0.0, data=None)
        self.assertEqual(st, 200)
        self.assertEqual(j['data']['ok'], j['data']['total'])
        self.assertEqual([g['key'] for g in j['data']['groups']], ['mx', 'us', 'global', 'factors'])

    def test_run_cli(self):
        st, j = self.req('POST', '/api/run', {'script': 'quant_evidence', 'command': 'list', 'params': {}})
        self.assertTrue(j['success'])
        self.assertEqual(j['data']['returncode'], 0)
        self.assertIn('evaluate', j['data']['parsed']['data'])
        for bad in ({'script': 'rm', 'command': 'list'}, {'script': 'quant_evidence', 'command': 'list; rm -rf /'},
                    {'script': 'quant_evidence', 'command': 'list', 'params': [1]}):
            st, j = self.req('POST', '/api/run', bad)
            self.assertFalse(j['success'], bad)


if __name__ == '__main__':
    unittest.main()
