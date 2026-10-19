"""
Tests for app/build_lab.py (Laboratorio Fincept): the page builds with every
marker replaced, its scripts parse, and the inlined data cannot close a
<script> tag early. Stdlib only (Node optional, for the syntax check):

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS = os.path.dirname(os.path.dirname(HERE))
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence.app import build_lab  # noqa: E402


class TestLabBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.out = build_lab.build(os.path.join(cls.tmp, 'laboratorio.html'))
        with open(cls.out, encoding='utf-8') as f:
            cls.html = f.read()
        cls.scripts = re.findall(r'<script>(.*?)</script>', cls.html, re.S)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_markers_replaced(self):
        for marker in build_lab.MARKERS:
            self.assertNotIn(marker, self.html)
        self.assertIn('<title>Laboratorio Fincept</title>', self.html[:8192])
        self.assertIn('root.QuantEvidence = factory()', self.html)
        self.assertIn('root.QuantSeries = factory()', self.html)

    def test_inlined_data_is_safe_and_complete(self):
        self.assertEqual(len(self.scripts), 4)
        data = self.scripts[2]
        kb = json.loads(re.search(r'var KB = (.*?);\nvar PAPERS', data, re.S).group(1).replace('<\\/', '</'))
        with open(build_lab.KB, encoding='utf-8') as f:
            full = json.load(f)
        ids = [s['id'] for s in kb['strategies']]
        self.assertEqual(ids, [s['id'] for s in full['strategies'] if s['id'] not in build_lab.EXCLUDED_STRATEGIES])
        self.assertEqual({k: v for k, v in kb.items() if k != 'strategies'}, {k: v for k, v in full.items() if k != 'strategies'})
        self.assertNotIn('</', data)

    def test_markowitz_is_not_offered(self):
        self.assertNotIn('markowitz_sample', self.html)
        self.assertNotIn('Optimización de Markowitz', self.html)

    def test_inline_json_escapes_script_close(self):
        s = build_lab._inline_json({'x': '</script><b>', 'y': ' '})
        self.assertNotIn('</', s)
        self.assertNotIn(' ', s)
        self.assertEqual(json.loads(s.replace('<\\/', '</')), {'x': '</script><b>', 'y': ' '})

    @unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
    def test_scripts_parse(self):
        for i, src in enumerate(self.scripts):
            path = os.path.join(self.tmp, f's{i}.js')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(src)
            proc = subprocess.run(['node', '--check', path], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == '__main__':
    unittest.main()
