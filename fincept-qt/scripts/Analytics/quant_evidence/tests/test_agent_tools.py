"""
Tests for quant_evidence.agent_tools, the Python port of the chat-agent tools
in app/agente.html, and for the CLI commands built on it. Stdlib only:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .

The fixed expectations below were produced by the page's own JavaScript; the
parity test re-runs the page's tools under Node (skipped if Node is not
installed) and compares them with the port.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS = os.path.dirname(os.path.dirname(HERE))
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence import agent_tools  # noqa: E402
from quant_evidence.evaluator import evaluate_decision  # noqa: E402
from quant_evidence.knowledge_base import load_kb, load_repo_map  # noqa: E402

MOMENTUM_BACKTEST = {'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8, 'n_trials': 50,
                     'periods_per_year': 12}


class TestSearch(unittest.TestCase):
    def test_ranking_matches_page(self):
        r = agent_tools.search_strategies('momentum de acciones')
        # momentum hits the name twice (6); the rest hit "acciones" in the name (3), then by rating.
        self.assertEqual([x['id'] for x in r['results']],
                         ['momentum', 'lifecycle_glidepath', 'kelly_fractional', 'all_equity_lifetime',
                          'tsmom_futures', 'value_momentum_combo'])
        self.assertEqual(r['results'][0]['match_score'], 6)
        self.assertEqual(len(r['results']), agent_tools.SEARCH_LIMIT)

    def test_accents_and_short_words_are_ignored(self):
        a = agent_tools.search_strategies('México calendario', limit=3)
        b = agent_tools.search_strategies('MEXICO, calendario!', limit=3)
        self.assertEqual(a['results'], b['results'])
        self.assertEqual([x['id'] for x in a['results']],
                         ['ipc_calendar', 'cross_sectional_seasonality', 'mexico_factors'])
        self.assertEqual(agent_tools.normalize_text('Año ñandú'), 'ano nandu')
        self.assertEqual(agent_tools.search_strategies('de la el')['results'], [])

    def test_no_match_lists_ids(self):
        r = agent_tools.search_strategies('zzzz')
        self.assertEqual(r['results'], [])
        self.assertIn('buy_hold_global', r['note'])

    def test_filters_and_catalog_mode(self):
        r = agent_tools.search_strategies(family='timing', limit=50)
        self.assertTrue(r['results'])
        self.assertTrue(all(x['family'] == 'timing' for x in r['results']))
        priors = [x['prior_score'] for x in r['results']]
        self.assertEqual(priors, sorted(priors, reverse=True))
        r = agent_tools.search_strategies('momentum', category='momentum')
        self.assertTrue(all('momentum' in next(s for s in load_kb()['strategies'] if s['id'] == x['id'])
                            ['categories'] for x in r['results']))


class TestCompare(unittest.TestCase):
    def test_mexico_profile_matches_page(self):
        r = agent_tools.compare_strategies({'market': 'mx'}, 'momentum')
        self.assertEqual(r['profile'], {'horizon_years': 15.0, 'market': 'mx', 'investor': 'retail'})
        self.assertEqual([(x['id'], x['score']) for x in r['top'][:4]],
                         [('buy_hold_global', 88), ('periodic_contributions', 86), ('naive_1n', 81),
                          ('rebalancing', 81)])
        self.assertEqual(len(r['top']), 10)
        self.assertEqual(r['rank_of_strategy'], 36)
        self.assertEqual(r['total'], len(load_kb()['strategies']))

    def test_scores_come_from_evaluator_and_are_sorted(self):
        r = agent_tools.compare_strategies({'horizon_years': 3, 'investor': 'institutional'}, top=100)
        scores = [x['score'] for x in r['top']]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len(r['top']), r['total'])
        x = r['top'][5]
        ref = evaluate_decision({'strategy_id': x['id'], 'horizon_years': 3, 'market': 'global',
                                 'investor': 'institutional'})
        self.assertEqual(x['score'], int(ref['scores']['final']))
        self.assertEqual([x['rank'] for x in r['top']], list(range(1, r['total'] + 1)))

    def test_defaults_and_unknown_strategy(self):
        r = agent_tools.compare_strategies({'horizon_years': 0, 'market': ''}, 'nope', top=0)
        self.assertEqual(r['profile']['horizon_years'], 15.0)
        self.assertEqual(r['profile']['market'], 'global')
        self.assertEqual(len(r['top']), agent_tools.COMPARE_TOP)
        self.assertIsNone(r['rank_of_strategy'])
        self.assertIn('nope', r['note'])


class TestBreakeven(unittest.TestCase):
    def test_momentum_backtest_matches_page(self):
        r = agent_tools.breakeven_points(MOMENTUM_BACKTEST)
        self.assertTrue(r['applicable'])
        self.assertEqual(r['current_roundtrip_cost_bps'], 40)
        self.assertEqual(r['breakeven_roundtrip_cost_bps'], 23)
        self.assertEqual(r['current_turnover_monthly'], 0.6)
        self.assertEqual(r['breakeven_turnover_monthly_pct'], 35)

    def test_breakeven_is_the_first_loss(self):
        def net(**kw):
            return evaluate_decision(dict(MOMENTUM_BACKTEST, **kw))['net_monthly_bps']
        self.assertLessEqual(net(roundtrip_cost_bps=23), 0)
        self.assertGreater(net(roundtrip_cost_bps=22), 0)
        self.assertLessEqual(net(turnover_monthly=35 * 0.01), 0)
        self.assertGreater(net(turnover_monthly=30 * 0.01), 0)

    def test_other_cases_match_page(self):
        tsmom = agent_tools.breakeven_points({'strategy_id': 'tsmom_futures', 'sharpe_annual': 0.77, 'years': 40,
                                              'n_trials': 5, 'investor': 'institutional',
                                              'out_of_sample': True, 'published': False})
        self.assertEqual((tsmom['breakeven_roundtrip_cost_bps'], tsmom['breakeven_turnover_monthly_pct']), (143, 285))
        tom = agent_tools.breakeven_points({'strategy_id': 'turn_of_month', 'roundtrip_cost_bps': 5,
                                            'turnover_monthly': 1, 'published': False})
        self.assertEqual((tom['breakeven_roundtrip_cost_bps'], tom['breakeven_turnover_monthly_pct']), (36, None))
        # Long-only version of a long-short factor: no edge even without costs.
        mom = agent_tools.breakeven_points({'strategy_id': 'momentum'})
        self.assertEqual((mom['breakeven_roundtrip_cost_bps'], mom['breakeven_turnover_monthly_pct']), (0, 0))
        # Literature net figure: costs never remove it.
        bab = agent_tools.breakeven_points({'strategy_id': 'betting_against_beta'})
        self.assertEqual((bab['breakeven_roundtrip_cost_bps'], bab['breakeven_turnover_monthly_pct']), (None, None))
        self.assertIn('already deducts costs', bab['note'])

    def test_not_applicable_and_errors(self):
        r = agent_tools.breakeven_points({'strategy_id': 'buy_hold_global'})
        self.assertFalse(r['applicable'])
        self.assertIn('no measurable edge', r['note'])
        with self.assertRaises(ValueError):
            agent_tools.breakeven_points({'strategy_id': 'nope'})

    def test_decision_from_keeps_typed_inputs_only(self):
        d = agent_tools.decision_from({'strategy_id': 'cape_timing', 'published': 'false', 'years': '8',
                                       'turnover_monthly': '', 'var_trials_sr': 2, 'market': 'mx'})
        self.assertEqual(d, {'strategy_id': 'cape_timing', 'years': 8.0, 'market': 'mx'})

    def test_js_round_halves_up(self):
        self.assertEqual(agent_tools._js_round(2.5), 3)
        self.assertEqual(agent_tools._js_round(-0.5), 0)


class TestRepoModules(unittest.TestCase):
    def test_modules_and_gaps_follow_categories(self):
        r = agent_tools.repo_modules('momentum')
        cats = set(r['categories'])
        self.assertEqual(r['modules'][0]['path'],
                         'fincept-qt/scripts/Analytics/alternateInvestment/market_neutral.py')
        self.assertLessEqual(len(r['modules']), agent_tools.MODULE_LIMIT)
        by_path = {m['path']: m for m in load_repo_map()['modules']}
        for m in r['modules']:
            self.assertTrue(cats.intersection(by_path[m['path']]['categories']), m['path'])
            self.assertLessEqual(len(m['summary']), agent_tools.MODULE_SUMMARY_CHARS)
        for g in r['gaps']:
            self.assertIn(g['category'], cats)

    def test_gaps_for_backtesting(self):
        sid = next(s['id'] for s in load_kb()['strategies'] if 'backtest_overfitting' in s['categories'])
        r = agent_tools.repo_modules(sid)
        self.assertTrue(r['gaps'])
        self.assertTrue(all(len(g['text']) <= agent_tools.GAP_TEXT_CHARS for g in r['gaps']))

    def test_unknown_strategy(self):
        with self.assertRaises(ValueError):
            agent_tools.repo_modules('nope')


# Runs the page's inline scripts with a minimal DOM stub and calls its tools.
NODE_HARNESS = r"""
const vm = require('vm');
let raw = '';
process.stdin.on('data', c => raw += c).on('end', () => {
  const { scripts, calls } = JSON.parse(raw);
  const el = () => ({ innerHTML: '', textContent: '', hidden: false, disabled: false, value: '',
    scrollTop: 0, scrollHeight: 0, addEventListener() {}, querySelector() { return el(); },
    querySelectorAll() { return []; }, appendChild() {}, insertBefore() {}, remove() {} });
  globalThis.window = globalThis;
  globalThis.document = { getElementById: el, createElement: el };
  for (const s of scripts) vm.runInThisContext(s);
  const tools = {};
  window.__agentTools.forEach(t => { tools[t.name] = t; });
  process.stdout.write(JSON.stringify(calls.map(([name, input]) => tools[name].execute(input))));
});
"""


@unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
class TestAgentPageParity(unittest.TestCase):
    def test_port_matches_page_tools(self):
        from quant_evidence.app import build_app
        html = build_app.render_page([], scan_repo=False, standalone=False, ui='agente')
        scripts = re.findall(r'<script>([\s\S]*?)</script>', html)
        kb = load_kb()
        queries = ['momentum de acciones', 'México calendario', 'retiro', 'aprendizaje automático',
                   'valor value', 'apalancamiento kelly', 'zzzz']
        profiles = [{}, {'market': 'mx'}, {'market': 'us', 'investor': 'institutional', 'horizon_years': 3}]
        decisions = [{'strategy_id': s['id']} for s in kb['strategies']] + [
            MOMENTUM_BACKTEST,
            {'strategy_id': 'ml_cross_section', 'sharpe_annual': 2.45, 'years': 30, 'n_trials': 20,
             'investor': 'institutional', 'live_months': 24},
            {'strategy_id': 'llm_news', 'gross_alpha_monthly_bps': 400, 'market': 'mx'},
            {'strategy_id': 'turn_of_month', 'roundtrip_cost_bps': 5, 'turnover_monthly': 1, 'published': False}]
        module_ids = ['momentum', 'cape_timing', 'buy_hold_global', 'ml_cross_section']
        calls = ([['buscar_estrategias', {'texto': q}] for q in queries]
                 + [['comparar_alternativas', dict(p, strategy_id='momentum', limite=10)] for p in profiles]
                 + [['puntos_de_equilibrio', d] for d in decisions]
                 + [['modulos_del_repositorio', {'strategy_id': i}] for i in module_ids])
        proc = subprocess.run(['node', '-e', NODE_HARNESS], input=json.dumps({'scripts': scripts, 'calls': calls}),
                              capture_output=True, text=True, encoding='utf-8', check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[-800:])
        for (name, inp), js in zip(calls, json.loads(proc.stdout)):
            with self.subTest(tool=name, input=inp):
                if name == 'buscar_estrategias':
                    py = agent_tools.search_strategies(inp['texto'])
                    self.assertEqual([x['id'] for x in py['results']], [x['id'] for x in js.get('resultados', [])])
                elif name == 'comparar_alternativas':
                    py = agent_tools.compare_strategies(inp, 'momentum', 10)
                    self.assertEqual([(x['id'], x['score']) for x in py['top']],
                                     [(x['id'], x['puntaje']) for x in js['mejores']])
                    self.assertEqual(py['rank_of_strategy'], js['posicion_de_la_consultada'])
                    self.assertEqual(py['profile'], js['perfil'])
                elif name == 'puntos_de_equilibrio':
                    py = agent_tools.breakeven_points(inp)
                    self.assertEqual(py['applicable'], js['aplica'])
                    if js['aplica']:
                        self.assertEqual(
                            (py['current_roundtrip_cost_bps'], py['breakeven_roundtrip_cost_bps'],
                             py['current_turnover_monthly'], py['breakeven_turnover_monthly_pct']),
                            (js['costo_actual_pb'], js['costo_de_equilibrio_pb'], js['rotacion_actual'],
                             js['rotacion_de_equilibrio_pct']))
                else:
                    py = agent_tools.repo_modules(inp['strategy_id'])
                    self.assertEqual([(m['path'], m['summary']) for m in py['modules']],
                                     [(m['ruta'], m['resumen']) for m in js['modulos']])
                    self.assertEqual([(g['severity'], g['text'], g['covered_by']) for g in py['gaps']],
                                     [(g['severidad'], g['texto'], g['cubierta_por']) for g in js['brechas']])


class TestCliAgentCommands(unittest.TestCase):
    CLI = os.path.join(ANALYTICS, 'quant_evidence_cli.py')

    def _run(self, *args):
        out = subprocess.run([sys.executable, self.CLI, *args], capture_output=True, text=True, check=True,
                             encoding='utf-8')
        return json.loads(out.stdout)

    def test_new_commands(self):
        listing = self._run('list')
        for cmd in ('search', 'compare', 'breakeven', 'repo_modules'):
            self.assertIn(cmd, listing['data'])
            self.assertIn(cmd, listing['help'])
        r = self._run('search', json.dumps({'query': 'momentum', 'limit': 2}))
        self.assertEqual([x['id'] for x in r['data']['results']], ['tsmom_futures', 'value_momentum_combo'])
        self.assertEqual(len(r['data']['results']), 2)
        r = self._run('compare', json.dumps({'market': 'mx', 'strategy_id': 'momentum', 'top': 3}))
        self.assertEqual(r['data']['rank_of_strategy'], 36)
        self.assertEqual(len(r['data']['top']), 3)
        r = self._run('breakeven', json.dumps(MOMENTUM_BACKTEST))
        self.assertEqual(r['data']['breakeven_roundtrip_cost_bps'], 23)
        r = self._run('repo_modules', json.dumps({'strategy_id': 'momentum'}))
        self.assertTrue(r['data']['modules'])
        r = self._run('breakeven', json.dumps({'strategy_id': 'nope'}))
        self.assertFalse(r['success'])


if __name__ == '__main__':
    unittest.main()
