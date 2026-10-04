"""
Local server for Fincept Quant Studio (stdlib only).

Serves the app and a JSON API so the page runs on the Python engine and can
reach the whole repository:

    GET  /                      the app (terminal interface)
    GET  /studio                the product-page style interface
    GET  /api/health            {"app": "quant-studio", ...}
    GET  /api/kb | /api/repo-map
    POST /api/evaluate          quant_evidence.evaluate_decision(body)
    POST /api/tool/<command>    any quant_evidence_cli command (deflated_sharpe, ...)
    GET  /api/repo/scan         live keyword scan of the repository
    GET  /api/repo/tree?path=   directory listing under fincept-qt/
    GET  /api/repo/file?path=   text of a file under fincept-qt/
    GET  /api/run/list          repository CLIs that can be run
    POST /api/run               {"script", "command", "params"} -> CLI output

It binds to 127.0.0.1 by default, accepts only localhost Host headers (DNS
rebinding) and JSON POST bodies (no cross-site simple requests), and never
reads outside fincept-qt/.

    python quant_studio.py [--port 8765] [--host 127.0.0.1] [--no-browser]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from ..evaluator import evaluate_decision
from ..knowledge_base import load_kb, load_repo_map
from ..repo_indexer import REPO_ROOT
from .build_app import code_index, render_page

ANALYTICS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
FILE_ROOT = os.path.realpath(os.path.join(REPO_ROOT, 'fincept-qt'))
MAX_FILE_BYTES = 2_000_000
MAX_BODY_BYTES = 256_000
MAX_OUTPUT_BYTES = 400_000
RUN_TIMEOUT_S = 60
TREE_SKIP = {'__pycache__', 'node_modules', 'build', '.venv', 'venv', 'dist'}
LOCAL_HOSTS = {'localhost', '127.0.0.1', '[::1]', '::1'}
COMMAND_RE = re.compile(r'^[a-z][a-z0-9_]{0,40}$')

RUNNABLE = [
    {'id': 'quant_evidence', 'label': 'quant_evidence_cli.py · paquete nuevo', 'script': 'quant_evidence_cli.py'},
    {'id': 'cfa_quant', 'label': 'quant_analytics_cli.py · CFA Quant', 'script': 'quant_analytics_cli.py'},
    {'id': 'statsmodels', 'label': 'statsmodels_cli.py · Statsmodels', 'script': 'statsmodels_cli.py'},
    {'id': 'financial_analysis', 'label': 'financial_analysis_cli.py · Análisis financiero',
     'script': 'financial_analysis_cli.py'},
]


def _sanitize(obj):
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def resolve_repo_path(rel: str) -> str | None:
    """Absolute path for a repo-relative path, or None if it escapes fincept-qt/."""
    if not rel or '\x00' in rel or os.path.isabs(rel):
        return None
    full = os.path.realpath(os.path.join(REPO_ROOT, rel))
    if full != FILE_ROOT and not full.startswith(FILE_ROOT + os.sep):
        return None
    return full


def _rel(full: str) -> str:
    return os.path.relpath(full, REPO_ROOT).replace(os.sep, '/')


def list_dir(rel: str) -> dict:
    full = resolve_repo_path(rel)
    if full is None or not os.path.isdir(full):
        raise PermissionError('Carpeta fuera del repositorio o inexistente.')
    dirs, files = [], []
    with os.scandir(full) as it:
        for e in sorted(it, key=lambda e: e.name.lower()):
            if e.name.startswith('.') or e.name in TREE_SKIP:
                continue
            target = os.path.realpath(e.path)
            if target != FILE_ROOT and not target.startswith(FILE_ROOT + os.sep):
                continue  # symlink pointing outside fincept-qt/
            if e.is_dir():
                dirs.append({'name': e.name, 'path': _rel(e.path)})
            elif e.is_file():
                files.append({'name': e.name, 'path': _rel(e.path), 'size': e.stat().st_size})
    return {'path': _rel(full), 'dirs': dirs, 'files': files}


def read_text(rel: str) -> dict:
    full = resolve_repo_path(rel)
    if full is None or not os.path.isfile(full):
        raise PermissionError('Archivo fuera del repositorio o inexistente.')
    size = os.path.getsize(full)
    if size > MAX_FILE_BYTES:
        raise ValueError(f'El archivo pesa {size // 1024} KB; el límite es {MAX_FILE_BYTES // 1024} KB.')
    with open(full, 'rb') as f:
        data = f.read()
    if b'\x00' in data[:8192]:
        raise ValueError('Es un archivo binario.')
    return {'path': _rel(full), 'size': size, 'text': data.decode('utf-8', errors='replace')}


def run_cli(script_id: str, command: str, params) -> dict:
    spec = next((r for r in RUNNABLE if r['id'] == script_id), None)
    if spec is None:
        raise ValueError('Programa no permitido.')
    if not isinstance(command, str) or not COMMAND_RE.match(command):
        raise ValueError('El comando solo puede tener letras minúsculas, números y guiones bajos.')
    if not isinstance(params, dict):
        raise ValueError('Los parámetros deben ser un objeto JSON.')
    script = os.path.join(ANALYTICS_DIR, spec['script'])
    if not os.path.isfile(script):
        raise ValueError(f"No se encontró {spec['script']}.")
    t0 = time.time()
    try:
        proc = subprocess.run([sys.executable, script, command, json.dumps(params)], cwd=ANALYTICS_DIR,
                              capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise ValueError(f'El programa tardó más de {RUN_TIMEOUT_S} s y se detuvo.')
    out = proc.stdout[:MAX_OUTPUT_BYTES]
    parsed = None
    try:
        parsed = json.loads(out)
    except ValueError:
        pass
    return {'returncode': proc.returncode, 'stdout': out, 'stderr': proc.stderr[-4000:],
            'parsed': parsed, 'seconds': round(time.time() - t0, 2)}


class StudioHandler(BaseHTTPRequestHandler):
    server_version = 'QuantStudio/1.0'
    page: str = ''
    studio_page: str = ''
    index: list = []
    by_id: dict = {}

    def log_message(self, fmt, *args):  # quieter console
        if os.environ.get('QUANT_STUDIO_VERBOSE'):
            super().log_message(fmt, *args)

    # ── helpers ────────────────────────────────────────────────────────────
    def _host_ok(self) -> bool:
        host = (self.headers.get('Host') or '').strip().lower()
        name = host.rsplit(':', 1)[0] if not host.startswith('[') else host.split(']')[0] + ']'
        return name in LOCAL_HOSTS or name == self.server.server_address[0]

    def _send(self, status: int, body: bytes, ctype: str):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, status: int = 200):
        self._send(status, json.dumps(data, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

    def _ok(self, data):
        self._json({'success': True, 'data': _sanitize(data)})

    def _err(self, msg: str, status: int = 400):
        self._json({'success': False, 'error': msg}, status)

    def _body(self):
        if not (self.headers.get('Content-Type') or '').startswith('application/json'):
            raise PermissionError('Se requiere Content-Type: application/json.')
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY_BYTES:
            raise ValueError('Cuerpo demasiado grande.')
        raw = self.rfile.read(n) if n else b'{}'
        return json.loads(raw.decode('utf-8') or '{}')

    # ── routes ─────────────────────────────────────────────────────────────
    def do_GET(self):
        if not self._host_ok():
            return self._err('Host no permitido.', HTTPStatus.FORBIDDEN)
        url = urlparse(self.path)
        q = parse_qs(url.query)
        path = url.path
        try:
            if path in ('/', '/index.html'):
                return self._send(200, self.page.encode('utf-8'), 'text/html; charset=utf-8')
            if path in ('/studio', '/studio/'):
                return self._send(200, self.studio_page.encode('utf-8'), 'text/html; charset=utf-8')
            m = re.match(r'^/code/(\d+)\.txt$', path)
            if m:
                e = self.by_id.get(int(m.group(1)))
                if not e:
                    return self._err('No existe.', HTTPStatus.NOT_FOUND)
                return self._send(200, read_text(e['path'])['text'].encode('utf-8'), 'text/plain; charset=utf-8')
            if path == '/api/health':
                return self._ok({'app': 'quant-studio', 'repo_root': REPO_ROOT, 'python': sys.version.split()[0],
                                 'files_indexed': len(self.index)})
            if path == '/api/kb':
                return self._ok(load_kb())
            if path == '/api/repo-map':
                return self._ok(load_repo_map())
            if path == '/api/repo/scan':
                from ..repo_indexer import scan
                return self._ok(scan())
            if path == '/api/repo/tree':
                return self._ok(list_dir((q.get('path') or ['fincept-qt'])[0]))
            if path == '/api/repo/file':
                return self._ok(read_text((q.get('path') or [''])[0]))
            if path == '/api/run/list':
                return self._ok([{'id': r['id'], 'label': r['label']} for r in RUNNABLE])
            return self._err('Ruta desconocida.', HTTPStatus.NOT_FOUND)
        except PermissionError as e:
            return self._err(str(e), HTTPStatus.FORBIDDEN)
        except (ValueError, OSError) as e:
            return self._err(str(e))

    def do_POST(self):
        if not self._host_ok():
            return self._err('Host no permitido.', HTTPStatus.FORBIDDEN)
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == '/api/evaluate':
                return self._ok(evaluate_decision(body))
            m = re.match(r'^/api/tool/([a-z_]+)$', path)
            if m:
                if ANALYTICS_DIR not in sys.path:
                    sys.path.insert(0, ANALYTICS_DIR)
                import quant_evidence_cli as cli
                fn = cli.COMMANDS.get(m.group(1))
                if fn is None or m.group(1) == 'export_web':
                    return self._err('Herramienta desconocida.', HTTPStatus.NOT_FOUND)
                return self._ok(fn(body))
            if path == '/api/run':
                return self._ok(run_cli(body.get('script'), body.get('command'), body.get('params', {})))
            return self._err('Ruta desconocida.', HTTPStatus.NOT_FOUND)
        except PermissionError as e:
            return self._err(str(e), HTTPStatus.FORBIDDEN)
        except (ValueError, TypeError, KeyError, OSError) as e:
            return self._err(str(e))


def make_server(host: str = '127.0.0.1', port: int = 8765, scan_repo: bool = True) -> ThreadingHTTPServer:
    index = code_index()

    class Handler(StudioHandler):
        pass

    Handler.index = index
    Handler.by_id = {e['id']: e for e in index}
    Handler.page = render_page(index, scan_repo=scan_repo, standalone=True, ui='terminal')
    Handler.studio_page = render_page(index, scan_repo=scan_repo, standalone=True, ui='studio')
    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Fincept Quant Studio (servidor local)')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--no-scan', action='store_true', help='omite el escaneo de vocabulario al arrancar')
    args = ap.parse_args(argv)
    print('Preparando Fincept Quant Studio…', flush=True)
    srv = make_server(args.host, args.port, scan_repo=not args.no_scan)
    url = f'http://{"127.0.0.1" if args.host in ("0.0.0.0", "") else args.host}:{srv.server_address[1]}/'
    print(f'Listo: {url}  (Ctrl+C para salir)', flush=True)
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == '__main__':
    main()
