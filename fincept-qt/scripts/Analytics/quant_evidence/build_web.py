"""
Builds web/decision_lab.html: the template with the engine, the evidence
catalog and the repository map inlined, so the page is a single self-contained
file (publishable as an artifact or opened locally).

    python -m quant_evidence.build_web [output.html] [--no-scan]
"""

from __future__ import annotations

import json
import os
import sys

from .knowledge_base import PACKAGE_DIR, load_kb, load_repo_map

WEB_DIR = os.path.join(PACKAGE_DIR, 'web')
TEMPLATE = os.path.join(WEB_DIR, 'decision_lab.template.html')
ENGINE = os.path.join(WEB_DIR, 'engine.js')
DEFAULT_OUTPUT = os.path.join(WEB_DIR, 'decision_lab.html')


def _js_json(obj) -> str:
    # Escape "</" so embedded strings can never close the <script> element.
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def build(output: str | None = None, scan_repo: bool = True) -> str:
    output = output or DEFAULT_OUTPUT
    with open(TEMPLATE, encoding='utf-8') as f:
        html = f.read()
    with open(ENGINE, encoding='utf-8') as f:
        engine = f.read()
    repo = dict(load_repo_map())
    if scan_repo:
        from .repo_indexer import scan
        result = scan(top_per_category=0)
        repo['auto_index'] = {
            'files_scanned': result['files_scanned'],
            'categories': {k: {'file_count': v['file_count']} for k, v in result['categories'].items()},
        }
    for marker in ('/*__ENGINE__*/', '/*__KB__*/null', '/*__REPO__*/null'):
        if marker not in html:
            raise RuntimeError(f'Template marker missing: {marker}')
    html = (html.replace('/*__ENGINE__*/', engine)
                .replace('/*__KB__*/null', _js_json(load_kb()))
                .replace('/*__REPO__*/null', _js_json(repo)))
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html)
    return output


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    print(build(args[0] if args else None, scan_repo='--no-scan' not in sys.argv))
