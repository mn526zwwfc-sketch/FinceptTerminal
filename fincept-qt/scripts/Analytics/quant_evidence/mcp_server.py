"""
MCP server for quant_evidence (stdlib only).

Speaks the Model Context Protocol over stdio: newline-delimited JSON-RPC 2.0,
one message per line. It exposes the evidence knowledge base, the decision
evaluator and the statistics as tools, reusing the commands of
quant_evidence_cli.py, so an MCP client (Claude Code, for instance) gets the
same numbers as the CLI and the web pages.

    python3 fincept-qt/scripts/Analytics/quant_evidence/mcp_server.py
    cd fincept-qt/scripts/Analytics && python3 -m quant_evidence.mcp_server

stdout carries protocol messages only; logs go to stderr. Every figure is
educational, not investment advice.
"""

from __future__ import annotations

import json
import os
import sys

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ANALYTICS_DIR = os.path.dirname(_PKG_DIR)
if __package__ in (None, ''):
    # Run as a script: sys.path[0] is the package dir; import the package from its parent instead.
    sys.path = [p for p in sys.path if os.path.abspath(p or '.') != _PKG_DIR]
if _ANALYTICS_DIR not in sys.path:
    sys.path.insert(0, _ANALYTICS_DIR)

import quant_evidence_cli as cli  # noqa: E402
from quant_evidence.knowledge_base import load_kb  # noqa: E402

SERVER_NAME = 'fincept-quant'
SERVER_VERSION = '1.0.0'
PROTOCOL_VERSION = '2025-06-18'
SUPPORTED_PROTOCOL_VERSIONS = ('2025-06-18', '2025-03-26', '2024-11-05')

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = \
    -32700, -32600, -32601, -32602, -32603

NOT_ADVICE = 'Figures are educational, not investment advice.'
INSTRUCTIONS = (
    'Academic evidence on 44 quant strategies and a decision evaluator. Typical flow: search_strategies '
    'to get a strategy_id, then evaluate_decision with only the data the user gave, then '
    'compare_strategies or breakeven_points if useful; get_strategy cites the evidence and sources. '
    'Every number must come from a tool. Strategy texts are in Spanish. ' + NOT_ADVICE)


def _log(msg: str) -> None:
    sys.stderr.write(f'[{SERVER_NAME}] {msg}\n')
    sys.stderr.flush()


# ── Tool definitions ──────────────────────────────────────────────────────

def _num(description: str) -> dict:
    return {'type': 'number', 'description': description}


def _int(description: str, minimum: int = 1) -> dict:
    return {'type': 'integer', 'minimum': minimum, 'description': description}


def _bool(description: str) -> dict:
    return {'type': 'boolean', 'description': description}


def _schema(properties: dict, required: tuple = ()) -> dict:
    out = {'type': 'object', 'properties': properties}
    if required:
        out['required'] = list(required)
    return out


STRATEGY_ID = {'type': 'string', 'description': 'Strategy id from search_strategies (e.g. "momentum").'}
MARKET = {'type': 'string', 'enum': ['global', 'us', 'mx', 'other'], 'description': 'Market. Default global.'}
INVESTOR = {'type': 'string', 'enum': ['retail', 'institutional'], 'description': 'Investor type. Default retail.'}

DECISION_PROPS = {
    'strategy_id': STRATEGY_ID,
    'sharpe_annual': _num('Annual Sharpe ratio of the backtest (only if the user gave one).'),
    'years': _num('Years of backtest data; with sharpe_annual it enables the statistical checks.'),
    'n_trials': _int('Variants, parameters or models tried before choosing this one. Default 1.'),
    'periods_per_year': _int('Return frequency: 252 daily, 52 weekly, 12 monthly. Default 252.'),
    'skew': _num('Skewness of returns. Default 0.'),
    'kurtosis': _num('Raw kurtosis of returns (normal = 3). Default 3.'),
    'var_trials_sr': _num('Cross-trial variance of annualized Sharpe ratios. Default 1 / years.'),
    'gross_alpha_monthly_bps': _num('Gross edge in bps per month; otherwise Sharpe x volatility / 12 '
                                    'or the literature figure.'),
    'volatility_annual': _num('Annual volatility as a fraction, 0.15 = 15%. Default 0.15.'),
    'turnover_monthly': _num('Fraction of each leg replaced per month, 0.6 = 60%. Default: strategy profile.'),
    'roundtrip_cost_bps': _num('Spread + commission + impact for a sell and a buy, in bps. Default 40 retail, '
                               '15 institutional, x1.5 in Mexico.'),
    'long_short': _bool('Needs short sales. Default: strategy profile.'),
    'uses_leverage': _bool('Needs leverage. Default: strategy profile.'),
    'microcap_share': _num('Share of the alpha that comes from microcaps, 0 to 1. Default by profile.'),
    'published': _bool('The idea comes from a paper, book or the internet. Default true.'),
    'out_of_sample': _bool('Validated out of sample. Default false.'),
    'live_months': _num('Months traded live. Default 0.'),
    'investor': INVESTOR,
    'market': MARKET,
    'horizon_years': _num('Investment horizon in years. Default 10.'),
    'kelly_multiple': _num('Bet size as a multiple of full Kelly, 0.5 = half Kelly.'),
}
# breakeven_points only uses inputs that move the net edge (decisionFrom() in the chat agent).
BREAKEVEN_PROPS = {k: v for k, v in DECISION_PROPS.items() if k != 'var_trials_sr'}


def _tool_specs() -> list[dict]:
    kb = load_kb()
    families = sorted({s['family'] for s in kb['strategies']})
    categories = [c['key'] for c in kb['categories']]
    return [
        {'name': 'search_strategies', 'command': 'search',
         'description': 'Search the 44 quant strategies of the evidence base by keywords (Spanish or English '
                        'ids work best). Returns id, name, family and the 0-100 evidence rating, best match '
                        'first; without a query, lists the catalog by rating. Use it first to get a '
                        'strategy_id. ' + NOT_ADVICE,
         'inputSchema': _schema({
             'query': {'type': 'string', 'description': 'Keywords, e.g. "momentum", "calendario México".'},
             'family': {'type': 'string', 'enum': families, 'description': 'Optional family filter.'},
             'category': {'type': 'string', 'enum': categories, 'description': 'Optional evidence category filter.'},
             'limit': _int('Maximum results. Default 6.')})},
        {'name': 'get_strategy', 'command': 'strategy',
         'description': 'What the academic literature says about one strategy: claim, key figure, main '
                        'critique, what survives in practice, reliability marks, evidence profile, rating '
                        'and source links. ' + NOT_ADVICE,
         'inputSchema': _schema({'id': STRATEGY_ID}, ('id',))},
        {'name': 'evaluate_decision', 'command': 'evaluate',
         'description': 'Score a proposed investment decision 0-100 against the evidence: verdict, '
                        'sub-scores, net-edge cascade (multiple testing, publication decay, microcaps, '
                        'costs), itemized checks with sources and related repository modules. Pass only '
                        'the data the user gave; the rest uses the strategy defaults. ' + NOT_ADVICE,
         'inputSchema': _schema(DECISION_PROPS, ('strategy_id',))},
        {'name': 'compare_strategies', 'command': 'compare',
         'description': 'Evaluate all 44 strategies with the same profile (horizon, market, investor, no '
                        'backtest) and rank them by score; also returns the rank of a given strategy. '
                        + NOT_ADVICE,
         'inputSchema': _schema({
             'horizon_years': _num('Investment horizon in years. Default 15.'),
             'market': MARKET, 'investor': INVESTOR,
             'strategy_id': {'type': 'string', 'description': 'Optional: strategy whose rank to report.'},
             'top': _int('How many of the best to return. Default 10.')})},
        {'name': 'breakeven_points', 'command': 'breakeven',
         'description': 'For a decision, the round-trip cost (bps) and the monthly turnover (%) at which '
                        'the net edge vanishes. Only applies to strategies with a measurable edge; '
                        'otherwise says so. null = edge survives the tested range, 0 = no edge even '
                        'without costs. ' + NOT_ADVICE,
         'inputSchema': _schema(BREAKEVEN_PROPS, ('strategy_id',))},
        {'name': 'deflated_sharpe', 'command': 'deflated_sharpe',
         'description': 'Deflated Sharpe Ratio (Bailey and Lopez de Prado 2014): probability that the true '
                        'Sharpe is positive after selecting the best of n_trials, with non-normal returns. '
                        + NOT_ADVICE,
         'inputSchema': _schema({
             'sharpe_annual': _num('Annual Sharpe ratio of the selected strategy.'),
             'n_trials': _int('Number of trials compared.'),
             'years': _num('Years of data.'),
             'periods_per_year': _int('Return frequency. Default 252.'),
             'var_trials_sr': _num('Cross-trial variance of annualized Sharpe ratios. Default 1 / years.'),
             'skew': _num('Skewness. Default 0.'),
             'kurtosis': _num('Raw kurtosis (normal = 3). Default 3.')}, ('sharpe_annual', 'n_trials', 'years'))},
        {'name': 'haircut_sharpe', 'command': 'haircut_sharpe',
         'description': 'Harvey-Liu multiple-testing haircut: the Sharpe ratio that survives after adjusting '
                        'the p-value for n_tests. ' + NOT_ADVICE,
         'inputSchema': _schema({
             'sharpe_annual': _num('Annual Sharpe ratio.'),
             'years': _num('Years of data.'),
             'n_tests': _int('Number of tests. Default 1.'),
             'method': {'type': 'string', 'enum': ['bonferroni', 'sidak'],
                        'description': 'Adjustment for the best of n_tests (Holm equals Bonferroni for '
                                       'the top test). Default bonferroni.'}}, ('sharpe_annual', 'years'))},
        {'name': 'min_backtest_length', 'command': 'min_backtest_length',
         'description': 'Minimum backtest length in years for n_trials (Bailey, Borwein, Lopez de Prado and '
                        'Zhu 2014), and/or the maximum trials a backtest of `years` supports. Give n_trials, '
                        'years or both. ' + NOT_ADVICE,
         'inputSchema': _schema({
             'n_trials': _int('Number of configurations tried.'),
             'years': _num('Available years of data.'),
             'target_sharpe': _num('Annual Sharpe to rule out as luck. Default 1.')})},
        {'name': 'cost_drag', 'command': 'cost_drag',
         'description': 'Monthly trading-cost drag in bps from turnover and round-trip cost, the 50% '
                        'turnover rule (Novy-Marx and Velikov) and, with a gross edge, the net edge and '
                        'break-even cost. ' + NOT_ADVICE,
         'inputSchema': _schema({
             'turnover_monthly': _num('Fraction replaced per month, 0.6 = 60%.'),
             'roundtrip_cost_bps': _num('Round-trip cost in bps. Default 40.'),
             'long_short': _bool('Two legs (doubles the cost). Default false.'),
             'gross_monthly_bps': _num('Optional gross edge in bps per month.')}, ('turnover_monthly',))},
        {'name': 'horizon_risk', 'command': 'horizon_risk',
         'description': 'Long-horizon risk: Bodie cost of insuring against underperforming the risk-free '
                        'rate, and the probability of a real loss under a lognormal model. ' + NOT_ADVICE,
         'inputSchema': _schema({
             'sigma_annual': _num('Annual volatility as a fraction. Default 0.2.'),
             'years': _num('Horizon in years. Default 30.'),
             'mu_real_annual': _num('Optional real expected return per year, as a fraction.')})},
        {'name': 'kelly', 'command': 'kelly',
         'description': 'Kelly and fractional Kelly sizing: full Kelly fraction, Merton fraction for a '
                        'risk aversion, growth kept by a fraction of Kelly and the growth rate. ' + NOT_ADVICE,
         'inputSchema': _schema({
             'mu': _num('Expected annual return, fraction (0.08 = 8%).'),
             'r': _num('Risk-free rate, fraction. Default 0.'),
             'sigma': _num('Annual volatility, fraction.'),
             'gamma': _num('Relative risk aversion for the Merton fraction. Default 1.'),
             'kelly_multiple': _num('Fraction of full Kelly. Default 0.5.')}, ('mu', 'sigma'))},
        {'name': 'repo_modules', 'command': 'repo_modules',
         'description': 'FinceptTerminal modules that implement the evidence categories of a strategy '
                        '(up to 12, with summaries) and the known gaps of the repository in those '
                        'categories. ' + NOT_ADVICE,
         'inputSchema': _schema({'strategy_id': STRATEGY_ID}, ('strategy_id',))},
    ]


_SPECS: list[dict] | None = None


def tool_specs() -> list[dict]:
    global _SPECS
    if _SPECS is None:
        _SPECS = _tool_specs()
    return _SPECS


def list_tools() -> list[dict]:
    return [{'name': t['name'], 'description': t['description'], 'inputSchema': t['inputSchema']}
            for t in tool_specs()]


# ── Tool calls ────────────────────────────────────────────────────────────

class ToolError(Exception):
    """An error reported to the model as a tool result with isError."""


def _validate(spec: dict, args: dict) -> None:
    missing = [k for k in spec['inputSchema'].get('required', []) if args.get(k) in (None, '')]
    if missing:
        raise ToolError(f"Missing required argument(s) for {spec['name']}: {', '.join(missing)}.")
    if spec['name'] == 'min_backtest_length' and 'n_trials' not in args and 'years' not in args:
        raise ToolError('min_backtest_length needs n_trials, years or both.')


def _text_result(payload, is_error: bool = False) -> dict:
    text = payload if isinstance(payload, str) else \
        json.dumps(cli._sanitize(payload), ensure_ascii=False, allow_nan=False)
    out = {'content': [{'type': 'text', 'text': text}]}
    if is_error:
        out['isError'] = True
    return out


def call_tool(name: str, args) -> dict:
    """Run one tool. Raises KeyError for an unknown tool; other failures become isError results."""
    spec = next((t for t in tool_specs() if t['name'] == name), None)
    if spec is None:
        raise KeyError(name)
    try:
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ToolError('Tool arguments must be a JSON object.')
        _validate(spec, args)
        return _text_result(cli.COMMANDS[spec['command']](dict(args)))
    except Exception as e:  # noqa: BLE001 - reported to the model, never crashes the server
        _log(f'tool {name} failed: {type(e).__name__}: {e}')
        return _text_result(f'Error in {name}: {e}', is_error=True)


# ── JSON-RPC dispatch ─────────────────────────────────────────────────────

def _error(req_id, code: int, message: str) -> dict:
    return {'jsonrpc': '2.0', 'id': req_id, 'error': {'code': code, 'message': message}}


def _result(req_id, result: dict) -> dict:
    return {'jsonrpc': '2.0', 'id': req_id, 'result': result}


def _initialize(params: dict) -> dict:
    requested = params.get('protocolVersion')
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
    return {'protocolVersion': version,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'title': 'Fincept Quant Evidence', 'version': SERVER_VERSION},
            'instructions': INSTRUCTIONS}


def handle_message(msg) -> dict | None:
    """Answer one decoded JSON-RPC message; None for notifications and responses."""
    if not isinstance(msg, dict) or msg.get('jsonrpc') != '2.0':
        return _error(msg.get('id') if isinstance(msg, dict) else None, INVALID_REQUEST, 'Invalid Request')
    method = msg.get('method')
    is_request = 'id' in msg
    if not isinstance(method, str):
        if is_request and ('result' in msg or 'error' in msg):
            return None  # a response from the client; this server sends no requests
        return _error(msg.get('id'), INVALID_REQUEST, 'Invalid Request') if is_request else None
    if not is_request:
        return None  # notifications/initialized, notifications/cancelled, ...
    req_id = msg['id']
    params = msg.get('params') or {}
    if not isinstance(params, dict):
        return _error(req_id, INVALID_PARAMS, 'params must be an object')
    try:
        if method == 'initialize':
            return _result(req_id, _initialize(params))
        if method == 'ping':
            return _result(req_id, {})
        if method == 'tools/list':
            return _result(req_id, {'tools': list_tools()})
        if method == 'tools/call':
            name = params.get('name')
            if not isinstance(name, str):
                return _error(req_id, INVALID_PARAMS, 'tools/call needs a tool name')
            try:
                return _result(req_id, call_tool(name, params.get('arguments')))
            except KeyError:
                return _error(req_id, INVALID_PARAMS, f'Unknown tool: {name}')
        return _error(req_id, METHOD_NOT_FOUND, f'Method not found: {method}')
    except Exception as e:  # noqa: BLE001
        _log(f'{method} failed: {type(e).__name__}: {e}')
        return _error(req_id, INTERNAL_ERROR, f'Internal error: {e}')


def handle_line(line: bytes | str) -> dict | None:
    if isinstance(line, bytes):
        try:
            line = line.decode('utf-8')
        except UnicodeDecodeError:
            return _error(None, PARSE_ERROR, 'Parse error: not UTF-8')
    if not line.strip():
        return None
    try:
        msg = json.loads(line)
    except ValueError as e:
        return _error(None, PARSE_ERROR, f'Parse error: {e}')
    return handle_message(msg)


def serve(stdin=None, stdout=None) -> None:
    """Read messages line by line until EOF and write one response line per request."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    for line in stdin:
        reply = handle_line(line)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False, allow_nan=False).encode('utf-8') + b'\n')
            stdout.flush()


def main() -> None:
    out = sys.stdout.buffer
    sys.stdout = sys.stderr  # stray prints must never corrupt the protocol stream
    _log(f'ready on stdio (protocol {PROTOCOL_VERSION}, {len(tool_specs())} tools)')
    try:
        serve(sys.stdin.buffer, out)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
