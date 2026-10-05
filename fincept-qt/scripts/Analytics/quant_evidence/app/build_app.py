"""
Builds Fincept Quant Studio, a single-page app over the quant_evidence engine
and the FinceptTerminal source code. Two interfaces share the same engine and
data: a market-terminal UI (terminal.html, default) and a product-page style
interface (template.html).

Output directory layout:

    index.html        the app (engine, evidence catalog, repo map and a code
                      index inlined)
    code/<id>.txt     source of every file in the code index, fetched on demand

    python -m quant_evidence.app.build_app [out_dir] [--fragment] [--no-scan] [--studio]

--studio builds the product-page style interface instead of the default terminal.

--fragment omits the <!doctype html>/<html> wrapper, for hosts that add their
own document skeleton (such as a claude.ai artifact). The local server
(server.py) renders the same page in memory and serves the sources from disk.
"""

from __future__ import annotations

import json
import os
import sys

from ..knowledge_base import PACKAGE_DIR, load_kb, load_repo_map
from ..repo_indexer import REPO_ROOT

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = {
    'terminal': os.path.join(APP_DIR, 'terminal.html'),   # default: market-terminal interface
    'studio': os.path.join(APP_DIR, 'template.html'),     # product-page style interface
}
TEMPLATE = TEMPLATES['terminal']
ENGINE = os.path.join(PACKAGE_DIR, 'web', 'engine.js')
DEFAULT_OUT = os.path.join(APP_DIR, 'dist')
CODE_EXTS = ('.py', '.js', '.json', '.html', '.cpp', '.h', '.hpp', '.md', '.txt', '.cmake', '.sh')
MAX_FILE_BYTES = 1_000_000

# Files of the new package shown first in the explorer, with a short description.
NEW_FILES = {
    'fincept-qt/scripts/Analytics/quant_evidence/stats.py':
        'Fórmulas de la literatura: Deflated Sharpe, MinBTL, recorte de Harvey y Liu, costos, Bodie, Kelly.',
    'fincept-qt/scripts/Analytics/quant_evidence/evaluator.py':
        'Evaluador de decisiones: puntaje de 0 a 100, cascada de la ventaja neta y chequeos con fuente.',
    'fincept-qt/scripts/Analytics/quant_evidence/web/engine.js':
        'Port línea a línea de stats.py y evaluator.py; una prueba de paridad garantiza los mismos números.',
    'fincept-qt/scripts/Analytics/quant_evidence/knowledge_base.py':
        'Carga y organiza la base de conocimiento y el mapa del repositorio.',
    'fincept-qt/scripts/Analytics/quant_evidence/repo_indexer.py':
        'Escaneo en vivo del repositorio por el vocabulario de cada categoría de evidencia.',
    'fincept-qt/scripts/Analytics/quant_evidence/data/evidence_kb.json':
        'Las 44 estrategias del informe con cifra clave, crítica, marcas de fiabilidad y fuentes.',
    'fincept-qt/scripts/Analytics/quant_evidence/data/repo_map.json':
        'Mapa curado de 235 módulos de FinceptTerminal y las brechas frente a la evidencia.',
    'fincept-qt/scripts/Analytics/quant_evidence_cli.py':
        'CLI JSON con la convención de los demás CLIs de Analytics.',
    'fincept-qt/scripts/Analytics/quant_studio.py':
        'Lanzador de esta app en modo local.',
    'fincept-qt/scripts/Analytics/quant_evidence/app/server.py':
        'Servidor local: API del motor Python, explorador del repositorio y ejecución de CLIs.',
    'fincept-qt/scripts/Analytics/quant_evidence/app/market.py':
        'Cotizaciones en vivo para la pantalla MERCADO (solo app local); nunca rellena un dato que no llegó.',
    'fincept-qt/scripts/Analytics/quant_evidence/app/alphavantage.py':
        'Proxy de Alpha Vantage para la app local: lista cerrada de funciones, una consulta por segundo, la clave nunca sale.',
    'fincept-qt/scripts/Analytics/quant_evidence/app/build_app.py':
        'Empaqueta la app y el índice de código.',
    'fincept-qt/scripts/Analytics/quant_evidence/app/terminal.html':
        'Interfaz de terminal financiera (predeterminada).',
    'fincept-qt/scripts/Analytics/quant_evidence/app/template.html':
        'Interfaz alternativa con estilo de página de producto.',
    'fincept-qt/scripts/Analytics/quant_evidence/build_web.py':
        'Construye la página Árbitro Quant.',
    'fincept-qt/scripts/Analytics/quant_evidence/tests/test_quant_evidence.py':
        'Pruebas: fórmulas contra los ejemplos del informe y paridad Python/JS.',
    'fincept-qt/scripts/Analytics/quant_evidence/tests/test_app.py':
        'Pruebas de la app: empaquetado, API y protección contra recorridos de rutas.',
    'fincept-qt/scripts/Analytics/quant_evidence/README.md':
        'Documentación del paquete.',
}


def _js_json(obj) -> str:
    # Escape "</" so embedded strings can never close the <script> element.
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')


def _line_count(path: str) -> int:
    with open(path, 'rb') as f:
        data = f.read()
    return data.count(b'\n') + (0 if data.endswith(b'\n') or not data else 1)


def code_index(root: str = REPO_ROOT) -> list[dict]:
    """Files shown in the code explorer: the new package, then every curated
    repo-map module that is a file. Directories in the map are skipped (the
    local server can browse them)."""
    entries, seen = [], set()

    def add(rel: str, group: str, summary: str = ''):
        full = os.path.join(root, rel)
        if rel in seen or not os.path.isfile(full) or not rel.endswith(CODE_EXTS):
            return
        size = os.path.getsize(full)
        if size > MAX_FILE_BYTES:
            return
        seen.add(rel)
        entries.append({'id': len(entries), 'path': rel, 'group': group, 'size': size,
                        'lines': _line_count(full), 'summary': summary})

    for rel, summary in NEW_FILES.items():
        add(rel, 'nuevo', summary)
    for m in load_repo_map().get('modules', []):
        add(m['path'], 'repo')
    return entries


_AUTO_INDEX: dict | None = None


def auto_index() -> dict:
    """Per-category file counts from the live keyword scan (cached per process)."""
    global _AUTO_INDEX
    if _AUTO_INDEX is None:
        from ..repo_indexer import scan
        result = scan(top_per_category=0)
        _AUTO_INDEX = {
            'files_scanned': result['files_scanned'],
            'categories': {k: {'file_count': v['file_count']} for k, v in result['categories'].items()},
        }
    return _AUTO_INDEX


def render_page(index: list[dict] | None = None, scan_repo: bool = True, standalone: bool = True,
                ui: str = 'terminal') -> str:
    if ui not in TEMPLATES:
        raise ValueError(f'Interfaz desconocida: {ui!r} (opciones: {", ".join(TEMPLATES)})')
    with open(TEMPLATES[ui], encoding='utf-8') as f:
        html = f.read()
    with open(ENGINE, encoding='utf-8') as f:
        engine = f.read()
    repo = dict(load_repo_map())
    if scan_repo:
        repo['auto_index'] = auto_index()
    if index is None:
        index = code_index()
    markers = ('/*__ENGINE__*/', '/*__KB__*/null', '/*__REPO__*/null', '/*__CODE_INDEX__*/null')
    for marker in markers:
        if marker not in html:
            raise RuntimeError(f'Template marker missing: {marker}')
    html = (html.replace('/*__ENGINE__*/', engine)
                .replace('/*__KB__*/null', _js_json(load_kb()))
                .replace('/*__REPO__*/null', _js_json(repo))
                .replace('/*__CODE_INDEX__*/null', _js_json(index)))
    if standalone:
        html = ('<!doctype html>\n<html lang="es">\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
                + html + '\n</html>\n')
    return html


def build(out_dir: str | None = None, standalone: bool = True, scan_repo: bool = True,
          root: str = REPO_ROOT, ui: str = 'terminal') -> dict:
    out_dir = out_dir or DEFAULT_OUT
    os.makedirs(os.path.join(out_dir, 'code'), exist_ok=True)
    index = code_index(root)
    for e in index:
        with open(os.path.join(root, e['path']), encoding='utf-8', errors='replace') as src, \
                open(os.path.join(out_dir, 'code', f"{e['id']}.txt"), 'w', encoding='utf-8') as dst:
            # Some repo files already contain U+FFFD from a past bad decode; static
            # hosts may reject it, so the published copy shows '?' instead.
            dst.write(src.read().replace('\ufffd', '?'))
    page = os.path.join(out_dir, 'index.html')
    with open(page, 'w', encoding='utf-8') as f:
        f.write(render_page(index, scan_repo=scan_repo, standalone=standalone, ui=ui))
    return {'page': page, 'files': len(index), 'out_dir': out_dir, 'ui': ui}


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    ui = 'studio' if '--studio' in sys.argv else 'terminal'
    print(json.dumps(build(args[0] if args else None, standalone='--fragment' not in sys.argv,
                           scan_repo='--no-scan' not in sys.argv, ui=ui)))
