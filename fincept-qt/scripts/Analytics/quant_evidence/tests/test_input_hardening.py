"""
Input hardening for the evaluator and the stats helpers (Python and the
web/engine.js port). Stdlib only:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .

Each class covers one defect found in review: values that were silently
dropped or misread (decimal commas, "n/a" Sharpe ratios, half a backtest,
negative volatility or Kelly multiples, upper-case market codes, unknown
boolean words), stats functions that accepted impossible parameters, a
numerically unstable E[max_N], and results that shared the cached catalog.
The parity class runs the same inputs through engine.js under Node.
"""

import copy
import json
import math
import os
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ANALYTICS = os.path.dirname(PKG)
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence import stats  # noqa: E402
from quant_evidence.evaluator import (WEIGHTS_NO_STATS, WEIGHTS_WITH_STATS, _bool, _num,  # noqa: E402
                                      evaluate_decision)
from quant_evidence.knowledge_base import get_strategy, load_kb  # noqa: E402
from quant_evidence.tests.test_quant_evidence import _close, _strip_text  # noqa: E402

NO_REPO = {'modules': []}


def _ev(raw):
    return evaluate_decision(raw, repo_map=NO_REPO)


def _checks(result):
    return {c['id']: c for c in result['checks']}


def _node(script, *args):
    """Run a Node snippet against engine.js; Infinity/NaN come back as strings and are restored."""
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


# ── 1. Decimal comma and backtest inputs that do not parse ───────────────────
class TestBacktestInputs(unittest.TestCase):
    def test_num_accepts_decimal_comma(self):
        self.assertEqual(_num('0,4'), 0.4)
        self.assertEqual(_num(' -1,5e2 '), -150.0)
        self.assertEqual(_num('3,'), 3.0)
        self.assertIsNone(_num('1,000.5'))   # mixed separators: ambiguous, rejected
        self.assertIsNone(_num('1,2,3'))

    def test_decimal_comma_sharpe_keeps_the_backtest(self):
        r = _ev({'strategy_id': 'momentum', 'sharpe_annual': '1,2', 'years': '8', 'n_trials': 50})
        self.assertTrue(r['inputs']['has_backtest'])
        self.assertEqual(r['inputs']['sharpe_annual'], 1.2)
        self.assertNotIn('backtest_inputs', _checks(r))

    def test_unparseable_sharpe_is_flagged_not_silently_dropped(self):
        raw = {'strategy_id': 'buy_hold_global', 'sharpe_annual': 'n/a', 'years': 5, 'n_trials': 200}
        r = _ev(raw)
        c = _checks(r).get('backtest_inputs')
        self.assertIsNotNone(c, 'a Sharpe that does not parse must produce a warning check')
        self.assertEqual(c['status'], 'fail')
        self.assertIn('Sharpe', c['detail'])
        self.assertIn('n/a', c['detail'])
        # Scoring is otherwise unchanged: same as giving no backtest at all
        ref = _ev({'strategy_id': 'buy_hold_global'})
        self.assertIsNone(r['stats'])
        self.assertAlmostEqual(r['scores']['final'], ref['scores']['final'])

    def test_unparseable_or_nonpositive_years(self):
        for years in ('cinco', [5], 0, -3):
            with self.subTest(years=years):
                c = _checks(_ev({'strategy_id': 'momentum', 'sharpe_annual': 1.0, 'years': years}))
                self.assertEqual(c['backtest_inputs']['status'], 'fail')
                self.assertIn('años', c['backtest_inputs']['detail'])

    def test_only_one_of_the_pair(self):
        for raw in ({'sharpe_annual': 1.2}, {'years': 8}, {'sharpe_annual': 1.2, 'years': '  '}):
            with self.subTest(raw=raw):
                r = _ev(dict(raw, strategy_id='momentum'))
                self.assertIsNone(r['stats'])
                self.assertEqual(_checks(r)['backtest_inputs']['status'], 'fail')

    def test_no_flag_when_both_valid_or_both_absent(self):
        for raw in ({}, {'sharpe_annual': 1.2, 'years': 8}, {'sharpe_annual': '', 'years': None},
                    {'sharpe_annual': ' ', 'years': ''}):
            with self.subTest(raw=raw):
                self.assertNotIn('backtest_inputs', _checks(_ev(dict(raw, strategy_id='momentum'))))


# ── 2. Boolean words ──────────────────────────────────────────────────────────
class TestBool(unittest.TestCase):
    def test_true_and_false_words(self):
        for s in ('1', 'true', 'si', 'sí', 'yes', 'y', 'verdadero', 'on', 't', 's', ' SÍ ', 'True', 'ON'):
            with self.subTest(s=s):
                self.assertIs(_bool(s, False), True)
        for s in ('0', 'false', 'no', 'n', 'falso', 'off', 'f', ' No ', 'FALSO'):
            with self.subTest(s=s):
                self.assertIs(_bool(s, True), False)

    def test_unknown_word_returns_default(self):
        for s in ('maybe', 'quizás', '2', '  '):
            with self.subTest(s=s):
                self.assertIs(_bool(s, True), True)
                self.assertIs(_bool(s, False), False)

    def test_unknown_published_keeps_default_in_evaluator(self):
        r = _ev({'strategy_id': 'momentum', 'published': 'tal vez'})
        self.assertIs(r['inputs']['published'], True)


# ── 3. Market and investor normalization ──────────────────────────────────────
class TestMarketInvestor(unittest.TestCase):
    def test_case_and_whitespace(self):
        r = _ev({'strategy_id': 'ipc_calendar', 'market': ' MX ', 'investor': 'Institutional'})
        self.assertEqual(r['inputs']['market'], 'mx')
        self.assertEqual(r['inputs']['investor'], 'institutional')
        self.assertIn('market_mx', _checks(r))
        self.assertAlmostEqual(r['inputs']['roundtrip_cost_bps'], 15 * 1.5)

    def test_non_string_is_treated_as_missing(self):
        for raw in ({'investor': ['institutional']}, {'market': ['mx']}, {'market': {'k': 1}},
                    {'investor': {'k': 1}}, {'market': 5}):
            with self.subTest(raw=raw):
                r = _ev(dict(raw, strategy_id='momentum'))  # TypeError (unhashable) before the fix
                self.assertEqual(r['inputs']['investor'], 'retail')
                self.assertEqual(r['inputs']['market'], 'global')

    def test_unknown_string_still_maps_to_fallback(self):
        r = _ev({'strategy_id': 'momentum', 'market': 'Japón', 'investor': 'Whale'})
        self.assertEqual((r['inputs']['market'], r['inputs']['investor']), ('other', 'retail'))


# ── 4. Numeric strings: plain decimal forms only ──────────────────────────────
class TestNumericForms(unittest.TestCase):
    def test_only_plain_decimal_forms(self):
        ok = {' 7 ': 7.0, '1e3': 1000.0, '.5': 0.5, '+2': 2.0, '-0,25': -0.25, '\t3.5\n': 3.5, '2E-2': 0.02}
        for s, v in ok.items():
            with self.subTest(s=s):
                self.assertEqual(_num(s), v)
        for s in ('0x10', '0b11', '1_000', '١٢', 'inf', 'nan', 'Infinity', '1e999', '--1', '1 2', 'e3', '.', ','):
            with self.subTest(s=s):
                self.assertIsNone(_num(s))

    def test_huge_integer_is_rejected_not_overflow(self):
        self.assertIsNone(_num(10 ** 400))

    def test_non_strings(self):
        self.assertEqual(_num(3), 3.0)
        self.assertEqual(_num(True), 1.0)
        self.assertIsNone(_num([1]))
        self.assertIsNone(_num(float('nan')))


# ── 5. Stats guards ───────────────────────────────────────────────────────────
class TestStatsGuards(unittest.TestCase):
    def test_unknown_adjustment_method(self):
        with self.assertRaises(ValueError) as cm:
            stats.adjust_pvalue(0.01, 10, 'bonferoni')
        self.assertIn('sidak', str(cm.exception))
        self.assertIn('bonferroni', str(cm.exception))
        with self.assertRaises(ValueError):
            stats.haircut_sharpe(0.75, 20, 200, 'fdr')
        self.assertAlmostEqual(stats.adjust_pvalue(0.01, 10, 'holm'), 0.1)  # top test: Holm == Bonferroni
        self.assertAlmostEqual(stats.adjust_pvalue(0.01, 10), 0.1)

    def test_negative_sigma(self):
        for fn in (lambda: stats.bodie_shortfall_put_cost(-0.2, 10),
                   lambda: stats.kelly_fraction(0.08, 0.02, -0.2)):
            with self.assertRaises(ValueError) as cm:
                fn()
            self.assertIn('sigma debe ser >= 0', str(cm.exception))
        self.assertEqual(stats.bodie_shortfall_put_cost(0.0, 10), 0.0)
        self.assertEqual(stats.kelly_fraction(0.02, 0.02, 0.0), 0.0)
        self.assertEqual(stats.kelly_fraction(0.03, 0.02, 0.0), math.inf)

    def test_negative_trial_variance(self):
        with self.assertRaises(ValueError):
            stats.deflated_sharpe_ratio(1.0, 10, 5, 252, -0.1)
        self.assertEqual(stats.deflated_sharpe_ratio(1.0, 10, 5, 252, 0.0)['sr0_annual'], 0.0)

    def test_value_errors_surface_through_evaluate(self):
        with self.assertRaises(ValueError):
            _ev({'strategy_id': 'momentum', 'sharpe_annual': 1.0, 'years': 5, 'var_trials_sr': -1})

    def test_cli_wraps_value_errors_in_its_envelope(self):
        cli = os.path.join(ANALYTICS, 'quant_evidence_cli.py')
        for cmd, params in (('evaluate', {'strategy_id': 'momentum', 'sharpe_annual': 1.0, 'years': 5,
                                          'var_trials_sr': -1}),
                            ('haircut_sharpe', {'sharpe_annual': 0.75, 'years': 20, 'n_tests': 200,
                                                'method': 'nope'})):
            with self.subTest(cmd=cmd):
                proc = subprocess.run([sys.executable, cli, cmd, json.dumps(params)],
                                      capture_output=True, text=True, timeout=60)
                out = json.loads(proc.stdout)
                self.assertFalse(out['success'])
                self.assertTrue(out['error'])


# ── 6. Negative volatility and Kelly multiple ─────────────────────────────────
class TestNegativeVolatilityAndKelly(unittest.TestCase):
    def test_negative_volatility_falls_back_with_warning(self):
        base = {'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8, 'n_trials': 50}
        r = _ev(dict(base, volatility_annual=-0.3))
        self.assertEqual(r['inputs']['volatility_annual'], 0.15)
        c = _checks(r).get('inputs')
        self.assertIsNotNone(c)
        self.assertEqual(c['status'], 'warn')
        self.assertIn('volatilidad', c['detail'])
        ref = _ev(base)
        self.assertEqual(r['scores'], ref['scores'])
        self.assertEqual(r['net_monthly_bps'], ref['net_monthly_bps'])
        self.assertNotIn('inputs', _checks(ref))
        self.assertNotIn('inputs', _checks(_ev(dict(base, volatility_annual=0))))

    def test_negative_kelly_fails(self):
        r = _ev({'strategy_id': 'cape_timing', 'kelly_multiple': -1})
        self.assertEqual(_checks(r)['kelly']['status'], 'fail')
        over = _ev({'strategy_id': 'cape_timing', 'kelly_multiple': 2})  # also a 0 context item
        self.assertAlmostEqual(r['scores']['context'], over['scores']['context'])
        ok = _ev({'strategy_id': 'cape_timing', 'kelly_multiple': 0})
        self.assertEqual(_checks(ok)['kelly']['status'], 'pass')


# ── 7. E[max_N] stays finite for huge N ───────────────────────────────────────
class TestExpectedMaxSharpeZ(unittest.TestCase):
    @staticmethod
    def _old(n):
        g = stats.EULER_GAMMA
        return (1 - g) * stats.norm_ppf(1 - 1 / n) + g * stats.norm_ppf(1 - 1 / (n * math.e))

    def test_unchanged_for_normal_n(self):
        for n in (2, 10, 45, 100, 1000, 10 ** 6):
            with self.subTest(n=n):
                self.assertAlmostEqual(stats.expected_max_sharpe_z(n), self._old(n), delta=1e-9)

    def test_finite_for_huge_n(self):
        z15, z16 = stats.expected_max_sharpe_z(10 ** 15), stats.expected_max_sharpe_z(10 ** 16)
        self.assertTrue(math.isfinite(z16))
        self.assertGreater(z16, z15)
        self.assertLess(z16, 10)
        self.assertTrue(math.isfinite(stats.min_backtest_length(10 ** 16, 1.0)))


# ── 8. Results never share the cached catalog ─────────────────────────────────
class TestResultIsolation(unittest.TestCase):
    def test_mutating_a_result_does_not_touch_the_cache(self):
        before_s = copy.deepcopy(get_strategy('momentum'))
        before_habits = copy.deepcopy(load_kb()['habits'])
        before_w = (dict(WEIGHTS_WITH_STATS), dict(WEIGHTS_NO_STATS))
        r = _ev({'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8})
        r['strategy']['categories'].append('MUTATED')
        r['strategy']['marks'].append('MUTATED')
        r['sources'].append({'label': 'x', 'url': 'y'})
        if r['sources']:
            r['sources'][0]['label'] = 'MUTATED'
        r['habits'].append('MUTATED')
        r['weights']['prior'] = 99
        for c in r['checks']:
            if c['source']:
                c['source']['label'] = 'MUTATED'
        self.assertEqual(get_strategy('momentum'), before_s)
        self.assertEqual(load_kb()['habits'], before_habits)
        self.assertEqual((WEIGHTS_WITH_STATS, WEIGHTS_NO_STATS), before_w)
        r2 = _ev({'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8})
        self.assertNotIn('MUTATED', json.dumps(r2, default=str))


# ── 9. Parity with web/engine.js ──────────────────────────────────────────────
PARITY_CASES = [
    {'strategy_id': 'buy_hold_global', 'sharpe_annual': 'n/a', 'years': 5, 'n_trials': 200},
    {'strategy_id': 'momentum', 'sharpe_annual': '1,2', 'years': '8', 'n_trials': 50},
    {'strategy_id': 'momentum', 'sharpe_annual': 1.2},
    {'strategy_id': 'momentum', 'years': 8},
    {'strategy_id': 'momentum', 'sharpe_annual': 1.0, 'years': 0},
    {'strategy_id': 'momentum', 'sharpe_annual': 1.0, 'years': [5]},
    {'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8, 'volatility_annual': -0.3},
    {'strategy_id': 'cape_timing', 'kelly_multiple': -1},
    {'strategy_id': 'ipc_calendar', 'market': ' MX ', 'investor': 'Institutional'},
    {'strategy_id': 'momentum', 'investor': ['institutional']},
    {'strategy_id': 'momentum', 'market': ['mx']},
    {'strategy_id': 'momentum', 'market': {'k': 1}},
    {'strategy_id': 'momentum', 'market': 5, 'investor': 7},
    {'strategy_id': 'momentum', 'published': 'tal vez', 'long_short': 'SÍ', 'uses_leverage': 'off',
     'out_of_sample': 'verdadero'},
    {'strategy_id': 'momentum', 'turnover_monthly': '0x10', 'roundtrip_cost_bps': '1_000', 'horizon_years': '١٢'},
    {'strategy_id': 'llm_news', 'sharpe_annual': 7.5, 'years': 25, 'n_trials': 1000},        # t = 37.5
    {'strategy_id': 'llm_news', 'sharpe_annual': 7.41, 'years': 25, 'n_trials': 1000},       # t = 37.05
    {'strategy_id': 'llm_news', 'sharpe_annual': 7.39, 'years': 25, 'n_trials': 1000},       # t = 36.95
    {'strategy_id': 'momentum', 'sharpe_annual': 1.0, 'years': 5, 'n_trials': 1e16},
]


@unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
class TestParity(unittest.TestCase):
    def test_evaluations_match(self):
        js = _node("return A[0].map(c=>E.evaluateDecision(c,kb,{modules:[]}));", PARITY_CASES)
        for case, js_res in zip(PARITY_CASES, js):
            with self.subTest(case=case):
                _close(_strip_text(_ev(case)), _strip_text(js_res))

    def test_numeric_string_forms(self):
        vals = ['0x10', '1_000', '0b11', ' 7 ', '1e3', '.5', '١٢', '0,4', '-1,5e2', '1,000.5', 'inf', '\t3\n',
                '', '  ', 'e3', '+2', True, None]
        js = _node("const s=E.getStrategy(kb,'momentum');"
                   "return A[0].map(v=>E.resolveInputs({horizon_years:v},s).horizon_years);", vals)
        self.assertEqual([_num(v, 10.0) for v in vals], js)

    def test_bool_words(self):
        vals = ['1', 'true', 'si', 'sí', 'yes', 'y', 'verdadero', 'on', 't', 's', ' SÍ ',
                '0', 'false', 'no', 'n', 'falso', 'off', 'f', 'maybe', '  ', '2']
        js = _node("const s=E.getStrategy(kb,'value');"
                   "return A[0].map(v=>[E.resolveInputs({published:v},s).published,"
                   "E.resolveInputs({out_of_sample:v},s).out_of_sample]);", vals)
        self.assertEqual([[_bool(v, True), _bool(v, False)] for v in vals], js)

    def test_stats_guards_and_tail(self):
        js = _node(
            "const t=f=>{try{f();return null}catch(e){return e.message}};"
            "return {emz:[2,10,100,1000,1e6,1e15,1e16].map(E.expectedMaxSharpeZ),"
            "adj:t(()=>E.adjustPvalue(0.01,10,'bonferoni')),holm:E.adjustPvalue(0.01,10,'holm'),"
            "hs:t(()=>E.haircutSharpe(0.75,20,200,'fdr')),"
            "bodie:t(()=>E.bodieShortfallPutCost(-0.2,10)),bodie0:E.bodieShortfallPutCost(0,10),"
            "kelly:t(()=>E.kellyFraction(0.08,0.02,-0.2)),kelly0:E.kellyFraction(0.02,0.02,0),"
            "dsr:t(()=>E.deflatedSharpeRatio(1,10,5,252,-0.1)),"
            "pv:[36.9,37,37.05,38,40].map(E.tToPvalue)};")
        _close([stats.expected_max_sharpe_z(int(n)) for n in (2, 10, 100, 1000, 1e6, 1e15, 1e16)], js['emz'])
        self.assertIn('sidak', js['adj'])
        self.assertAlmostEqual(js['holm'], 0.1)
        self.assertTrue(js['hs'])
        self.assertIn('sigma debe ser >= 0', js['bodie'])
        self.assertIn('sigma debe ser >= 0', js['kelly'])
        self.assertEqual((js['bodie0'], js['kelly0']), (0, 0))
        self.assertTrue(js['dsr'])
        for t, p in zip((36.9, 37, 37.05, 38, 40), js['pv']):
            with self.subTest(t=t):
                py = stats.t_to_pvalue(t)
                self.assertEqual(py == 0.0, p == 0.0)
                self.assertTrue(math.isclose(py, p, rel_tol=1e-6, abs_tol=0.0) or py == p == 0.0)


if __name__ == '__main__':
    unittest.main()
