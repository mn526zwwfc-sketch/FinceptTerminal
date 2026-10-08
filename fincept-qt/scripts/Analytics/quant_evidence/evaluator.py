"""
Decision effectiveness evaluator.

Combines (1) what the academic evidence says about a strategy family
(data/evidence_kb.json), (2) the statistical credibility of the user's own
backtest (deflated Sharpe, multiple-testing haircut, minimum backtest length),
(3) implementability after decay, microcap dependence and trading costs, and
(4) context (market, horizon, live track record, bet size) into a 0-100 score
with an itemized list of checks, each tied to its source.

The weights and thresholds below are a transparent heuristic built on the
report's conclusions, not a published model. web/engine.js implements the
same function; tests/test_quant_evidence.py checks that both agree.
"""

from __future__ import annotations

import math

from . import stats
from .knowledge_base import load_kb, load_repo_map, get_strategy

WEIGHTS_WITH_STATS = {'prior': 0.35, 'statistical': 0.25, 'implementability': 0.25, 'context': 0.15}
WEIGHTS_NO_STATS = {'prior': 0.50, 'implementability': 0.30, 'context': 0.20}

MICROCAP_ALPHA_SHARE = {'alta': 0.6, 'media': 0.3, 'baja': 0.05}
DEFAULT_ROUNDTRIP_BPS = {'retail': 40.0, 'institutional': 15.0}
MX_COST_MULTIPLIER = 1.5
MARKET_SCORE = {'global': 1.0, 'us': 0.8, 'other': 0.7, 'mx': 0.6}
EDGE_FAMILIES = ('factores', 'machine learning', 'timing', 'calendario')

DSR_NAN_TEXT = ('No se puede calcular el DSR: hacen falta al menos 2 observaciones y que la asimetría y la '
                'curtosis den una varianza positiva del estimador del Sharpe. Revisa años, frecuencia, '
                'asimetría y curtosis.')

VERDICTS = [
    (70, 'respaldada', 'Respaldada por la evidencia'),
    (50, 'condicionada', 'Condicionada: depende de supuestos'),
    (30, 'debil', 'Débil'),
    (0, 'no_respaldada', 'No respaldada por la evidencia'),
]

DECAY_SOURCE = {'label': 'McLean y Pontiff (CFA Digest)',
                'url': 'https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary'}
DSR_SOURCE = {'label': 'Bailey y López de Prado, JPM 2014',
              'url': 'https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf'}
HL_SOURCE = {'label': 'Harvey y Liu, Backtesting (JPM 2015)',
             'url': 'https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF'}
HLZ_SOURCE = {'label': 'Harvey, Liu y Zhu, NBER w20592',
              'url': 'https://www.nber.org/system/files/working_papers/w20592/w20592.pdf'}
MINBTL_SOURCE = {'label': 'Bailey, Borwein, López de Prado y Zhu 2014',
                 'url': 'https://carmamaths.org/resources/jon/backtest.pdf'}
COST_SOURCE = {'label': 'Novy-Marx y Velikov, RFS 2016',
               'url': 'https://ideas.repec.org/a/oup/rfinst/v29y2016i1p104-147..html'}
MICROCAP_SOURCE = {'label': 'Avramov, Cheng y Metzker, MS 2023',
                   'url': 'https://si-cheng.net/wp-content/uploads/2023/05/2023-ms-avramov_cheng_metzker-machine-learning-vs.-economic-restrictions.pdf'}
LONG_ONLY_SOURCE = {'label': 'Chen y Welch, arXiv 2607.06502 [WP]', 'url': 'https://arxiv.org/abs/2607.06502'}
LIVE_SOURCE = {'label': 'Arnott, Harvey y Markowitz 2019',
               'url': 'https://people.duke.edu/~charvey/Research/Published_Papers/G138_A_backtesting_protocol.pdf'}
HORIZON_SOURCE = {'label': 'Anarkulova, Cederburg y O\'Doherty, JFE 2022',
                  'url': 'https://repository.arizona.edu/handle/10150/661101'}
KELLY_SOURCE = {'label': 'MacLean, Thorp y Ziemba 2010',
                'url': 'https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf'}
MX_SOURCE = {'label': 'Diaz-Ruiz, Herrerías y Vasquez, NAJEF 2020',
             'url': 'https://ideas.repec.org/a/eee/ecofin/v53y2020ics1062940820300851.html'}


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x != x:  # NaN
        return lo
    return max(lo, min(hi, x))


def _num(value, default=None):
    if value is None or value == '':
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _bool(value, default: bool) -> bool:
    if value is None or value == '':
        return default
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'si', 'sí', 'yes', 'y')
    return bool(value)


def resolve_inputs(raw: dict, strategy: dict) -> dict:
    """Fill missing inputs from the strategy's evidence profile."""
    ev = strategy['evidence']
    investor = raw.get('investor') or 'retail'
    if investor not in DEFAULT_ROUNDTRIP_BPS:
        investor = 'retail'
    market = raw.get('market') or 'global'
    if market not in MARKET_SCORE:
        market = 'other'
    default_cost = DEFAULT_ROUNDTRIP_BPS[investor] * (MX_COST_MULTIPLIER if market == 'mx' else 1.0)
    sharpe = _num(raw.get('sharpe_annual'))
    years = _num(raw.get('years'))
    has_backtest = sharpe is not None and years is not None and years > 0
    live_months = _num(raw.get('live_months'), 0.0)
    return {
        'strategy_id': strategy['id'],
        'has_backtest': has_backtest,
        'sharpe_annual': sharpe if has_backtest else None,
        'years': years if has_backtest else None,
        'n_trials': max(int(_num(raw.get('n_trials'), 1)), 1),
        'periods_per_year': max(int(_num(raw.get('periods_per_year'), 252)), 1),
        'skew': _num(raw.get('skew'), 0.0),
        'kurtosis': _num(raw.get('kurtosis'), 3.0),
        'var_trials_sr': _num(raw.get('var_trials_sr')),
        'gross_alpha_monthly_bps': _num(raw.get('gross_alpha_monthly_bps')),
        'volatility_annual': _num(raw.get('volatility_annual'), 0.15),
        'turnover_monthly': _num(raw.get('turnover_monthly'), ev.get('typical_turnover_monthly') or 0.0),
        'roundtrip_cost_bps': _num(raw.get('roundtrip_cost_bps'), default_cost),
        'long_short': _bool(raw.get('long_short'), bool(ev.get('requires_short'))),
        'uses_leverage': _bool(raw.get('uses_leverage'), bool(ev.get('requires_leverage'))),
        'microcap_share': _clamp(_num(raw.get('microcap_share'),
                                      MICROCAP_ALPHA_SHARE.get(ev.get('microcap_dependence'), 0.05))),
        'published': _bool(raw.get('published'), True),
        'out_of_sample': _bool(raw.get('out_of_sample'), False) or live_months >= 12,
        'live_months': live_months,
        'investor': investor,
        'market': market,
        'horizon_years': _num(raw.get('horizon_years'), 10.0),
        'kelly_multiple': _num(raw.get('kelly_multiple')),
    }


def _check(cid, label, status, detail, source=None):
    return {'id': cid, 'label': label, 'status': status, 'detail': detail, 'source': source}


def _fmt(x, nd=2):
    return f'{x:.{nd}f}'


def evaluate_decision(raw: dict, kb: dict | None = None, repo_map: dict | None = None) -> dict:
    kb = kb or load_kb()
    strategy = get_strategy(raw.get('strategy_id'), kb)
    if strategy is None:
        raise ValueError(f"Estrategia desconocida: {raw.get('strategy_id')!r}")
    if repo_map is None:
        repo_map = load_repo_map()
    inp = resolve_inputs(raw, strategy)
    ev = strategy['evidence']
    checks = []
    scores = {'prior': float(strategy['prior']['score'])}

    # 1. Evidence prior ------------------------------------------------------
    prior = scores['prior']
    checks.append(_check(
        'evidence', 'Evidencia académica del tipo de estrategia',
        'pass' if prior >= 60 else 'warn' if prior >= 30 else 'fail',
        f"{strategy['survives']} (valoración sintética: {int(prior)}/100)",
        strategy['sources'][0] if strategy['sources'] else None))

    # 2. Statistical credibility ----------------------------------------------
    stat_block = None
    if inp['has_backtest']:
        sr, years, n = inp['sharpe_annual'], inp['years'], inp['n_trials']
        hl = stats.haircut_sharpe(sr, years, n)
        dsr = stats.deflated_sharpe_ratio(sr, n, years, inp['periods_per_year'],
                                          inp['var_trials_sr'], inp['skew'], inp['kurtosis'])
        minbtl = stats.min_backtest_length(n, sr) if sr > 0 else math.inf
        max_trials = stats.max_trials_for_length(years, sr) if sr > 0 else 1
        dsr_ok = dsr['dsr'] == dsr['dsr']  # False when NaN
        s_dsr = _clamp((dsr['dsr'] - 0.5) / 0.45) if dsr_ok else 0.0
        s_hair = _clamp(hl['t_adjusted'] / 1.96) if sr > 0 else 0.0
        s_len = _clamp(years / minbtl) if math.isfinite(minbtl) and minbtl > 0 else (1.0 if n <= 1 and sr > 0 else 0.0)
        scores['statistical'] = 100.0 * (0.4 * s_dsr + 0.3 * s_hair + 0.3 * s_len)
        stat_block = {
            't_stat': hl['t_stat'], 'p_value': hl['p_value'],
            'p_adjusted': hl['p_adjusted'], 't_adjusted': hl['t_adjusted'],
            'sharpe_haircut': hl['sharpe_haircut'], 'haircut_pct': hl['haircut_pct'],
            'dsr': dsr['dsr'], 'sr0_annual': dsr['sr0_annual'], 'n_obs': dsr['n_obs'],
            'var_trials_sr_annual': dsr['var_trials_sr_annual'],
            'min_backtest_years': minbtl, 'max_trials_for_length': max_trials,
            'bonferroni_t_threshold': stats.bonferroni_t_threshold(n),
        }
        checks.append(_check(
            't3', 'Umbral t > 3.0 (Harvey, Liu y Zhu)',
            'pass' if hl['t_stat'] >= 3.0 else 'warn' if hl['t_stat'] >= 1.96 else 'fail',
            f"t = {_fmt(hl['t_stat'])} con {n} prueba(s); el mejor de {n} debe superar t = "
            f"{_fmt(stat_block['bonferroni_t_threshold'])} (Bonferroni, 5%).", HLZ_SOURCE))
        checks.append(_check(
            'haircut', 'Sharpe con recorte por pruebas múltiples',
            'pass' if sr > 0 and hl['t_adjusted'] >= 1.96 else 'warn' if hl['sharpe_haircut'] > 0 else 'fail',
            f"Sharpe {_fmt(sr)} → {_fmt(hl['sharpe_haircut'])} tras ajustar por {n} prueba(s) "
            f"(recorte de {hl['haircut_pct'] * 100:.0f}%).", HL_SOURCE))
        checks.append(_check(
            'dsr', 'Deflated Sharpe Ratio ≥ 0.95',
            'info' if not dsr_ok else 'pass' if dsr['dsr'] >= 0.95 else 'warn' if dsr['dsr'] >= 0.5 else 'fail',
            DSR_NAN_TEXT if not dsr_ok else
            f"DSR = {_fmt(dsr['dsr'], 3)}: probabilidad de que el Sharpe verdadero sea positivo "
            f"descontando {n} intento(s), asimetría {_fmt(inp['skew'], 1)} y curtosis "
            f"{_fmt(inp['kurtosis'], 1)}. Sharpe esperable del mejor intento sin habilidad: "
            f"{_fmt(dsr['sr0_annual'])}.", DSR_SOURCE))
        if sr > 0:
            checks.append(_check(
                'minbtl', 'Longitud mínima del backtest (MinBTL)',
                'pass' if years >= minbtl else 'fail',
                f"Con {n} configuración(es) hacen falta {_fmt(minbtl, 1)} años para un Sharpe de "
                f"{_fmt(sr)}; hay {_fmt(years, 1)}. Con esa longitud no deberían probarse más de "
                f"{max_trials} configuraciones.", MINBTL_SOURCE))

    # 3. Implementability: net edge cascade ----------------------------------
    cascade = []
    edge_strategy = strategy['family'] in EDGE_FAMILIES or inp['gross_alpha_monthly_bps'] is not None \
        or inp['has_backtest']
    net_monthly = None
    if edge_strategy:
        if inp['gross_alpha_monthly_bps'] is not None:
            g0, origin = inp['gross_alpha_monthly_bps'], 'alfa bruta capturada por el usuario'
        elif inp['has_backtest']:
            g0 = inp['sharpe_annual'] * inp['volatility_annual'] / 12.0 * 1e4
            origin = f"Sharpe {_fmt(inp['sharpe_annual'])} × volatilidad {inp['volatility_annual'] * 100:.0f}% / 12"
        elif ev.get('net_monthly_bps') is not None:
            g0, origin = None, None
        elif ev.get('gross_monthly_bps') is not None:
            g0, origin = float(ev['gross_monthly_bps']), 'cifra bruta del informe para la familia'
        else:
            g0, origin = None, None

        if g0 is None and ev.get('net_monthly_bps') is not None:
            g = float(ev['net_monthly_bps'])
            cascade.append({'stage': 'Neto según la literatura', 'monthly_bps': g,
                            'note': 'Cifra neta del informe para la familia (ya descuenta costos).'})
        elif g0 is not None:
            g = g0
            cascade.append({'stage': 'Bruto', 'monthly_bps': g, 'note': origin})
            if inp['has_backtest'] and inp['sharpe_annual'] > 0 and stat_block is not None:
                ratio = _clamp(stat_block['sharpe_haircut'] / inp['sharpe_annual'])
                g = g * ratio
                cascade.append({'stage': 'Tras pruebas múltiples', 'monthly_bps': g,
                                'note': f"× {_fmt(ratio)} (Sharpe con recorte / Sharpe original)"})
            if inp['published']:
                g = g * (1.0 - stats.MCLEAN_PONTIFF_POST_PUB_DECAY)
                cascade.append({'stage': 'Tras publicación', 'monthly_bps': g,
                                'note': '× 0.42 (−58% después de publicarse)'})
            elif not inp['out_of_sample']:
                g = g * (1.0 - stats.MCLEAN_PONTIFF_OOS_DECAY)
                cascade.append({'stage': 'Fuera de muestra', 'monthly_bps': g,
                                'note': '× 0.74 (−26% fuera de muestra)'})
            if inp['microcap_share'] > 0:
                g = g * (1.0 - inp['microcap_share'])
                cascade.append({'stage': 'Sin microcaps', 'monthly_bps': g,
                                'note': f"× {_fmt(1 - inp['microcap_share'])} (parte del alfa en microcaps, no capturable a costos realistas)"})
            cost = stats.monthly_cost_bps(inp['turnover_monthly'], inp['roundtrip_cost_bps'], inp['long_short'])
            g = g - cost
            cascade.append({'stage': 'Neto de costos', 'monthly_bps': g,
                            'note': f"− {_fmt(cost, 1)} pb: rotación {inp['turnover_monthly'] * 100:.0f}% × "
                                    f"{_fmt(inp['roundtrip_cost_bps'], 0)} pb ida y vuelta"
                                    f"{' × 2 patas' if inp['long_short'] else ''}"})
        else:
            g = None

        if g is not None and ev.get('requires_short') and not inp['long_short'] \
                and strategy['family'] in ('factores', 'machine learning') and g > 0:
            g = 0.0
            cascade.append({'stage': 'Versión solo-largo', 'monthly_bps': g,
                            'note': 'Las versiones solo-largo rinden "at most zero net of selection bias" [WP].'})
        net_monthly = g

    turnover = inp['turnover_monthly']
    s_turn = 1.0 if turnover <= 0.5 else _clamp(0.5 / turnover)
    retail = inp['investor'] == 'retail'
    s_access = _clamp(1.0 - (0.35 if retail and inp['long_short'] else 0.0)
                      - (0.35 if retail and inp['uses_leverage'] else 0.0))
    if net_monthly is not None:
        s_net = _clamp(net_monthly / 20.0)
        scores['implementability'] = 100.0 * (0.5 * s_net + 0.25 * s_turn + 0.25 * s_access)
        checks.append(_check(
            'net_edge', 'Ventaja neta esperada',
            'pass' if net_monthly >= 10 else 'warn' if net_monthly > 0 else 'fail',
            f"{_fmt(net_monthly, 1)} pb mensuales ({net_monthly * 12 / 100:.2f}% anual) tras la cascada. "
            "Referencias: la anomalía promedio deja 4 pb y las combinaciones unos 20 pb.",
            {'label': 'Chen y Velikov, JFQA 2023',
             'url': 'https://www.cambridge.org/core/services/aop-cambridge-core/content/view/945133D5A3ECEEAF466AEE91551FD225/S0022109022000874a.pdf/zeroing_in_on_the_expected_returns_of_anomalies.pdf'}))
    else:
        scores['implementability'] = 100.0 * (0.5 * s_turn + 0.5 * s_access)

    checks.append(_check(
        'turnover', 'Rotación mensual frente a la frontera de 50%',
        'pass' if turnover <= 0.5 else 'warn' if turnover <= 1.0 else 'fail',
        f"Rotación de {turnover * 100:.0f}% mensual. Las estrategias con menos de 50% suelen seguir "
        "siendo rentables después de costos; las de mayor rotación generalmente no.", COST_SOURCE))
    if edge_strategy and inp['published']:
        checks.append(_check(
            'decay', 'Decaimiento tras la publicación',
            'warn', 'Si la idea viene de un paper, libro o internet, supón que rinde la mitad o menos '
            'en adelante (−26% fuera de muestra, −58% tras publicarse).', DECAY_SOURCE))
    if inp['microcap_share'] >= 0.3:
        checks.append(_check(
            'microcaps', 'Dependencia de acciones diminutas',
            'fail' if inp['microcap_share'] >= 0.5 else 'warn',
            f"{inp['microcap_share'] * 100:.0f}% del alfa vendría de microcaps. En machine learning "
            "el alfa cae 48% a 71% al excluirlas; son 60.7% de las acciones y 3.21% de la capitalización.",
            MICROCAP_SOURCE))
    if retail and (inp['long_short'] or inp['uses_leverage']):
        needs = ' y '.join(x for x, f in (('ventas en corto', inp['long_short']),
                                           ('apalancamiento', inp['uses_leverage'])) if f)
        checks.append(_check(
            'access', 'Acceso de un minorista',
            'fail' if inp['long_short'] and inp['uses_leverage'] else 'warn',
            f"Requiere {needs}. Los papers modelan costos de un gran fondo, no de una cuenta minorista; "
            "el préstamo de títulos es caro justo donde vive la señal.", LONG_ONLY_SOURCE))

    # 4. Context ---------------------------------------------------------------
    ctx = [MARKET_SCORE[inp['market']]]
    if inp['market'] == 'mx':
        checks.append(_check(
            'market_mx', 'Mercado mexicano',
            'warn',
            'Con 71 a 130 emisoras los estadísticos t son frágiles; los efectos locales cambian de signo '
            'entre muestras y ninguno se ha demostrado neto de costos. Se aplicó un costo 1.5× mayor por defecto.',
            MX_SOURCE))
    h = inp['horizon_years']
    ctx.append(0.3 if h < 3 else 0.7 if h < 10 else 1.0)
    put_cost = stats.bodie_shortfall_put_cost(max(inp['volatility_annual'], 0.0), max(h, 0.0))
    checks.append(_check(
        'horizon', 'Horizonte de inversión',
        'pass' if h >= 10 else 'warn',
        f"A {h:.0f} años, asegurarse contra rendir menos que la tasa libre de riesgo costaría "
        f"{put_cost * 100:.1f}% de lo invertido (Bodie, σ = {inp['volatility_annual'] * 100:.0f}%). "
        "El plazo baja la probabilidad de perder, no el tamaño de la pérdida: 12% de probabilidad de "
        "pérdida real a 30 años en 39 países desarrollados.", HORIZON_SOURCE))
    if edge_strategy:
        ctx.append(_clamp(inp['live_months'] / 36.0))
        checks.append(_check(
            'live', 'Historial en vivo',
            'pass' if inp['live_months'] >= 36 else 'warn' if inp['live_months'] >= 12 else 'fail',
            f"{inp['live_months']:.0f} meses operando en vivo. El único out-of-sample verdadero es operar en vivo.",
            LIVE_SOURCE))
    k = inp['kelly_multiple']
    if k is not None:
        ctx.append(1.0 if k <= 0.5 else 0.6 if k <= 1.0 else 0.0)
        checks.append(_check(
            'kelly', 'Tamaño de la apuesta',
            'pass' if k <= 0.5 else 'warn' if k <= 1.0 else 'fail',
            f"{_fmt(k)}× Kelly conserva {stats.kelly_growth_share(k) * 100:.0f}% del crecimiento máximo; "
            "medio Kelly conserva 75% y el doble de Kelly deja el crecimiento en cero.", KELLY_SOURCE))
    scores['context'] = 100.0 * sum(ctx) / len(ctx)

    # 5. Aggregate -------------------------------------------------------------
    weights = WEIGHTS_WITH_STATS if 'statistical' in scores else WEIGHTS_NO_STATS
    final = sum(scores[k2] * w for k2, w in weights.items())
    caps = []
    if net_monthly is not None and net_monthly <= 0:
        final = min(final, 29.0)
        caps.append('La ventaja neta esperada es nula o negativa: el puntaje se limita a 29.')
    if stat_block is not None and not (stat_block['dsr'] >= 0.5):  # also catches NaN
        final = min(final, 40.0)
        caps.append('El Deflated Sharpe Ratio es menor que 0.5 o no se puede calcular: el puntaje se limita a 40.')
    scores['final'] = final

    code, label = next((c, lbl) for th, c, lbl in VERDICTS if final >= th)
    n_fail = sum(1 for c in checks if c['status'] == 'fail')
    n_warn = sum(1 for c in checks if c['status'] == 'warn')
    summary = (f"{label} ({math.floor(final)}/100). {n_fail} chequeo(s) en rojo y {n_warn} con advertencia. "
               f"{strategy['survives']}")

    modules = []
    if repo_map:
        cats = set(strategy['categories'])
        for m in repo_map.get('modules', []):
            if cats.intersection(m.get('categories', [])):
                modules.append({'path': m['path'], 'summary': m.get('summary_es') or m.get('summary', ''),
                                'categories': [c for c in m.get('categories', []) if c in cats]})
        modules.sort(key=lambda m: (-len(m['categories']), m['path']))

    return {
        'strategy': {k3: strategy[k3] for k3 in ('id', 'name', 'family', 'categories', 'claim',
                                                  'key_figure', 'critique', 'survives', 'marks')},
        'inputs': inp,
        'stats': stat_block,
        'cascade': cascade,
        'net_monthly_bps': net_monthly,
        'net_sharpe_estimate': (net_monthly * 12 / 1e4 / inp['volatility_annual'])
        if net_monthly is not None and inp['volatility_annual'] > 0 else None,
        'scores': scores,
        'weights': weights,
        'caps': caps,
        'verdict': {'code': code, 'label': label, 'summary': summary},
        'checks': checks,
        'sources': strategy['sources'],
        'related_modules': modules[:12],
        'habits': kb.get('habits', []),
        'disclaimer': kb['meta']['disclaimer'],
    }
