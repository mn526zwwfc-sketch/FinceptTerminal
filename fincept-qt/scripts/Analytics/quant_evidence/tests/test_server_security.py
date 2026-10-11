"""
Regression tests for the local server's protections (quant_evidence/app/server.py):
RUN cannot write files, strict Host parsing, cross-site API requests and
Content-Length limits. Stdlib only:

    cd fincept-qt/scripts/Analytics
    python -m unittest discover -s quant_evidence/tests -t .
"""

import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ANALYTICS = os.path.dirname(os.path.dirname(HERE))
if ANALYTICS not in sys.path:
    sys.path.insert(0, ANALYTICS)

from quant_evidence.app.server import make_server  # noqa: E402


class TestServerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server('127.0.0.1', 0, scan_repo=False)
        cls.port = cls.srv.server_address[1]
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        h = {'Host': f'127.0.0.1:{self.port}'}
        if body is not None:
            h['Content-Type'] = 'application/json'
        h.update(headers or {})
        c.request(method, path, body=None if body is None else json.dumps(body), headers=h)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, json.loads(data)

    def raw(self, request: bytes) -> bytes:
        with socket.create_connection(('127.0.0.1', self.port), timeout=10) as s:
            s.sendall(request)
            s.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                b = s.recv(65536)
                if not b:
                    break
                chunks.append(b)
        return b''.join(chunks)

    def test_run_refuses_export_web(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'should_not_exist.html')
            st, j = self.req('POST', '/api/run', {'script': 'quant_evidence', 'command': 'export_web',
                                                  'params': {'output': out}})
            self.assertFalse(j['success'])
            self.assertFalse(os.path.exists(out))

    def test_run_command_rejects_trailing_newline(self):
        st, j = self.req('POST', '/api/run', {'script': 'quant_evidence', 'command': 'list\n', 'params': {}})
        self.assertFalse(j['success'])

    def test_host_suffix_after_ipv6_literal_is_rejected(self):
        for host in ('[::1].evil.com', '[::1]evil.com:80', 'localhost:evil', 'localhost.evil.com'):
            st, j = self.req('GET', '/api/health', headers={'Host': host})
            self.assertEqual(st, 403, host)

    def test_local_hosts_are_accepted(self):
        for host in (f'localhost:{self.port}', '127.0.0.1', '[::1]:8765'):
            st, j = self.req('GET', '/api/health', headers={'Host': host})
            self.assertEqual(st, 200, host)

    def test_cross_site_api_get_is_rejected(self):
        st, j = self.req('GET', '/api/repo/scan', headers={'Sec-Fetch-Site': 'cross-site'})
        self.assertEqual(st, 403)
        st, j = self.req('GET', '/api/health', headers={'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(st, 200)

    def test_negative_content_length_is_rejected(self):
        resp = self.raw(b'POST /api/tool/categories HTTP/1.1\r\n'
                        + f'Host: 127.0.0.1:{self.port}\r\n'.encode()
                        + b'Content-Type: application/json\r\nContent-Length: -1\r\n\r\n{}')
        self.assertTrue(resp.startswith(b'HTTP/1.0 400') or resp.startswith(b'HTTP/1.1 400'), resp[:40])

    def test_non_numeric_content_length_is_rejected(self):
        resp = self.raw(b'POST /api/tool/categories HTTP/1.1\r\n'
                        + f'Host: 127.0.0.1:{self.port}\r\n'.encode()
                        + b'Content-Type: application/json\r\nContent-Length: abc\r\n\r\n{}')
        self.assertIn(b' 400 ', resp.split(b'\r\n', 1)[0])

    def test_arithmetic_errors_return_400(self):
        for body in ({'sharpe_annual': 1.0, 'years': 5, 'periods_per_year': 0},
                     {'sharpe_annual': 1.0, 'years': 5, 'n_trials': 1e400}):
            st, j = self.req('POST', '/api/tool/deflated_sharpe', body)
            self.assertEqual(st, 400, body)
            self.assertFalse(j['success'])


if __name__ == '__main__':
    unittest.main()
