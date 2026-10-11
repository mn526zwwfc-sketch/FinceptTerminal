"""
Agent tools: the chat-agent helpers of app/agente.html, ported to Python.

The JavaScript agent (app/agente.html) offers search, comparison, break-even
and repository-module tools that used to exist only in the browser. This
module reproduces them on top of the Python engine (evaluator.py), with the
same ranking, defaults and break-even search, so the CLI and the MCP server
give the same answers as the page. tests/test_agent_tools.py runs the page's
tools under Node (when installed) and checks that both agree.

Everything here is pure: it reads the knowledge base and the repository map
and returns plain dicts. The figures are educational, not investment advice.
"""

from __future__ import annotations

import math
import re
import unicodedata

from .evaluator import _num, evaluate_decision
from .knowledge_base import get_strategy, load_kb, load_repo_map

SEARCH_LIMIT = 6
COMPARE_TOP = 10
COMPARE_DEFAULTS = {'horizon_years': 15.0, 'market': 'global', 'investor': 'retail'}

# decisionFrom() in app/agente.html: the inputs an agent may pass through.
DECISION_NUMBERS = ('horizon_years', 'sharpe_annual', 'years', 'n_trials', 'periods_per_year', 'skew',
                    'kurtosis', 'turnover_monthly', 'roundtrip_cost_bps', 'microcap_share',
                    'volatility_annual', 'gross_alpha_monthly_bps', 'live_months', 'kelly_multiple')
DECISION_STRINGS = ('market', 'investor')
DECISION_BOOLEANS = ('published', 'out_of_sample', 'long_short', 'uses_leverage')

# firstLoss() search ranges: (low, high, step, scale to the evaluator's unit).
COST_SEARCH = (0, 300, 1, 1.0)          # round-trip cost in bps, 1 bp resolution
TURNOVER_SEARCH = (0, 300, 5, 0.01)     # monthly turnover in %, 5 point resolution

LITERATURE_NET_STAGE = 'Neto según la literatura'   # first cascade stage when costs are already netted

MODULE_LIMIT = 12
MODULE_SUMMARY_CHARS = 220
GAP_TEXT_CHARS = 260

_NON_ALNUM = re.compile(r'[^a-z0-9 ]+')


def normalize_text(text) -> str:
    """Lowercase, strip accents and keep [a-z0-9 ] (norm() in the page)."""
    s = unicodedata.normalize('NFD', str(text or '').lower())
    s = ''.join(ch for ch in s if not '̀' <= ch <= 'ͯ')
    return _NON_ALNUM.sub(' ', s)


def _tokens(query) -> list[str]:
    return [t for t in normalize_text(query).split() if len(t) > 2]


def _match_score(tokens: list[str], strategy: dict) -> int:
    """A word in the id or name counts three times as much as one elsewhere."""
    head = normalize_text(strategy['id'].replace('_', ' ') + ' ' + strategy['name'])
    rest = normalize_text(strategy['claim'] + ' ' + ' '.join(strategy['categories']).replace('_', ' ')
                          + ' ' + strategy['family'])
    score = 0
    for t in tokens:
        stem = t[:-2] if len(t) > 5 else t
        if stem in head:
            score += 3
        elif stem in rest:
            score += 1
    return score


def _positive_int(value, default: int) -> int:
    v = _num(value)
    return max(int(v), 1) if v else default


def search_strategies(query: str | None = None, family: str | None = None, category: str | None = None,
                      limit: int = SEARCH_LIMIT, kb: dict | None = None) -> dict:
    """Keyword search over the 44 strategies (buscar_estrategias).

    With a query, strategies are ranked by match score, then by evidence
    rating, exactly like the page. Without one, the (optionally filtered)
    catalog is returned by evidence rating.
    """
    kb = kb or load_kb()
    limit = _positive_int(limit, SEARCH_LIMIT)
    pool = [s for s in kb['strategies']
            if (not family or s['family'] == family) and (not category or category in s['categories'])]
    has_query = query is not None and str(query).strip() != ''
    if has_query:
        tokens = _tokens(query)
        scored = [(s, _match_score(tokens, s)) for s in pool]
        ranked = sorted(((s, sc) for s, sc in scored if sc > 0),
                        key=lambda x: (-x[1], -x[0]['prior']['score']))
    else:
        ranked = sorted(((s, None) for s in pool), key=lambda x: -x[0]['prior']['score'])
    results = [{'id': s['id'], 'name': s['name'], 'family': s['family'],
                'prior_score': s['prior']['score'], 'match_score': sc} for s, sc in ranked[:limit]]
    out = {'query': query, 'family': family, 'category': category,
           'results': results, 'total_matches': len(ranked)}
    if not results:
        out['note'] = 'No matches. Valid ids: ' + ', '.join(s['id'] for s in kb['strategies'])
    return out


def decision_from(raw: dict, kb: dict | None = None) -> dict:
    """Keep only well-typed decision inputs (decisionFrom() in the page)."""
    if not isinstance(raw, dict):
        raise TypeError('The decision must be a JSON object.')
    sid = str(raw.get('strategy_id') or '')
    if get_strategy(sid, kb) is None:
        raise ValueError(f'Unknown strategy_id {sid!r}: use search_strategies to get a valid id.')
    d = {'strategy_id': sid}
    for k in DECISION_NUMBERS:
        v = _num(raw.get(k))
        if v is not None:
            d[k] = v
    for k in DECISION_STRINGS:
        if raw.get(k):
            d[k] = str(raw[k])
    for k in DECISION_BOOLEANS:
        if isinstance(raw.get(k), bool):
            d[k] = raw[k]
    return d


def _js_round(x: float) -> int:
    """Math.round: halves round up, unlike Python's round()."""
    return math.floor(x + 0.5)


def first_loss(decision: dict, key: str, lo: int, hi: int, step: int, scale: float,
               kb: dict | None = None) -> int | None:
    """Smallest value of `key` (in search units) at which the net edge is <= 0.

    Returns `lo` when there is no edge even at the low end and None when the
    edge survives the whole range. Bisection on a `step` grid (firstLoss()).
    """
    def gone(v: int) -> bool:
        r = evaluate_decision(dict(decision, **{key: v * scale}), kb, {})
        return r['net_monthly_bps'] is not None and r['net_monthly_bps'] <= 0

    if gone(lo):
        return lo
    if not gone(hi):
        return None
    a, b = lo, hi
    while b - a > step:
        m = a + _js_round((b - a) / 2 / step) * step
        if m <= a:
            m = a + step
        if m >= b:
            break
        if gone(m):
            b = m
        else:
            a = m
    return b


def compare_strategies(profile: dict | None = None, strategy_id: str | None = None,
                       top: int = COMPARE_TOP, kb: dict | None = None) -> dict:
    """Evaluate every strategy with one profile and rank them (comparar_alternativas).

    The profile is horizon_years (default 15), market (global) and investor
    (retail), with no backtest. Ranking is by the floored final score; ties
    keep the knowledge-base order, as in the page.
    """
    kb = kb or load_kb()
    profile = profile or {}
    prof = {'horizon_years': _num(profile.get('horizon_years')) or COMPARE_DEFAULTS['horizon_years'],
            'market': str(profile.get('market') or COMPARE_DEFAULTS['market']),
            'investor': str(profile.get('investor') or COMPARE_DEFAULTS['investor'])}
    ranked = []
    for s in kb['strategies']:
        r = evaluate_decision(dict(prof, strategy_id=s['id']), kb, {})
        ranked.append({'id': s['id'], 'name': s['name'], 'family': s['family'],
                       'score': math.floor(r['scores']['final']), 'verdict': r['verdict']['label'],
                       'verdict_code': r['verdict']['code'], 'net_monthly_bps': r['net_monthly_bps']})
    ranked.sort(key=lambda x: -x['score'])
    for i, x in enumerate(ranked, 1):
        x['rank'] = i
    n = min(_positive_int(top, COMPARE_TOP), len(ranked))
    out = {'profile': prof, 'top': ranked[:n], 'total': len(ranked),
           'strategy_id': strategy_id, 'rank_of_strategy': None}
    if strategy_id:
        hit = next((x for x in ranked if x['id'] == str(strategy_id)), None)
        if hit is None:
            out['note'] = f'Unknown strategy_id {strategy_id!r}: use search_strategies to get a valid id.'
        else:
            out['rank_of_strategy'] = hit['rank']
            out['strategy'] = hit
    return out


def breakeven_points(decision: dict, kb: dict | None = None) -> dict:
    """Round-trip cost and monthly turnover at which the net edge vanishes (puntos_de_equilibrio)."""
    d = decision_from(decision, kb)
    r = evaluate_decision(d, kb, {})
    if r['net_monthly_bps'] is None:
        return {'applicable': False, 'strategy_id': d['strategy_id'],
                'note': 'This strategy has no measurable edge in bps; it is judged on evidence and context.'}
    note = ('null = the edge survives the whole tested range (0-300 bps, 0-300% monthly turnover); '
            '0 = there is no edge even without costs. Cost is resolved to 1 bp and turnover to 5 points.')
    if r['cascade'] and r['cascade'][0]['stage'] == LITERATURE_NET_STAGE:
        note += (' The edge here is the literature net figure, which already deducts costs, so your '
                 'cost and turnover do not move it.')
    return {
        'applicable': True,
        'strategy_id': d['strategy_id'],
        'net_monthly_bps': r['net_monthly_bps'],
        'current_roundtrip_cost_bps': r['inputs']['roundtrip_cost_bps'],
        'breakeven_roundtrip_cost_bps': first_loss(d, 'roundtrip_cost_bps', *COST_SEARCH, kb=kb),
        'current_turnover_monthly': r['inputs']['turnover_monthly'],
        'breakeven_turnover_monthly_pct': first_loss(d, 'turnover_monthly', *TURNOVER_SEARCH, kb=kb),
        'search_range': {'roundtrip_cost_bps': [COST_SEARCH[0], COST_SEARCH[1], COST_SEARCH[2]],
                         'turnover_monthly_pct': [TURNOVER_SEARCH[0], TURNOVER_SEARCH[1], TURNOVER_SEARCH[2]]},
        'note': note,
    }


def repo_modules(strategy_id: str, kb: dict | None = None, repo_map: dict | None = None) -> dict:
    """FinceptTerminal modules and known gaps for a strategy's evidence categories."""
    s = get_strategy(str(strategy_id or ''), kb)
    if s is None:
        raise ValueError(f'Unknown strategy_id {strategy_id!r}: use search_strategies to get a valid id.')
    repo_map = repo_map if repo_map is not None else load_repo_map()
    cats = s['categories']
    mods = [m for m in repo_map.get('modules', [])
            if any(c in cats for c in m.get('categories') or [])][:MODULE_LIMIT]
    gaps = [g for g in repo_map.get('gaps', []) if isinstance(g, dict) and g.get('category') in cats]
    return {
        'strategy_id': s['id'], 'name': s['name'], 'categories': cats,
        'modules': [{'path': m['path'],
                     'summary': (m.get('summary_es') or m.get('summary') or '')[:MODULE_SUMMARY_CHARS]}
                    for m in mods],
        'gaps': [{'category': g['category'], 'severity': g.get('severity'),
                  'text': g.get('text', '')[:GAP_TEXT_CHARS], 'covered_by': g.get('covered_by') or None}
                 for g in gaps],
    }
