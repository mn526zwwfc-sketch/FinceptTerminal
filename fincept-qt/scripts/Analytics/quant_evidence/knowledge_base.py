"""
Loads and organizes the structured evidence catalog (data/evidence_kb.json)
and the repository map (data/repo_map.json).
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PACKAGE_DIR, 'data')
KB_PATH = os.path.join(DATA_DIR, 'evidence_kb.json')
REPO_MAP_PATH = os.path.join(DATA_DIR, 'repo_map.json')

_cache: dict = {}


def _load_json(path: str):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def load_kb(path: str = KB_PATH) -> dict:
    if path not in _cache:
        _cache[path] = _load_json(path)
    return _cache[path]


def load_repo_map(path: str = REPO_MAP_PATH) -> dict:
    if not os.path.exists(path):
        return {'modules': [], 'gaps': []}
    if path not in _cache:
        _cache[path] = _load_json(path)
    return _cache[path]


def get_strategy(strategy_id: str | None, kb: dict | None = None) -> dict | None:
    kb = kb or load_kb()
    for s in kb['strategies']:
        if s['id'] == strategy_id:
            return s
    return None


def list_strategies(kb: dict | None = None, family: str | None = None,
                    category: str | None = None) -> list[dict]:
    kb = kb or load_kb()
    out = []
    for s in kb['strategies']:
        if family and s['family'] != family:
            continue
        if category and category not in s['categories']:
            continue
        out.append({'id': s['id'], 'name': s['name'], 'family': s['family'],
                    'prior': s['prior']['score'], 'survives': s['survives']})
    return sorted(out, key=lambda s: -s['prior'])


def organize(kb: dict | None = None, repo_map: dict | None = None) -> dict:
    """Group strategies and repository modules under each evidence category.

    Returns an ordered mapping category_key -> {name, family, strategies,
    modules, best_prior}, plus the repository gaps and uncategorized modules.
    """
    kb = kb or load_kb()
    repo_map = repo_map if repo_map is not None else load_repo_map()
    groups: 'OrderedDict[str, dict]' = OrderedDict()
    for c in kb['categories']:
        groups[c['key']] = {'name': c['name'], 'family': c['family'],
                            'strategies': [], 'modules': []}
    for s in kb['strategies']:
        for c in s['categories']:
            groups[c]['strategies'].append({'id': s['id'], 'name': s['name'],
                                            'prior': s['prior']['score']})
    uncategorized = []
    for m in repo_map.get('modules', []):
        hit = False
        for c in m.get('categories', []):
            if c in groups:
                groups[c]['modules'].append({'path': m['path'], 'kind': m.get('kind', ''),
                                             'summary': m.get('summary_es') or m.get('summary', '')})
                hit = True
        if not hit:
            uncategorized.append(m['path'])
    for g in groups.values():
        g['strategies'].sort(key=lambda s: -s['prior'])
        g['modules'].sort(key=lambda m: m['path'])
        g['best_prior'] = max((s['prior'] for s in g['strategies']), default=None)
    return {'categories': groups, 'gaps': repo_map.get('gaps', []),
            'uncategorized_modules': uncategorized}
