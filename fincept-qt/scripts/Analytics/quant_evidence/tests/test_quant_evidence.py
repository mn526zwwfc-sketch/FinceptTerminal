"""
Tests for quant_evidence. Stdlib only:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .

The formula tests reproduce the worked examples quoted in the research
report; the parity test runs web/engine.js under Node (skipped if Node is not
installed) and compares it with the Python evaluator.
"""

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ANALYTICS = os.path.dirname(PKG)
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence import stats  # noqa: E402
from quant_evidence.evaluator import evaluate_decision  # noqa: E402
from quant_evidence.knowledge_base import load_kb, organize  # noqa: E402
from quant_evidence.repo_indexer import _literal, classify_text  # noqa: E402

PARITY_CASES = [
    {'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8, 'n_trials': 50, 'periods_per_year': 12,
     'skew': -1.5, 'kurtosis': 8, 'market': 'us'},
    {'strategy_id': 'buy_hold_global', 'horizon_years': 25},
    {'strategy_id': 'ipc_calendar', 'sharpe_annual': 0.9, 'years': 10, 'n_trials': 30, 'market': 'mx',
     'horizon_years': 5},
    {'strategy_id': 'ml_cross_section', 'sharpe_annual': 2.45, 'years': 30, 'n_trials': 20,
     'periods_per_year': 12, 'investor': 'institutional', 'live_months': 24, 'kelly_multiple': 0.5},
    {'strategy_id': 'profitability_quality', 'gross_alpha_monthly_bps': 25, 'turnover_monthly': 0.1,
     'long_short': False, 'published': True},
    {'strategy_id': 'betting_against_beta'},
    {'strategy_id': 'cape_timing', 'horizon_years': 2, 'kelly_multiple': 2},
    {'strategy_id': 'tsmom_futures', 'sharpe_annual': 0.77, 'years': 40, 'n_trials': 5, 'investor': 'institutional',
     'out_of_sample': True, 'published': False, 'live_months': 60},
    {'strategy_id': 'llm_news', 'sharpe_annual': 2.97, 'years': 2.5, 'n_trials': 10, 'microcap_share': 0.8},
    {'strategy_id': 'value', 'sharpe_annual': -0.2, 'years': 15, 'n_trials': 3},
    {'strategy_id': 'kelly_full', 'kelly_multiple': 1.0, 'market': 'other'},
    {'strategy_id': 'turn_of_month', 'roundtrip_cost_bps': '5', 'turnover_monthly': '1', 'published': 'false'},
]


class TestFormulasAgainstReport(unittest.TestCase):
    def test_deflated_sharpe_example(self):
        # Bailey & Lopez de Prado: SR 2.5, 5 years daily, 100 trials -> DSR 0.90
        r = stats.deflated_sharpe_ratio(2.5, 100, 5, 250, 0.5, -3, 10)
        self.assertAlmostEqual(r['dsr'], 0.90, places=2)
        self.assertAlmostEqual(r['sr0_per_period'], 0.1132, places=4)

    def test_harvey_liu_haircut(self):
        # Sharpe 0.75, 20 years, 200 tests -> ~0.32 (a ~60% haircut)
        r = stats.haircut_sharpe(0.75, 20, 200)
        self.assertAlmostEqual(r['sharpe_haircut'], 0.32, delta=0.01)
        self.assertAlmostEqual(r['haircut_pct'], 0.58, delta=0.02)

    def test_min_backtest_length(self):
        # "if only 5 years of data are available, no more than 45 ... should be tried"
        self.assertAlmostEqual(stats.min_backtest_length(45, 1.0), 5.0, delta=0.05)
        self.assertEqual(stats.max_trials_for_length(5, 1.0), 45)
        # Report's own figures: 7 trials -> 1.9 years, 1,000 trials -> 10.6 years
        self.assertAlmostEqual(stats.min_backtest_length(7, 1.0), 1.9, delta=0.05)
        self.assertAlmostEqual(stats.min_backtest_length(1000, 1.0), 10.6, delta=0.05)
        self.assertLess(stats.min_backtest_length(1000, 1.0), 2 * math.log(1000))

    def test_bonferroni_threshold(self):
        # Harvey, Liu & Zhu: ~3.78 for Bonferroni with 316 factors
        self.assertAlmostEqual(stats.bonferroni_t_threshold(316), 3.78, delta=0.01)

    def test_bodie_put(self):
        # sigma 20%: 7.98% at 1 year, 24.84% at 10, 41.61% at 30
        self.assertAlmostEqual(stats.bodie_shortfall_put_cost(0.2, 1), 0.0798, delta=0.0005)
        self.assertAlmostEqual(stats.bodie_shortfall_put_cost(0.2, 10), 0.2484, delta=0.0005)
        self.assertAlmostEqual(stats.bodie_shortfall_put_cost(0.2, 30), 0.4161, delta=0.0005)

    def test_kelly(self):
        self.assertAlmostEqual(stats.kelly_growth_share(0.5), 0.75)
        self.assertAlmostEqual(stats.kelly_growth_share(2.0), 0.0)
        mu, r, s = 0.08, 0.02, 0.2
        f = stats.kelly_fraction(mu, r, s)
        g = lambda x: stats.growth_rate(x * f, mu, r, s) - r  # noqa: E731
        self.assertAlmostEqual(g(0.5) / g(1.0), 0.75)

    def test_campbell_thompson(self):
        # R2 0.25% monthly with S2 1.2% -> about 21% more expected return
        self.assertAlmostEqual(stats.campbell_thompson_gain(0.0025, 0.012), 0.21, delta=0.005)

    def test_cost_rule(self):
        self.assertAlmostEqual(stats.monthly_cost_bps(0.5, 20, False), 10.0)
        self.assertAlmostEqual(stats.monthly_cost_bps(0.5, 20, True), 20.0)
        self.assertAlmostEqual(stats.breakeven_roundtrip_cost_bps(10, 0.5, False), 20.0)

    def test_edge_cases(self):
        self.assertEqual(stats.expected_max_sharpe_z(1), 0.0)
        self.assertTrue(math.isinf(stats.min_backtest_length(10, 0)))
        self.assertTrue(math.isnan(stats.probabilistic_sharpe_ratio(0.1, 0, 1)))


class TestKnowledgeBase(unittest.TestCase):
    def setUp(self):
        self.kb = load_kb()

    def test_integrity(self):
        ids = [s['id'] for s in self.kb['strategies']]
        self.assertEqual(len(ids), len(set(ids)))
        cats = {c['key'] for c in self.kb['categories']}
        for s in self.kb['strategies']:
            self.assertTrue(set(s['categories']) <= cats, s['id'])
            self.assertTrue(0 <= s['prior']['score'] <= 100, s['id'])
            self.assertTrue(s['sources'], s['id'])
            for src in s['sources']:
                self.assertTrue(src['url'].startswith('http'), s['id'])
            for m in s['marks']:
                self.assertIn(m, self.kb['meta']['marks'])
            for key in ('claim', 'key_figure', 'critique', 'survives', 'section'):
                self.assertTrue(s[key], (s['id'], key))

    def test_every_category_has_a_strategy(self):
        org = organize(self.kb, {'modules': []})
        empty = [k for k, g in org['categories'].items() if not g['strategies']]
        self.assertEqual(empty, [])

    def test_baseline_is_top_ranked(self):
        best = max(self.kb['strategies'], key=lambda s: s['prior']['score'])
        self.assertEqual(best['id'], 'buy_hold_global')


class TestEvaluator(unittest.TestCase):
    def test_baseline_supported(self):
        r = evaluate_decision({'strategy_id': 'buy_hold_global', 'horizon_years': 25}, repo_map={'modules': []})
        self.assertEqual(r['verdict']['code'], 'respaldada')
        self.assertIsNone(r['net_monthly_bps'])

    def test_retail_momentum_not_supported(self):
        r = evaluate_decision(PARITY_CASES[0], repo_map={'modules': []})
        self.assertLessEqual(r['net_monthly_bps'], 0)
        self.assertLessEqual(r['scores']['final'], 29)
        self.assertEqual(r['verdict']['code'], 'no_respaldada')
        self.assertEqual([c['stage'] for c in r['cascade']],
                         ['Bruto', 'Tras pruebas múltiples', 'Tras publicación', 'Sin microcaps', 'Neto de costos'])

    def test_more_trials_never_helps(self):
        base = {'strategy_id': 'anomaly_combo', 'sharpe_annual': 1.0, 'years': 10, 'investor': 'institutional'}
        scores = [evaluate_decision(dict(base, n_trials=n), repo_map={'modules': []})['scores']['statistical']
                  for n in (1, 10, 100, 1000)]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_long_only_caps_long_short_family(self):
        r = evaluate_decision({'strategy_id': 'ml_cross_section', 'sharpe_annual': 2.0, 'years': 30,
                               'investor': 'institutional', 'long_short': False, 'microcap_share': 0,
                               'turnover_monthly': 0.1}, repo_map={'modules': []})
        self.assertEqual(r['cascade'][-1]['stage'], 'Versión solo-largo')
        self.assertEqual(r['net_monthly_bps'], 0.0)

    def test_low_dsr_cap(self):
        r = evaluate_decision({'strategy_id': 'naive_1n', 'sharpe_annual': 0.3, 'years': 3, 'n_trials': 200},
                              repo_map={'modules': []})
        self.assertLess(r['stats']['dsr'], 0.5)
        self.assertLessEqual(r['scores']['final'], 40)

    def test_mexico_defaults(self):
        r = evaluate_decision({'strategy_id': 'mexico_factors', 'market': 'mx'}, repo_map={'modules': []})
        self.assertEqual(r['inputs']['roundtrip_cost_bps'], 60.0)
        self.assertIn('market_mx', [c['id'] for c in r['checks']])

    def test_unknown_strategy(self):
        with self.assertRaises(ValueError):
            evaluate_decision({'strategy_id': 'no_existe'})

    def test_related_modules_follow_categories(self):
        repo = {'modules': [{'path': 'a.py', 'categories': ['momentum'], 'summary': 'x'},
                            {'path': 'b.py', 'categories': ['value'], 'summary': 'y'}]}
        r = evaluate_decision({'strategy_id': 'momentum'}, repo_map=repo)
        self.assertEqual([m['path'] for m in r['related_modules']], ['a.py'])


def _strip_text(result):
    """Numbers, codes and statuses only; prose is formatted per language."""
    return {
        'scores': result['scores'],
        'net': result['net_monthly_bps'],
        'net_sharpe': result['net_sharpe_estimate'],
        'verdict': result['verdict']['code'],
        'checks': [(c['id'], c['status']) for c in result['checks']],
        'cascade': [(c['stage'], c['monthly_bps']) for c in result['cascade']],
        'stats': result['stats'],
        'inputs': result['inputs'],
        'modules': [m['path'] for m in result['related_modules']],
    }


def _close(a, b, path='$'):
    if isinstance(a, dict):
        assert isinstance(b, dict) and set(a) == set(b), f'{path}: keys {sorted(a)} != {sorted(b)}'
        for k in a:
            _close(a[k], b[k], f'{path}.{k}')
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), f'{path}: length {len(a)} != {len(b)}'
        for i, (x, y) in enumerate(zip(a, b)):
            _close(x, y, f'{path}[{i}]')
    elif isinstance(a, bool) or isinstance(b, bool):
        assert a == b, f'{path}: {a!r} != {b!r}'
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isinf(a) or math.isinf(b):
            assert a == b, f'{path}: {a} != {b}'
        else:
            assert math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9), f'{path}: {a} != {b}'
    else:
        assert a == b, f'{path}: {a!r} != {b!r}'


@unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
class TestJavaScriptParity(unittest.TestCase):
    def test_engine_matches_python(self):
        repo = {'modules': [{'path': 'fincept-qt/scripts/x.py', 'categories': ['momentum', 'ml_cross_section'],
                             'summary': 's'}]}
        script = (
            "const E=require(process.argv[1]);const kb=require(process.argv[2]);"
            "const cases=JSON.parse(process.argv[3]);const repo=JSON.parse(process.argv[4]);"
            "const inf=(k,v)=>(typeof v==='number'&&!isFinite(v))?(v>0?'Infinity':'-Infinity'):v;"
            "const out={evals:cases.map(c=>E.evaluateDecision(c,kb,repo)),"
            "fx:{dsr:E.deflatedSharpeRatio(2.5,100,5,250,0.5,-3,10),hl:E.haircutSharpe(0.75,20,200),"
            "minbtl:E.minBacktestLength(45,1),maxn:E.maxTrialsForLength(5,1),ppf:[0.001,0.02,0.3,0.5,0.9,0.999999].map(E.normPpf),"
            "cdf:[-8,-3,-0.5,0,1.2,3.3,9].map(E.normCdf),bodie:E.bodieShortfallPutCost(0.2,30),"
            "loss:E.probRealLossLognormal(0.05,0.18,30)}};"
            "process.stdout.write(JSON.stringify(out,inf));")
        proc = subprocess.run(
            ['node', '-e', script, os.path.join(PKG, 'web', 'engine.js'),
             os.path.join(PKG, 'data', 'evidence_kb.json'), json.dumps(PARITY_CASES), json.dumps(repo)],
            capture_output=True, text=True, check=True)
        js = json.loads(proc.stdout, parse_constant=float)

        def fix_inf(o):
            if isinstance(o, dict):
                return {k: fix_inf(v) for k, v in o.items()}
            if isinstance(o, list):
                return [fix_inf(v) for v in o]
            if o in ('Infinity', '-Infinity'):
                return float(o)
            return o
        js = fix_inf(js)
        for case, js_res in zip(PARITY_CASES, js['evals']):
            py = _strip_text(evaluate_decision(case, repo_map=repo))
            with self.subTest(case=case['strategy_id']):
                _close(py, _strip_text(js_res))
        from statistics import NormalDist
        nd = NormalDist()
        _close(stats.deflated_sharpe_ratio(2.5, 100, 5, 250, 0.5, -3, 10), js['fx']['dsr'])
        _close(stats.haircut_sharpe(0.75, 20, 200), js['fx']['hl'])
        _close(stats.min_backtest_length(45, 1), js['fx']['minbtl'])
        self.assertEqual(stats.max_trials_for_length(5, 1), js['fx']['maxn'])
        _close([nd.inv_cdf(p) for p in (0.001, 0.02, 0.3, 0.5, 0.9, 0.999999)], js['fx']['ppf'])
        for x, y in zip([-8, -3, -0.5, 0, 1.2, 3.3, 9], js['fx']['cdf']):
            self.assertAlmostEqual(nd.cdf(x), y, delta=1e-13)
        _close(stats.bodie_shortfall_put_cost(0.2, 30), js['fx']['bodie'])
        _close(stats.prob_real_loss_lognormal(0.05, 0.18, 30), js['fx']['loss'])


class TestRepoIndexer(unittest.TestCase):
    def test_literal_prefilter(self):
        self.assertEqual(_literal(r'\bmacd\b'), 'macd')
        self.assertEqual(_literal(r'anomal(y|ies)'), 'anomal')
        self.assertEqual(_literal(r'cross[_\s-]?sectional[_\s]?momentum'), 'sectional')

    def test_classify(self):
        cats = classify_text('scripts/x/deflated_sharpe.py',
                             'def deflated_sharpe(): pass  # backtest walk-forward bonferroni')
        self.assertIn('backtest_overfitting', cats)
        self.assertIn('mexico_latam', classify_text('scripts/banxico_data.py', ''))
        self.assertEqual(classify_text('a.py', 'hello world'), {})


class TestCliAndBuild(unittest.TestCase):
    CLI = os.path.join(ANALYTICS, 'quant_evidence_cli.py')

    def _run(self, *args):
        out = subprocess.run([sys.executable, self.CLI, *args], capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_cli_evaluate_and_tools(self):
        r = self._run('evaluate', json.dumps(PARITY_CASES[0]))
        self.assertTrue(r['success'])
        self.assertEqual(r['data']['verdict']['code'], 'no_respaldada')
        r = self._run('deflated_sharpe', json.dumps({'sharpe_annual': 2.5, 'n_trials': 100, 'years': 5,
                                                     'periods_per_year': 250, 'var_trials_sr': 0.5,
                                                     'skew': -3, 'kurtosis': 10}))
        self.assertAlmostEqual(r['data']['dsr'], 0.90, places=2)
        self.assertFalse(self._run('nope')['success'])
        self.assertIn('evaluate', self._run('list')['data'])

    def test_cli_reads_json_file(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump({'strategy_id': 'buy_hold_global'}, f)
        try:
            r = self._run('evaluate', f.name)
            self.assertEqual(r['data']['verdict']['code'], 'respaldada')
        finally:
            os.unlink(f.name)

    def test_build_web(self):
        from quant_evidence.build_web import build
        with tempfile.TemporaryDirectory() as d:
            path = build(os.path.join(d, 'lab.html'), scan_repo=False)
            with open(path, encoding='utf-8') as f:
                html = f.read()
        self.assertNotIn('/*__KB__*/', html)
        self.assertNotIn('/*__ENGINE__*/', html)
        self.assertIn('window.QuantEvidence', html.replace('root.QuantEvidence', 'window.QuantEvidence'))
        self.assertIn('"buy_hold_global"', html)
        self.assertNotIn('</script>"', html)


if __name__ == '__main__':
    unittest.main()
