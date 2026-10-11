"""
Tests for quant_evidence.mcp_server, the stdio MCP server. Stdlib only:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .

The server is spawned as a subprocess and driven with newline-delimited
JSON-RPC 2.0, the way an MCP client such as Claude Code talks to it.
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
ANALYTICS = os.path.dirname(PKG)
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence import mcp_server  # noqa: E402
from quant_evidence.evaluator import evaluate_decision  # noqa: E402

SERVER = os.path.join(PKG, 'mcp_server.py')
EXPECTED_TOOLS = ['search_strategies', 'get_strategy', 'evaluate_decision', 'compare_strategies',
                  'breakeven_points', 'deflated_sharpe', 'haircut_sharpe', 'min_backtest_length', 'cost_drag',
                  'horizon_risk', 'kelly', 'repo_modules']


class McpSession:
    """A server subprocess with a request/response helper."""

    def __init__(self, cmd, cwd=None):
        self.proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.next_id = 0

    def send(self, msg):
        self.proc.stdin.write(json.dumps(msg).encode('utf-8') + b'\n')
        self.proc.stdin.flush()

    def recv(self):
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError('server closed stdout: ' + self.proc.stderr.read().decode('utf-8', 'replace'))
        return json.loads(line)

    def request(self, method, params=None):
        self.next_id += 1
        msg = {'jsonrpc': '2.0', 'id': self.next_id, 'method': method}
        if params is not None:
            msg['params'] = params
        self.send(msg)
        reply = self.recv()
        assert reply.get('id') == self.next_id, reply
        return reply

    def close(self):
        self.proc.stdin.close()
        rc = self.proc.wait(timeout=30)
        rest = self.proc.stdout.read()
        stderr = self.proc.stderr.read().decode('utf-8', 'replace')
        self.proc.stdout.close()
        self.proc.stderr.close()
        return rc, rest, stderr


class TestMcpServerProtocol(unittest.TestCase):
    def setUp(self):
        self.s = McpSession([sys.executable, SERVER])

    def tearDown(self):
        if self.s.proc.poll() is None:
            self.s.close()

    def _call(self, name, arguments):
        r = self.s.request('tools/call', {'name': name, 'arguments': arguments})
        self.assertIn('result', r, r)
        return r['result']

    def test_session(self):
        r = self.s.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                          'clientInfo': {'name': 'test', 'version': '0'}})
        res = r['result']
        self.assertEqual(res['protocolVersion'], '2025-06-18')
        self.assertEqual(res['serverInfo']['name'], 'fincept-quant')
        self.assertIn('tools', res['capabilities'])
        self.s.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})  # no reply expected

        tools = self.s.request('tools/list')['result']['tools']
        self.assertEqual([t['name'] for t in tools], EXPECTED_TOOLS)
        for t in tools:
            self.assertEqual(t['inputSchema']['type'], 'object')
            self.assertIn('not investment advice', t['description'])
            for k in t['inputSchema'].get('required', []):
                self.assertIn(k, t['inputSchema']['properties'])

        decision = {'strategy_id': 'momentum', 'sharpe_annual': 1.2, 'years': 8, 'n_trials': 50,
                    'periods_per_year': 12}
        res = self._call('evaluate_decision', decision)
        self.assertNotIn('isError', res)
        data = json.loads(res['content'][0]['text'])
        ref = evaluate_decision(decision)
        self.assertEqual(data['verdict']['code'], ref['verdict']['code'])
        self.assertAlmostEqual(data['scores']['final'], ref['scores']['final'])

        res = self._call('evaluate_decision', {'strategy_id': 'no_such_strategy'})
        self.assertTrue(res['isError'])
        self.assertIn('no_such_strategy', res['content'][0]['text'])
        res = self._call('kelly', {'mu': 0.08})  # sigma missing
        self.assertTrue(res['isError'])
        self.assertIn('sigma', res['content'][0]['text'])

        r = self.s.request('resources/list')
        self.assertEqual(r['error']['code'], -32601)
        r = self.s.request('tools/call', {'name': 'nope', 'arguments': {}})
        self.assertEqual(r['error']['code'], -32602)
        self.assertEqual(self.s.request('ping')['result'], {})

        rc, rest, stderr = self.s.close()
        self.assertEqual(rc, 0)
        self.assertEqual(rest, b'')  # nothing but replies on stdout
        self.assertIn('[fincept-quant]', stderr)

    def test_tools_return_engine_figures(self):
        self.s.request('initialize', {'protocolVersion': '2025-06-18', 'capabilities': {}})
        dsr = json.loads(self._call('deflated_sharpe', {'sharpe_annual': 2.5, 'n_trials': 100, 'years': 5,
                                                        'periods_per_year': 250, 'var_trials_sr': 0.5,
                                                        'skew': -3, 'kurtosis': 10})['content'][0]['text'])
        self.assertAlmostEqual(dsr['dsr'], 0.90, places=2)
        be = json.loads(self._call('breakeven_points', {'strategy_id': 'momentum', 'sharpe_annual': 1.2,
                                                        'years': 8, 'n_trials': 50,
                                                        'periods_per_year': 12})['content'][0]['text'])
        self.assertEqual(be['breakeven_roundtrip_cost_bps'], 23)
        found = json.loads(self._call('search_strategies', {'query': 'momentum'})['content'][0]['text'])
        ids = [x['id'] for x in found['results']]
        self.assertEqual(ids[0], 'tsmom_futures')  # ties on match score are broken by evidence rating
        self.assertIn('momentum', ids)
        # Non-finite floats become null rather than invalid JSON.
        mbl = json.loads(self._call('min_backtest_length', {'n_trials': 10, 'target_sharpe': 0})
                         ['content'][0]['text'])
        self.assertIn('min_years', mbl)
        self.assertTrue(self._call('min_backtest_length', {'target_sharpe': 1})['isError'])

    def test_older_protocol_and_bad_input(self):
        r = self.s.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {}})
        self.assertEqual(r['result']['protocolVersion'], '2024-11-05')
        self.s.proc.stdin.write(b'not json\n')
        self.s.proc.stdin.flush()
        self.assertEqual(self.s.recv()['error']['code'], -32700)
        r = self.s.request('tools/call', {'name': 'get_strategy', 'arguments': 'momentum'})
        self.assertTrue(r['result']['isError'])
        r = self.s.request('tools/call', {'name': 'get_strategy', 'arguments': {'id': 'momentum'}})
        self.assertEqual(json.loads(r['result']['content'][0]['text'])['id'], 'momentum')


class TestMcpServerModule(unittest.TestCase):
    def test_runs_as_module(self):
        s = McpSession([sys.executable, '-m', 'quant_evidence.mcp_server'], cwd=ANALYTICS)
        try:
            r = s.request('initialize', {'protocolVersion': '1999-01-01', 'capabilities': {}})
            self.assertEqual(r['result']['protocolVersion'], mcp_server.PROTOCOL_VERSION)
        finally:
            self.assertEqual(s.close()[0], 0)

    def test_handle_message_rules(self):
        self.assertIsNone(mcp_server.handle_message({'jsonrpc': '2.0', 'method': 'notifications/cancelled'}))
        self.assertIsNone(mcp_server.handle_message({'jsonrpc': '2.0', 'id': 9, 'result': {}}))
        self.assertEqual(mcp_server.handle_message([1])['error']['code'], -32600)
        self.assertEqual(mcp_server.handle_line(b'\xff\n')['error']['code'], -32700)
        self.assertIsNone(mcp_server.handle_line('  \n'))


if __name__ == '__main__':
    unittest.main()
