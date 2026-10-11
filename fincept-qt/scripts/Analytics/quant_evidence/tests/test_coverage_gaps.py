"""
Coverage-gap tests for quant_evidence: JS/Python parity over every strategy and
the stats functions the pages call, check and verdict thresholds, the server's
JSON contract, stats reference values and knowledge-base integrity. Stdlib only:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .
"""

import http.client
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS = os.path.dirname(os.path.dirname(HERE))
PKG = os.path.join(ANALYTICS, 'quant_evidence')
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence import stats  # noqa: E402
from quant_evidence.evaluator import MICROCAP_ALPHA_SHARE, VERDICTS, evaluate_decision  # noqa: E402
from quant_evidence.knowledge_base import list_strategies, load_kb, load_repo_map, organize  # noqa: E402
from quant_evidence.tests.test_quant_evidence import _close, _strip_text  # noqa: E402

NO_REPO = {'modules': []}


def _node(script, *args):
    """Run a Node snippet; Infinity/NaN are passed back as strings and restored."""
    wrapped = ("const E=require(process.argv[1]);const kb=require(process.argv[2]);"
               "const A=process.argv.slice(3).map(a=>JSON.parse(a));"
               "const inf=(k,v)=>(typeof v==='number'&&!isFinite(v))?(v!==v?'NaN':v>0?'Infinity':'-Infinity'):v;"
               "const out=(()=>{" + script + "})();process.stdout.write(JSON.stringify(out,inf));")
    proc = subprocess.run(['node', '-e', wrapped, os.path.join(PKG, 'web', 'engine.js'),
                           os.path.join(PKG, 'data', 'evidence_kb.json'), *[json.dumps(a) for a in args]],
                          capture_output=True, text=True, check=True)

    def fix(o):
        if isinstance(o, dict):
            return {k: fix(v) for k, v in o.items()}
        if isinstance(o, list):
            return [fix(v) for v in o]
        return float(o) if o in ('Infinity', '-Infinity', 'NaN') else o
    return fix(json.loads(proc.stdout))


# ── 2. Parity over EVERY strategy in the KB, three input profiles ─────────────
@unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
class TestParityAllStrategies(unittest.TestCase):
    PROFILES = [
        {},
        {'sharpe_annual': 0.8, 'years': 12, 'n_trials': 25, 'live_months': 6, 'kelly_multiple': 0.75},
        {'sharpe_annual': 1.5, 'years': 20, 'n_trials': 3, 'investor': 'institutional', 'published': False,
         'live_months': 40, 'market': 'mx', 'horizon_years': 4, 'periods_per_year': 52, 'skew': -0.5,
         'kurtosis': 5},
    ]

    def test_every_strategy_every_profile(self):
        repo = {'modules': [{'path': 'x.py', 'categories': ['momentum', 'value', 'calendar_effects']}]}
        cases = [dict(p, strategy_id=s['id']) for s in load_kb()['strategies'] for p in self.PROFILES]
        js = _node("return A[0].map(c=>E.evaluateDecision(c,kb,A[1]));", cases, repo)
        self.assertEqual(len(js), 44 * 3)
        for case, js_res in zip(cases, js):
            with self.subTest(case=case):
                _close(_strip_text(evaluate_decision(case, repo_map=repo)), _strip_text(js_res))


# ── 4. Stats-level parity for functions the UIs call but the parity test skips ──
@unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
class TestParityStatsFunctions(unittest.TestCase):
    def test_stats_grid(self):
        js = _node(
            "return {"
            "emz:[1,2,7,45,1000,1e6].map(E.expectedMaxSharpeZ),"
            "psr:[[0.1,0,101,0,3],[0.05,0.02,60,-1,6],[0.3,0,2,0,3],[0.1,0,1,0,3],[1.2,0,100,5,3]]"
            ".map(a=>E.probabilisticSharpeRatio(...a)),"
            "hs:[[0.75,20,200,'sidak'],[1.0,10,50,'sidak'],[-0.5,10,10,'sidak'],[0.4,0,10]].map(a=>E.haircutSharpe(...a)),"
            "adj:[[0.01,10,'sidak'],[0.5,3,'sidak'],[1,5,'sidak'],[0.02,0,'bonferroni']].map(a=>E.adjustPvalue(...a)),"
            "bt:[[1],[316],[100,0.01]].map(a=>E.bonferroniTThreshold(...a)),"
            "pv:[0,1.96,3,8.5,40].map(E.tToPvalue),"
            "kf:[[0.08,0.02,0.2],[0.08,0.02,0.2,3],[0.02,0.02,0],[0.01,0.02,0]].map(a=>E.kellyFraction(...a)),"
            "gr:[[0.5,0.08,0.02,0.2],[3,0.08,0.02,0.2]].map(a=>E.growthRate(...a)),"
            "be:[[10,0.5,false],[10,0.5,true],[10,0,false]].map(a=>E.breakevenRoundtripCostBps(...a)),"
            "ct:[[0.0025,0.012],[0.01,0]].map(a=>E.campbellThompsonGain(...a)),"
            "ppf:[0,1,1e-300].map(E.normPpf),cdf:[-40,40].map(E.normCdf),"
            "loss:[[0.05,0.18,0],[0.05,0,30]].map(a=>E.probRealLossLognormal(...a))};")
        _close([stats.expected_max_sharpe_z(n) for n in (1, 2, 7, 45, 1000, 10**6)], js['emz'])
        _close([stats.probabilistic_sharpe_ratio(*a) for a in
                ((0.1, 0, 101, 0, 3), (0.05, 0.02, 60, -1, 6), (0.3, 0, 2, 0, 3), (0.1, 0, 1, 0, 3),
                 (1.2, 0, 100, 5, 3))], js['psr'])
        _close([stats.haircut_sharpe(0.75, 20, 200, 'sidak'), stats.haircut_sharpe(1.0, 10, 50, 'sidak'),
                stats.haircut_sharpe(-0.5, 10, 10, 'sidak'), stats.haircut_sharpe(0.4, 0, 10)], js['hs'])
        _close([stats.adjust_pvalue(0.01, 10, 'sidak'), stats.adjust_pvalue(0.5, 3, 'sidak'),
                stats.adjust_pvalue(1, 5, 'sidak'), stats.adjust_pvalue(0.02, 0)], js['adj'])
        _close([stats.bonferroni_t_threshold(1), stats.bonferroni_t_threshold(316),
                stats.bonferroni_t_threshold(100, 0.01)], js['bt'])
        for t, p in zip((0, 1.96, 3, 8.5, 40), js['pv']):  # erfc vs 2*Phi(-|t|): JS is ~1e-8 relative at t=8.5
            self.assertTrue(math.isclose(stats.t_to_pvalue(t), p, rel_tol=1e-7, abs_tol=1e-300), t)
        _close([stats.kelly_fraction(0.08, 0.02, 0.2), stats.kelly_fraction(0.08, 0.02, 0.2, 3),
                stats.kelly_fraction(0.02, 0.02, 0), stats.kelly_fraction(0.01, 0.02, 0)], js['kf'])
        _close([stats.growth_rate(0.5, 0.08, 0.02, 0.2), stats.growth_rate(3, 0.08, 0.02, 0.2)], js['gr'])
        _close([stats.breakeven_roundtrip_cost_bps(10, 0.5, False), stats.breakeven_roundtrip_cost_bps(10, 0.5, True),
                stats.breakeven_roundtrip_cost_bps(10, 0, False)], js['be'])
        _close([stats.campbell_thompson_gain(0.0025, 0.012), stats.campbell_thompson_gain(0.01, 0)], js['ct'])
        _close([stats.norm_ppf(0), stats.norm_ppf(1)], js['ppf'][:2])
        self.assertTrue(math.isclose(stats.norm_ppf(1e-300), js['ppf'][2], rel_tol=1e-9))
        _close([stats.norm_cdf(-40), stats.norm_cdf(40)], js['cdf'])
        _close([stats.prob_real_loss_lognormal(0.05, 0.18, 0), stats.prob_real_loss_lognormal(0.05, 0, 30)],
               js['loss'])


# ── 5. Check-status boundaries (>= vs >) ──────────────────────────────────────
class TestCheckBoundaries(unittest.TestCase):
    def status(self, raw, cid):
        r = evaluate_decision(dict({'strategy_id': 'turn_of_month'}, **raw), repo_map=NO_REPO)
        return {c['id']: c['status'] for c in r['checks']}.get(cid), r

    def test_thresholds(self):
        table = [
            ({'turnover_monthly': 0.5}, 'turnover', 'pass'), ({'turnover_monthly': 0.5001}, 'turnover', 'warn'),
            ({'turnover_monthly': 1.0}, 'turnover', 'warn'), ({'turnover_monthly': 1.0001}, 'turnover', 'fail'),
            ({'live_months': 11.99}, 'live', 'fail'), ({'live_months': 12}, 'live', 'warn'),
            ({'live_months': 35.99}, 'live', 'warn'), ({'live_months': 36}, 'live', 'pass'),
            ({'kelly_multiple': 0.5}, 'kelly', 'pass'), ({'kelly_multiple': 0.51}, 'kelly', 'warn'),
            ({'kelly_multiple': 1.0}, 'kelly', 'warn'), ({'kelly_multiple': 1.01}, 'kelly', 'fail'),
            ({'horizon_years': 9.99}, 'horizon', 'warn'), ({'horizon_years': 10}, 'horizon', 'pass'),
            ({'microcap_share': 0.29}, 'microcaps', None), ({'microcap_share': 0.3}, 'microcaps', 'warn'),
            ({'microcap_share': 0.49}, 'microcaps', 'warn'), ({'microcap_share': 0.5}, 'microcaps', 'fail'),
            ({'long_short': True}, 'access', 'warn'), ({'long_short': True, 'uses_leverage': True}, 'access', 'fail'),
            ({'long_short': True, 'investor': 'institutional'}, 'access', None),
        ]
        for raw, cid, want in table:
            with self.subTest(raw=raw, check=cid):
                self.assertEqual(self.status(raw, cid)[0], want)

    def test_context_score_steps(self):
        ctx = lambda h: self.status({'horizon_years': h, 'live_months': 36}, 'horizon')[1]['scores']['context']  # noqa: E731
        # global market 1.0, live 36m 1.0, horizon step 0.3 / 0.7 / 1.0
        self.assertAlmostEqual(ctx(2.99), 100 * (1 + 0.3 + 1) / 3)
        self.assertAlmostEqual(ctx(3), 100 * (1 + 0.7 + 1) / 3)
        self.assertAlmostEqual(ctx(10), 100.0)

    def test_twelve_live_months_count_as_out_of_sample(self):
        stages = lambda m: [c['stage'] for c in self.status({'published': False, 'live_months': m}, 'live')[1]['cascade']]  # noqa: E731
        self.assertIn('Fuera de muestra', stages(11))
        self.assertNotIn('Fuera de muestra', stages(12))


# ── 6. Verdict thresholds with a synthetic KB (final = 0.5 * prior + 50) ──────
class TestVerdictThresholds(unittest.TestCase):
    def kb(self, prior, family='base', ev=None):
        base = load_kb()
        s = {'id': 'synthetic', 'name': 'S', 'family': family, 'categories': [], 'claim': 'c', 'key_figure': 'k',
             'critique': 'c', 'survives': 's.', 'marks': [], 'sources': [], 'prior': {'score': prior},
             'evidence': dict({'typical_turnover_monthly': 0.0, 'requires_short': False,
                               'requires_leverage': False, 'microcap_dependence': 'baja'}, **(ev or {}))}
        return {'strategies': [s], 'categories': [], 'meta': base['meta'], 'habits': []}

    def run_(self, prior, **kw):
        return evaluate_decision({'strategy_id': 'synthetic', 'horizon_years': 25}, kb=self.kb(prior, **kw),
                                 repo_map=NO_REPO)

    def test_threshold_edges(self):
        expected = {40: 'respaldada', 39.98: 'condicionada', 0: 'condicionada'}
        for prior, code in expected.items():
            with self.subTest(prior=prior):
                r = self.run_(prior)
                self.assertAlmostEqual(r['scores']['final'], 0.5 * prior + 50)
                self.assertEqual(r['verdict']['code'], code)
        self.assertEqual([v[0] for v in VERDICTS], [70, 50, 30, 0])

    def test_net_edge_cap_hits_exactly_29(self):
        r = self.run_(100, family='factores', ev={'net_monthly_bps': 0})
        self.assertEqual(r['scores']['final'], 29.0)
        self.assertEqual(r['verdict']['code'], 'no_respaldada')
        self.assertTrue(r['verdict']['summary'].startswith('No respaldada por la evidencia (29/100)'))
        self.assertEqual(len(r['caps']), 1)

    def test_empty_sources_does_not_crash(self):
        self.assertIsNone(self.run_(50)['checks'][0]['source'])


# ── 7. Server: strict JSON for non-finite stats + error routes ────────────────
class TestServerContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from quant_evidence.app.server import make_server
        cls.srv = make_server('127.0.0.1', 0, scan_repo=False)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def raw(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        h = {'Host': f'127.0.0.1:{self.port}', 'Content-Type': 'application/json'}
        h.update(headers or {})
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    @staticmethod
    def strict(data):
        def bad(c):
            raise ValueError(f'non-standard JSON constant {c}')
        return json.loads(data, parse_constant=bad)

    def test_non_finite_stats_become_null(self):
        st, data = self.raw('POST', '/api/evaluate', json.dumps({'strategy_id': 'value', 'sharpe_annual': -0.2,
                                                                 'years': 15, 'n_trials': 3}))
        self.assertEqual(st, 200)
        j = self.strict(data)
        self.assertIsNone(j['data']['stats']['min_backtest_years'])   # inf in Python
        st, data = self.raw('POST', '/api/evaluate', json.dumps({'strategy_id': 'momentum', 'sharpe_annual': 1.2,
                                                                 'years': 8, 'skew': 5,
                                                                 'periods_per_year': 12}))
        self.assertIsNone(self.strict(data)['data']['stats']['dsr'])  # NaN in Python

    def test_error_paths(self):
        cases = [
            ('POST', '/api/evaluate', json.dumps({'strategy_id': 'no_existe'}), None, 400),
            ('POST', '/api/evaluate', '[1, 2]', None, 400),
            ('POST', '/api/evaluate', '{not json', None, 400),
            ('POST', '/api/evaluate', '{}', {'Content-Length': '999999'}, 400),
            ('POST', '/api/nope', '{}', None, 404),
            ('GET', '/api/nope', None, None, 404),
            ('GET', '/code/999999.txt', None, None, 404),
            ('GET', '/api/health', None, {'Host': f'[::1]:{self.port}'}, 200),
        ]
        for method, path, body, headers, want in cases:
            with self.subTest(path=path, body=body, headers=headers):
                st, data = self.raw(method, path, body, headers)
                self.assertEqual(st, want)
                if want != 200:
                    self.assertFalse(self.strict(data)['success'])

    def test_read_only_endpoints(self):
        st, data = self.raw('GET', '/api/kb')
        self.assertEqual(len(self.strict(data)['data']['strategies']), len(load_kb()['strategies']))
        st, data = self.raw('GET', '/api/run/list')
        self.assertEqual([r['id'] for r in self.strict(data)['data']][0], 'quant_evidence')
        st, data = self.raw('GET', '/api/repo-map')
        self.assertIn('modules', self.strict(data)['data'])


# ── 8. Reference values and guards for stats functions without tests ─────────
class TestStatsReferenceValues(unittest.TestCase):
    def test_mclean_pontiff_decay(self):
        # McLean & Pontiff (2016): -26% out of sample, -58% after publication
        self.assertAlmostEqual(stats.decayed_alpha(100, published=True, out_of_sample=False), 42.0)
        self.assertAlmostEqual(stats.decayed_alpha(100, published=False, out_of_sample=False), 74.0)
        self.assertAlmostEqual(stats.decayed_alpha(100, published=False, out_of_sample=True), 100.0)
        self.assertAlmostEqual(stats.decayed_alpha(100, published=True, out_of_sample=True), 42.0)

    def test_t_and_p_conventions(self):
        # Harvey, Liu & Zhu: t = 3.0 <-> two-sided p ~ 0.27%; t = 1.96 <-> 5%
        self.assertAlmostEqual(stats.t_to_pvalue(3.0), 0.0027, delta=0.00005)
        self.assertAlmostEqual(stats.pvalue_to_t(0.05), 1.959964, places=6)
        self.assertAlmostEqual(stats.pvalue_to_t(stats.t_to_pvalue(2.5)), 2.5, places=9)
        self.assertAlmostEqual(stats.bonferroni_t_threshold(1), 1.959964, places=6)

    def test_psr_closed_form(self):
        # skew 0, kurtosis 3: PSR = Phi(SR sqrt(T-1) / sqrt(1 + SR^2/2))
        self.assertAlmostEqual(stats.probabilistic_sharpe_ratio(0.1, 0.0, 101),
                               stats.norm_cdf(1.0 / math.sqrt(1.005)), places=12)
        self.assertAlmostEqual(stats.probabilistic_sharpe_ratio(0.1, 0.0, 101), 0.8407, places=4)
        self.assertAlmostEqual(stats.probabilistic_sharpe_ratio(0.0, 0.0, 50), 0.5)
        self.assertTrue(math.isnan(stats.probabilistic_sharpe_ratio(1.2, 0, 100, skew=5)))

    def test_sidak_haircut_is_milder_than_bonferroni(self):
        b = stats.haircut_sharpe(0.75, 20, 200)
        s = stats.haircut_sharpe(0.75, 20, 200, 'sidak')
        self.assertEqual(s['method'], 'sidak')
        self.assertGreaterEqual(s['sharpe_haircut'], b['sharpe_haircut'])
        self.assertAlmostEqual(s['sharpe_haircut'], b['sharpe_haircut'], delta=0.01)

    def test_guards(self):
        self.assertEqual(stats.norm_ppf(1.0), math.inf)
        self.assertEqual(stats.norm_ppf(0.0), -math.inf)
        self.assertEqual(stats.max_trials_for_length(0, 1.0), 1)
        self.assertEqual(stats.max_trials_for_length(5, 0), 1)
        self.assertEqual(stats.campbell_thompson_gain(0.01, 0), math.inf)
        self.assertTrue(math.isnan(stats.prob_real_loss_lognormal(0.05, 0.18, 0)))
        self.assertEqual(stats.breakeven_roundtrip_cost_bps(10, 0), math.inf)
        r = stats.haircut_sharpe(0.5, 0, 10)
        self.assertEqual((r['sharpe_haircut'], r['haircut_pct']), (0.0, 1.0))


# ── 9. Extended KB integrity ──────────────────────────────────────────────────
class TestKnowledgeBaseIntegrityExtended(unittest.TestCase):
    def setUp(self):
        self.kb = load_kb()

    def test_schema(self):
        keys = [c['key'] for c in self.kb['categories']]
        self.assertEqual(len(keys), len(set(keys)))
        families = {'base', 'factores', 'machine learning', 'timing', 'calendario', 'cartera', 'comportamiento'}
        for s in self.kb['strategies']:
            with self.subTest(strategy=s['id']):
                self.assertRegex(s['id'], r'^[a-z0-9_]+$')
                self.assertIn(s['family'], families)
                self.assertTrue(s['categories'])
                self.assertEqual(len(s['categories']), len(set(s['categories'])))
                score = s['prior']['score']
                self.assertIsInstance(score, (int, float))
                self.assertNotIsInstance(score, bool)
                self.assertTrue(s['prior']['rationale'])
                ev = s['evidence']
                self.assertIn(ev['microcap_dependence'], MICROCAP_ALPHA_SHARE)  # else silent 5% default
                self.assertIsInstance(ev['requires_short'], bool)
                self.assertIsInstance(ev['requires_leverage'], bool)
                for k in ('gross_monthly_bps', 'net_monthly_bps', 'typical_turnover_monthly'):
                    self.assertTrue(ev[k] is None or (isinstance(ev[k], (int, float)) and not isinstance(ev[k], bool)),
                                    k)
                if ev['typical_turnover_monthly'] is not None:
                    self.assertGreaterEqual(ev['typical_turnover_monthly'], 0)
                if ev['gross_monthly_bps'] is not None and ev['net_monthly_bps'] is not None:
                    self.assertLessEqual(ev['net_monthly_bps'], ev['gross_monthly_bps'])
                for src in s['sources']:
                    self.assertTrue(src['label'].strip())
                    self.assertTrue(src['url'].startswith('https://') or src['url'].startswith('http://'))

    def test_every_strategy_evaluates_with_defaults(self):
        for s in self.kb['strategies']:
            with self.subTest(strategy=s['id']):
                r = evaluate_decision({'strategy_id': s['id']}, repo_map=NO_REPO)
                self.assertTrue(0 <= r['scores']['final'] <= 100)
                self.assertIn(r['verdict']['code'], [v[1] for v in VERDICTS])


# ── 10. knowledge_base helpers: list_strategies / organize / load_repo_map ────
class TestKnowledgeBaseHelpers(unittest.TestCase):
    def test_list_strategies_sorted_and_filtered(self):
        rows = list_strategies()
        self.assertEqual(len(rows), len(load_kb()['strategies']))
        self.assertEqual([r['prior'] for r in rows], sorted((r['prior'] for r in rows), reverse=True))
        self.assertEqual(rows[0]['id'], 'buy_hold_global')
        fam = list_strategies(family='calendario')
        self.assertEqual({r['family'] for r in fam}, {'calendario'})
        self.assertEqual(len(fam), 5)
        mom = list_strategies(category='momentum')
        self.assertIn('momentum', [r['id'] for r in mom])
        self.assertEqual(list_strategies(family='no_such_family'), [])

    def test_organize_places_modules(self):
        repo = {'modules': [{'path': 'b.py', 'categories': ['momentum', 'value'], 'summary_es': 'es'},
                            {'path': 'a.py', 'categories': ['momentum'], 'summary': 'en'},
                            {'path': 'z.py', 'categories': ['not_a_category']},
                            {'path': 'y.py'}],
                'gaps': ['g1']}
        org = organize(repo_map=repo)
        mom = org['categories']['momentum']
        self.assertEqual([m['path'] for m in mom['modules']], ['a.py', 'b.py'])
        self.assertEqual(mom['modules'][1]['summary'], 'es')
        self.assertEqual([m['path'] for m in org['categories']['value']['modules']], ['b.py'])
        self.assertEqual(org['uncategorized_modules'], ['z.py', 'y.py'])
        self.assertEqual(org['gaps'], ['g1'])
        self.assertEqual(mom['best_prior'], max(s['prior'] for s in mom['strategies']))

    def test_missing_repo_map_is_empty(self):
        self.assertEqual(load_repo_map('/nonexistent/repo_map.json'), {'modules': [], 'gaps': []})


if __name__ == '__main__':
    unittest.main()
