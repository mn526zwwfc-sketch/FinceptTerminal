"""
Tests for web/series.js (series analytics used by the Laboratorio page):
parsing, moments, Minimum Track Record Length, the bootstrap and PBO by
CSCV, each checked against an independent Python reference. Needs Node:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .
"""

import itertools
import json
import math
import os
import random
import shutil
import subprocess
import unittest
from statistics import NormalDist

HERE = os.path.dirname(os.path.abspath(__file__))
SERIES_JS = os.path.join(os.path.dirname(HERE), 'web', 'series.js')


def _node(script, *args):
    wrapped = ("const S=require(process.argv[1]);const A=process.argv.slice(2).map(a=>JSON.parse(a));"
               "const out=(()=>{" + script + "})();"
               "process.stdout.write(JSON.stringify(out,(k,v)=>typeof v==='number'&&!isFinite(v)?String(v):v));")
    proc = subprocess.run(['node', '-e', wrapped, SERIES_JS, *[json.dumps(a) for a in args]],
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def _moments(r):
    n = len(r)
    mean = sum(r) / n
    m2 = sum((x - mean) ** 2 for x in r) / n
    m3 = sum((x - mean) ** 3 for x in r) / n
    m4 = sum((x - mean) ** 4 for x in r) / n
    return mean, math.sqrt(m2 * n / (n - 1)), m3 / m2 ** 1.5, m4 / m2 ** 2


def _sharpe(r):
    mean, sd, _, _ = _moments(r)
    return mean / sd


def _pbo_reference(columns, blocks):
    """Straight transcription of CSCV (Bailey, Borwein, Lopez de Prado & Zhu 2017)."""
    n_var, t = len(columns), len(columns[0])
    length = t // blocks
    start = t - length * blocks
    parts = [list(range(start + s * length, start + (s + 1) * length)) for s in range(blocks)]
    over = 0
    total = 0
    for is_blocks in itertools.combinations(range(blocks), blocks // 2):
        is_rows = [i for b in is_blocks for i in parts[b]]
        oos_rows = [i for b in range(blocks) if b not in is_blocks for i in parts[b]]
        is_sr = [_sharpe([c[i] for i in is_rows]) for c in columns]
        oos_sr = [_sharpe([c[i] for i in oos_rows]) for c in columns]
        best = max(range(n_var), key=lambda k: (is_sr[k], -k))
        pick = oos_sr[best]
        below = sum(1 for k in range(n_var) if oos_sr[k] < pick)
        ties = sum(1 for k in range(n_var) if oos_sr[k] == pick and k != best)
        omega = (below + 1 + ties / 2) / (n_var + 1)
        over += math.log(omega / (1 - omega)) <= 0
        total += 1
    return over / total


@unittest.skipUnless(shutil.which('node'), 'Node.js not installed')
class TestSeries(unittest.TestCase):
    def setUp(self):
        rnd = random.Random(11)
        self.cols = [[rnd.gauss(0.004, 0.04) for _ in range(96)] for _ in range(6)]

    def test_moments_and_summary(self):
        r = self.cols[0]
        js = _node('return [S.moments(A[0]), S.summarize(A[0], 12)];', r)
        mean, sd, skew, kurt = _moments(r)
        self.assertAlmostEqual(js[0]['mean'], mean, places=12)
        self.assertAlmostEqual(js[0]['sd'], sd, places=12)
        self.assertAlmostEqual(js[0]['skew'], skew, places=10)
        self.assertAlmostEqual(js[0]['kurtosis'], kurt, places=10)
        self.assertAlmostEqual(js[1]['sharpe_annual'], mean / sd * math.sqrt(12), places=10)
        equity, peak, worst = 1.0, 1.0, 0.0
        for x in r:
            equity *= 1 + x
            peak = max(peak, equity)
            worst = min(worst, equity / peak - 1)
        self.assertAlmostEqual(js[1]['max_drawdown'], worst, places=12)
        self.assertAlmostEqual(js[1]['total_return'], equity - 1, places=12)

    def test_min_track_record_length(self):
        z = NormalDist().inv_cdf(0.95)
        for sr, skew, kurt in ((0.2, -0.5, 5.0), (0.1, 0.0, 3.0), (0.35, 1.0, 9.0)):
            ref = 1 + (1 - skew * sr + (kurt - 1) / 4 * sr * sr) * (z / sr) ** 2
            self.assertAlmostEqual(_node('return S.minTrackRecordLength(A[0], 0, A[1], A[2], 0.05);', sr, skew, kurt),
                                   ref, delta=ref * 1e-8)
        self.assertEqual(_node('return S.minTrackRecordLength(-0.1, 0, 0, 3);'), 'Infinity')

    def test_pbo_matches_reference(self):
        js = _node('return S.pbo(A[0], {blocks: 8});', self.cols)
        self.assertEqual(js['splits'], math.comb(8, 4))
        self.assertAlmostEqual(js['pbo'], _pbo_reference(self.cols, 8), places=12)

    def test_pbo_finds_a_real_edge(self):
        cols = [list(c) for c in self.cols]
        cols[2] = [x + 0.03 for x in cols[2]]
        self.assertEqual(_node('return S.pbo(A[0], {blocks: 8}).pbo;', cols), 0.0)

    def test_bootstrap_is_reproducible_and_brackets_the_estimate(self):
        a, b = _node('return [S.bootstrapSharpe(A[0], 12), S.bootstrapSharpe(A[0], 12)];', self.cols[0])
        self.assertEqual(a, b)
        sr = _sharpe(self.cols[0]) * math.sqrt(12)
        self.assertLess(a['lo'], sr)
        self.assertGreater(a['hi'], sr)

    def test_parse_table(self):
        text = 'fecha;A;B\n2020-03-31;2%;-1\n2020-01-31;1,5%;2\n2020-02-29;-0,5%;1\nfoo;x;1\n'
        t = _node('return S.parseTable(A[0]);', text)
        self.assertEqual(t['names'], ['A', 'B'])
        self.assertEqual(t['columns'], [[0.015, -0.005, 0.02], [2, 1, -1]])   # sorted oldest first
        self.assertEqual(t['skipped'], 1)
        self.assertEqual(_node('return S.inferPeriodsPerYear(S.parseTable(A[0]).dates);', text), 12)
        plain = _node('return S.parseTable(A[0]);', '0.01\n-0.02\n0.03\n')
        self.assertIsNone(plain['dates'])
        self.assertEqual(plain['columns'], [[0.01, -0.02, 0.03]])

    def test_detect_kind_and_returns(self):
        kinds = _node('return [S.detectKind([100,101,99,105]), S.detectKind([0.01,-0.02,0.03]),'
                      ' S.detectKind([1.2,-3,2.5]), S.toReturns([100,110,99], "prices")];')
        self.assertEqual(kinds[:3], ['prices', 'returns', 'percent'])
        self.assertAlmostEqual(kinds[3][0], 0.1)
        self.assertAlmostEqual(kinds[3][1], -0.1)

    def test_errors(self):
        with self.assertRaises(subprocess.CalledProcessError):
            _node('return S.parseTable("texto sin numeros");')
        with self.assertRaises(subprocess.CalledProcessError):
            _node('return S.pbo([[0.1, 0.2, 0.3]]);')


if __name__ == '__main__':
    unittest.main()
