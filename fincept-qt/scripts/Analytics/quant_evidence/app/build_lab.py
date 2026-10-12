"""
Builds Laboratorio Fincept: a single self-contained page (app/laboratorio.html)
with the JavaScript engine (web/engine.js), the series analytics
(web/series.js), the evidence base and the recent-research list inlined.

    cd fincept-qt/scripts/Analytics
    python -m quant_evidence.app.build_lab [output.html]

The page is meant to be published as a claude.ai artifact: there it reads
prices from its Yahoo database, signals through the viewer's Quiver Quant
connector, and drafts reports with the viewer's Claude account. Opened
anywhere else it still runs the audit on the simulated example or on pasted
data.
"""

import json
import os
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.dirname(APP_DIR)
TEMPLATE = os.path.join(APP_DIR, 'laboratorio.html')
ENGINE = os.path.join(PACKAGE_DIR, 'web', 'engine.js')
SERIES = os.path.join(PACKAGE_DIR, 'web', 'series.js')
KB = os.path.join(PACKAGE_DIR, 'data', 'evidence_kb.json')
PAPERS = os.path.join(PACKAGE_DIR, 'data', 'recent_papers.json')
MARKERS = ('/*__ENGINE__*/', '/*__SERIES__*/', '/*__KB__*/null', '/*__PAPERS__*/null')
# Strategies the Laboratorio does not offer (they stay in the shared knowledge base).
EXCLUDED_STRATEGIES = {'markowitz_sample'}


def _read(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def _inline_json(obj) -> str:
    # Safe inside <script>: no '</' sequence and no raw U+2028/2029.
    return (json.dumps(obj, ensure_ascii=False, separators=(',', ':'))
            .replace('</', '<\\/').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


def _inline_js(src: str) -> str:
    return src.replace('</script', '<\\/script')


def _without_excluded(kb: dict, papers: dict | None):
    kb = dict(kb, strategies=[s for s in kb['strategies'] if s['id'] not in EXCLUDED_STRATEGIES])
    if papers:
        papers = dict(papers, papers=[
            dict(p, related_strategy_ids=[i for i in p.get('related_strategy_ids', []) if i not in EXCLUDED_STRATEGIES])
            for p in papers.get('papers', [])])
    return kb, papers


def build(output: str | None = None) -> str:
    html = _read(TEMPLATE)
    for marker in MARKERS:
        if html.count(marker) != 1:
            raise ValueError(f'Template marker {marker!r} must appear exactly once.')
    papers = json.loads(_read(PAPERS)) if os.path.isfile(PAPERS) else None
    kb, papers = _without_excluded(json.loads(_read(KB)), papers)
    html = (html.replace('/*__ENGINE__*/', _inline_js(_read(ENGINE)))
            .replace('/*__SERIES__*/', _inline_js(_read(SERIES)))
            .replace('/*__KB__*/null', _inline_json(kb))
            .replace('/*__PAPERS__*/null', _inline_json(papers) if papers else 'null'))
    out = output or os.path.join(APP_DIR, 'dist', 'laboratorio.html')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(html)
    return out


if __name__ == '__main__':
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
