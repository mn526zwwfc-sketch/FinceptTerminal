"""
Quant Evidence CLI - academic evidence on quant strategies + decision evaluator.

Organizes the literature review "La academia quant desinfla sus propias
estrategias" as structured data, maps it onto the
FinceptTerminal modules that implement each topic, and scores how well a
proposed investment decision is supported once multiple testing, decay,
microcaps and trading costs are accounted for.

Usage:
    python quant_evidence_cli.py <command> [params_json]

Commands:
    list                 - List available commands
    strategies           - Strategy catalog, optional {"family": ..., "category": ...}
    strategy             - One strategy with its evidence, {"id": "momentum"}
    categories           - Evidence categories with strategies and repo modules
    evaluate             - Score a decision, e.g. {"strategy_id": "momentum",
                           "sharpe_annual": 1.2, "years": 8, "n_trials": 50}
    deflated_sharpe      - {"sharpe_annual", "n_trials", "years", "periods_per_year",
                           "var_trials_sr", "skew", "kurtosis"}
    haircut_sharpe       - {"sharpe_annual", "years", "n_tests", "method"}
    min_backtest_length  - {"n_trials", "target_sharpe"} or {"years", "target_sharpe"}
    cost_drag            - {"turnover_monthly", "roundtrip_cost_bps", "long_short",
                           "gross_monthly_bps"}
    horizon_risk         - {"sigma_annual", "years", "mu_real_annual"}
    kelly                - {"mu", "r", "sigma", "gamma", "kelly_multiple"}
    cascade              - Chen-Velikov cascade and decay constants
    repo_map             - Curated map of repository modules by category
    repo_scan            - Live keyword scan of the repository tree
    export_web           - Write web/decision_lab.html with the data embedded,
                           {"output": "path.html"} optional
"""

import json
import math
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from quant_evidence import stats  # noqa: E402
from quant_evidence.evaluator import _bool, evaluate_decision  # noqa: E402
from quant_evidence.knowledge_base import (  # noqa: E402
    get_strategy, list_strategies, load_kb, load_repo_map, organize)


def _sanitize(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _f(params, key, default=None):
    v = params.get(key, default)
    return default if v is None else float(v)


def cmd_strategies(params):
    return list_strategies(family=params.get('family'), category=params.get('category'))


def cmd_strategy(params):
    s = get_strategy(params.get('id') or params.get('strategy_id'))
    if s is None:
        raise ValueError(f"Estrategia desconocida: {params.get('id')!r}")
    return s


def cmd_categories(params):
    org = organize()
    return {'categories': org['categories'], 'gaps': org['gaps']}


def cmd_deflated_sharpe(params):
    return stats.deflated_sharpe_ratio(
        _f(params, 'sharpe_annual'), int(params.get('n_trials', 1)), _f(params, 'years'),
        int(params.get('periods_per_year', 252)),
        _f(params, 'var_trials_sr'), _f(params, 'skew', 0.0), _f(params, 'kurtosis', 3.0))


def cmd_haircut_sharpe(params):
    return stats.haircut_sharpe(_f(params, 'sharpe_annual'), _f(params, 'years'),
                                int(params.get('n_tests', params.get('n_trials', 1))),
                                params.get('method', 'bonferroni'))


def cmd_min_backtest_length(params):
    target = _f(params, 'target_sharpe', 1.0)
    out = {'target_sharpe': target}
    if 'n_trials' in params:
        out['n_trials'] = int(params['n_trials'])
        out['min_years'] = stats.min_backtest_length(out['n_trials'], target)
    if 'years' in params:
        out['years'] = _f(params, 'years')
        out['max_trials'] = stats.max_trials_for_length(out['years'], target)
    return out


def cmd_cost_drag(params):
    turnover = _f(params, 'turnover_monthly', 0.0)
    cost = _f(params, 'roundtrip_cost_bps', 40.0)
    ls = _bool(params.get('long_short'), False)
    out = {'monthly_cost_bps': stats.monthly_cost_bps(turnover, cost, ls),
           'survives_turnover_rule': turnover <= 0.5}
    if params.get('gross_monthly_bps') is not None:
        gross = _f(params, 'gross_monthly_bps')
        out['net_monthly_bps'] = gross - out['monthly_cost_bps']
        out['breakeven_roundtrip_cost_bps'] = stats.breakeven_roundtrip_cost_bps(gross, turnover, ls)
    return out


def cmd_horizon_risk(params):
    sigma = _f(params, 'sigma_annual', 0.2)
    years = _f(params, 'years', 30.0)
    out = {'bodie_put_cost': stats.bodie_shortfall_put_cost(sigma, years),
           'empirical_39_countries_30y_real_loss': 0.12}
    if params.get('mu_real_annual') is not None:
        out['model_prob_real_loss'] = stats.prob_real_loss_lognormal(
            _f(params, 'mu_real_annual'), sigma, years)
    return out


def cmd_kelly(params):
    mu, r, sigma = _f(params, 'mu'), _f(params, 'r', 0.0), _f(params, 'sigma')
    gamma = _f(params, 'gamma', 1.0)
    f_star = stats.kelly_fraction(mu, r, sigma, 1.0)
    x = _f(params, 'kelly_multiple', 0.5)
    return {'kelly_fraction': f_star,
            'merton_fraction': stats.kelly_fraction(mu, r, sigma, gamma),
            'kelly_multiple': x,
            'growth_share_kept': stats.kelly_growth_share(x),
            'growth_rate': stats.growth_rate(x * f_star, mu, r, sigma)}


def cmd_cascade(params):
    kb = load_kb()
    return {'cascade': kb['cascade'], 'decay': kb['decay'], 'habits': kb['habits']}


def cmd_repo_map(params):
    return load_repo_map()


def cmd_repo_scan(params):
    from quant_evidence.repo_indexer import scan
    return scan(min_hits=int(params.get('min_hits', 3)),
                top_per_category=int(params.get('top', 15)))


def cmd_export_web(params):
    from quant_evidence.build_web import build
    path = build(params.get('output'))
    return {'output': path}


COMMANDS = {
    'strategies': cmd_strategies,
    'strategy': cmd_strategy,
    'categories': cmd_categories,
    'evaluate': evaluate_decision,
    'deflated_sharpe': cmd_deflated_sharpe,
    'haircut_sharpe': cmd_haircut_sharpe,
    'min_backtest_length': cmd_min_backtest_length,
    'cost_drag': cmd_cost_drag,
    'horizon_risk': cmd_horizon_risk,
    'kelly': cmd_kelly,
    'cascade': cmd_cascade,
    'repo_map': cmd_repo_map,
    'repo_scan': cmd_repo_scan,
    'export_web': cmd_export_web,
}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'success': False, 'error': 'No command provided',
                          'usage': 'python quant_evidence_cli.py <command> [params_json]'}))
        return
    command = sys.argv[1].lower()
    params = {}
    if len(sys.argv) > 2:
        arg = sys.argv[2]
        try:
            if os.path.isfile(arg):
                with open(arg, encoding='utf-8') as f:
                    params = json.load(f)
            else:
                params = json.loads(arg)
        except (ValueError, OSError) as e:  # JSONDecodeError and UnicodeDecodeError
            print(json.dumps({'success': False, 'error': f'Invalid JSON parameters: {e}'}))
            return
    if command == 'list':
        print(json.dumps({'success': True, 'data': sorted(COMMANDS)}))
        return
    if command not in COMMANDS:
        print(json.dumps({'success': False, 'error': f'Unknown command: {command}',
                          'available_commands': sorted(COMMANDS)}))
        return
    try:
        data = COMMANDS[command](params)
        print(json.dumps({'success': True, 'data': _sanitize(data)}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001 - surfaced as JSON to the caller
        print(json.dumps({'success': False, 'error': str(e), 'command': command}, ensure_ascii=False))


if __name__ == '__main__':
    main()
