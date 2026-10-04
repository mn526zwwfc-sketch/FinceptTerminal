"""
Repository indexer: classifies FinceptTerminal source files into the evidence
categories of data/evidence_kb.json.

Two layers:
  * data/repo_map.json — curated map (file-level summaries, verified by
    reading each file). This is what the evaluator and the web page use.
  * scan() — a live keyword scan of the tree, so the organization stays
    current as the repository changes. It only reports where a category's
    vocabulary appears; it does not claim what a file does.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

from .knowledge_base import PACKAGE_DIR

REPO_ROOT = os.path.abspath(os.path.join(PACKAGE_DIR, '..', '..', '..', '..'))
SCAN_DIRS = ('fincept-qt/scripts', 'fincept-qt/src')
SCAN_EXTS = ('.py', '.cpp', '.h')
SKIP_DIRS = {'__pycache__', '.git', 'node_modules', 'third_party', '.venv', 'venv', 'build', 'i18n',
             'translations', 'quant_evidence'}
MAX_BYTES = 80_000

# Vocabulary per category. Patterns are matched case-insensitively against the
# file path and its first MAX_BYTES of content.
KEYWORD_RULES: dict[str, list[str]] = {
    'factor_models': [r'fama[_\s-]?french', r'\bsmb\b', r'\bhml\b', r'carhart', r'factor[_\s]?model',
                      r'q[_-]?factor', r'factor[_\s]?exposure', r'factor[_\s]?loading'],
    'quality_profitability': [r'gross[_\s]?profitab', r'quality[_\s]?minus[_\s]?junk', r'\bqmj\b',
                              r'piotroski', r'quality[_\s]?score', r'profitability[_\s]?factor'],
    'value': [r'value[_\s]?factor', r'book[_\s]?to[_\s]?market', r'value[_\s]?premium', r'\bp/b\b',
              r'price[_\s]?to[_\s]?book', r'value[_\s]?investing'],
    'momentum': [r'momentum[_\s]?(factor|strategy|signal|score)', r'\bwml\b', r'12[_-]?1[_\s]?month',
                 r'cross[_\s-]?sectional[_\s]?momentum', r'jegadeesh'],
    'low_beta_bab': [r'betting[_\s]?against[_\s]?beta', r'\bbab\b', r'low[_\s]?beta', r'low[_\s]?vol(atility)?[_\s]?(anomaly|factor)'],
    'anomaly_zoo': [r'alpha158', r'alpha360', r'alpha101', r'formulaic[_\s]?alpha', r'anomal(y|ies)',
                    r'factor[_\s]?zoo', r'alpha[_\s]?factor'],
    'ml_cross_section': [r'lightgbm', r'xgboost', r'catboost', r'random[_\s]?forest', r'\blstm\b',
                         r'transformer', r'neural[_\s]?net', r'gradient[_\s]?boost', r'qlib'],
    'llm_text_signals': [r'\bllm\b', r'gpt', r'news[_\s]?sentiment', r'finbert', r'text[_\s]?signal',
                         r'language[_\s]?model', r'sentiment[_\s]?score'],
    'backtest_overfitting': [r'backtest', r'walk[_\s-]?forward', r'cross[_\s-]?validation', r'deflated[_\s]?sharpe',
                             r'probability[_\s]?of[_\s]?backtest[_\s]?overfitting', r'purged', r'combinatorial',
                             r'reality[_\s]?check', r'data[_\s-]?snooping', r'bonferroni', r'out[_\s-]?of[_\s-]?sample'],
    'technical_rules': [r'moving[_\s]?average', r'\bsma\b', r'\bema\b', r'\brsi\b', r'\bmacd\b',
                        r'bollinger', r'breakout', r'donchian', r'candlestick', r'chart[_\s]?pattern'],
    'portfolio_construction': [r'markowitz', r'mean[_\s-]?variance', r'efficient[_\s]?frontier', r'risk[_\s]?parity',
                               r'black[_\s-]?litterman', r'ledoit', r'shrinkage', r'hierarchical[_\s]?risk',
                               r'\bhrp\b', r'min(imum)?[_\s]?variance', r'equal[_\s]?weight', r'rebalanc'],
    'position_sizing_kelly': [r'kelly', r'position[_\s]?siz', r'bet[_\s]?siz', r'leverage'],
    'long_horizon_lifecycle': [r'retirement', r'lifecycle', r'life[_\s]?cycle', r'glide[_\s]?path',
                               r'monte[_\s]?carlo', r'safe[_\s]?withdrawal', r'target[_\s]?date', r'dollar[_\s]?cost'],
    'trading_costs_turnover': [r'transaction[_\s]?cost', r'slippage', r'commission', r'turnover',
                               r'bid[_\s-]?ask', r'market[_\s]?impact', r'spread[_\s]?cost'],
    'market_timing_predictors': [r'\bcape\b', r'shiller', r'dividend[_\s]?yield', r'equity[_\s]?premium',
                                 r'earnings[_\s]?yield', r'goyal', r'market[_\s]?timing'],
    'trend_following_tsmom': [r'trend[_\s]?follow', r'time[_\s-]?series[_\s]?momentum', r'\btsmom\b',
                              r'10[_\s-]?month', r'200[_\s-]?day'],
    'volatility_managed': [r'garch', r'egarch', r'volatility[_\s]?target', r'vol[_\s]?target',
                           r'realized[_\s]?vol', r'volatility[_\s]?forecast', r'arch[_\s]?model'],
    'regimes_business_cycle': [r'regime', r'markov[_\s]?switch', r'hidden[_\s]?markov', r'\bhmm\b',
                               r'yield[_\s]?curve', r'recession', r'business[_\s]?cycle', r'term[_\s]?spread'],
    'sentiment_options_short': [r'\bvix\b', r'implied[_\s]?vol', r'variance[_\s]?risk[_\s]?premium',
                                r'short[_\s]?interest', r'put[_\s/-]?call', r'fear[_\s]?(and|&)[_\s]?greed',
                                r'investor[_\s]?sentiment'],
    'calendar_effects': [r'day[_\s]?of[_\s]?(the[_\s])?week', r'january[_\s]?effect', r'seasonal',
                         r'turn[_\s]?of[_\s]?(the[_\s])?month', r'\bfomc\b', r'halloween', r'sell[_\s]?in[_\s]?may',
                         r'holiday[_\s]?effect'],
    'active_funds_retail': [r'mutual[_\s]?fund', r'fund[_\s]?performance', r'\bspiva\b', r'expense[_\s]?ratio',
                            r'active[_\s]?management', r'fund[_\s]?flow'],
    'mexico_latam': [r'banxico', r'\bbmv\b', r'\bipc\b', r'mexic', r'inegi', r'latam', r'latin[_\s]?america',
                     r'\bmxn\b', r'cetes'],
}



def _literal(pattern: str) -> str:
    """Longest plain run of letters/digits that every match must contain,
    used as a cheap substring prefilter before running the regex."""
    bare = re.sub(r'\\[a-zA-Z]', ' ', pattern)
    bare = re.sub(r'\[[^\]]*\]\??', ' ', bare)
    bare = re.sub(r'\([^)]*\)\?|\([^)]*\|[^)]*\)', ' ', bare)
    runs = re.findall(r'[a-z0-9]+', bare)
    return max(runs, key=len) if runs else ''


_COMPILED = {k: [(_literal(p), re.compile(p)) for p in v] for k, v in KEYWORD_RULES.items()}


def _kind(path: str) -> str:
    if path.endswith('.py'):
        return 'python_cli' if path.endswith('_cli.py') else 'python_module'
    if '/screens/' in path or '/ui/' in path:
        return 'cpp_screen'
    return 'cpp_service'


def classify_text(path: str, text: str, min_hits: int = 2) -> dict[str, int]:
    """Return {category: hit_count} for categories whose vocabulary occurs at
    least `min_hits` times in the path + text, or that match the path itself."""
    out = {}
    low_path = path.lower()
    hay = low_path + '\n' + text.lower()
    for cat, pats in _COMPILED.items():
        hits = sum(len(rx.findall(hay)) for lit, rx in pats if lit in hay)
        path_hit = any(lit in low_path and rx.search(low_path) for lit, rx in pats)
        if hits >= min_hits or path_hit:
            out[cat] = hits
    return out


def iter_source_files(root: str = REPO_ROOT):
    for base in SCAN_DIRS:
        top = os.path.join(root, base)
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]
            for fn in filenames:
                if fn.endswith(SCAN_EXTS):
                    yield os.path.join(dirpath, fn)


def scan(root: str = REPO_ROOT, min_hits: int = 3, top_per_category: int = 15) -> dict:
    """Keyword scan of the repository.

    Returns per-category file counts and the files with the most hits, plus
    totals. Paths are repo-relative.
    """
    per_cat: dict[str, list[tuple[int, str]]] = defaultdict(list)
    n_files = 0
    for full in iter_source_files(root):
        n_files += 1
        rel = os.path.relpath(full, root).replace(os.sep, '/')
        try:
            with open(full, encoding='utf-8', errors='ignore') as f:
                text = f.read(MAX_BYTES)
        except OSError:
            continue
        for cat, hits in classify_text(rel, text, min_hits).items():
            per_cat[cat].append((hits, rel))
    categories = {}
    for cat in KEYWORD_RULES:
        files = sorted(per_cat.get(cat, []), key=lambda x: (-x[0], x[1]))
        categories[cat] = {
            'file_count': len(files),
            'top_files': [{'path': p, 'hits': h, 'kind': _kind(p)} for h, p in files[:top_per_category]],
        }
    empty = [c for c, v in categories.items() if v['file_count'] == 0]
    return {'root': root, 'files_scanned': n_files, 'categories': categories,
            'categories_without_files': empty}
