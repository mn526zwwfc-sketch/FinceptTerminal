/*
 * quant_evidence engine — JavaScript port of stats.py + evaluator.py.
 *
 * Runs in the browser (window.QuantEvidence) and in Node (module.exports) so
 * tests/test_quant_evidence.py can check parity with the Python reference.
 * Keep the two in sync: any change to a formula, weight or threshold in
 * evaluator.py must be mirrored here.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.QuantEvidence = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var EULER_GAMMA = 0.5772156649015329;

  // ── Normal distribution ───────────────────────────────────────────────────
  // CDF: West (2005) double-precision version of Hart's algorithm 5666.
  function normCdf(x) {
    var xa = Math.abs(x), c;
    if (xa > 37) c = 0;
    else {
      var e = Math.exp(-xa * xa / 2), b;
      if (xa < 7.07106781186547) {
        b = 3.52624965998911e-2 * xa + 0.700383064443688;
        b = b * xa + 6.37396220353165;
        b = b * xa + 33.912866078383;
        b = b * xa + 112.079291497871;
        b = b * xa + 221.213596169931;
        b = b * xa + 220.206867912376;
        c = e * b;
        b = 8.83883476483184e-2 * xa + 1.75566716318264;
        b = b * xa + 16.064177579207;
        b = b * xa + 86.7807322029461;
        b = b * xa + 296.564248779674;
        b = b * xa + 637.333633378831;
        b = b * xa + 793.826512519948;
        b = b * xa + 440.413735824752;
        c = c / b;
      } else {
        b = xa + 0.65;
        b = xa + 4 / b;
        b = xa + 3 / b;
        b = xa + 2 / b;
        b = xa + 1 / b;
        c = e / b / 2.506628274631;
      }
    }
    return x > 0 ? 1 - c : c;
  }

  // Inverse CDF: Wichura AS241, same algorithm as Python's statistics module.
  function normPpf(p) {
    if (p <= 0) return -Infinity;
    if (p >= 1) return Infinity;
    var q = p - 0.5, r, num, den, x;
    if (Math.abs(q) <= 0.425) {
      r = 0.180625 - q * q;
      num = (((((((2.5090809287301226727e+3 * r + 3.3430575583588128105e+4) * r +
        6.7265770927008700853e+4) * r + 4.5921953931549871457e+4) * r +
        1.3731693765509461125e+4) * r + 1.9715909503065514427e+3) * r +
        1.3314166789178437745e+2) * r + 3.3871328727963666080e+0) * q;
      den = (((((((5.2264952788528545610e+3 * r + 2.8729085735721942674e+4) * r +
        3.9307895800092710610e+4) * r + 2.1213794301586595867e+4) * r +
        5.3941960214247511077e+3) * r + 6.8718700749205790830e+2) * r +
        4.2313330701600911252e+1) * r + 1.0);
      return num / den;
    }
    r = q <= 0 ? p : 1 - p;
    r = Math.sqrt(-Math.log(r));
    if (r <= 5.0) {
      r = r - 1.6;
      num = (((((((7.74545014278341407640e-4 * r + 2.27238449892691845833e-2) * r +
        2.41780725177450611770e-1) * r + 1.27045825245236838258e+0) * r +
        3.64784832476320460504e+0) * r + 5.76949722146069140550e+0) * r +
        4.63033784615654529590e+0) * r + 1.42343711074968357734e+0);
      den = (((((((1.05075007164441684324e-9 * r + 5.47593808499534494600e-4) * r +
        1.51986665636164571966e-2) * r + 1.48103976427480074590e-1) * r +
        6.89767334985100004550e-1) * r + 1.67638483018380384940e+0) * r +
        2.05319162663775882187e+0) * r + 1.0);
    } else {
      r = r - 5.0;
      num = (((((((2.01033439929228813265e-7 * r + 2.71155556874348757815e-5) * r +
        1.24266094738807843860e-3) * r + 2.65321895265761230930e-2) * r +
        2.96560571828504891230e-1) * r + 1.78482653991729133580e+0) * r +
        5.46378491116411436990e+0) * r + 6.65790464350110377720e+0);
      den = (((((((2.04426310338993978564e-15 * r + 1.42151175831644588870e-7) * r +
        1.84631831751005468180e-5) * r + 7.86869131145613259100e-4) * r +
        1.48753612908506148525e-2) * r + 1.36929880922735805310e-1) * r +
        5.99832206555887937690e-1) * r + 1.0);
    }
    x = num / den;
    return q < 0 ? -x : x;
  }

  // ── stats.py ──────────────────────────────────────────────────────────────
  function expectedMaxSharpeZ(n) {
    n = Math.floor(n);
    if (n <= 1) return 0;
    return (1 - EULER_GAMMA) * normPpf(1 - 1 / n) + EULER_GAMMA * normPpf(1 - 1 / (n * Math.E));
  }

  function minBacktestLength(n, target) {
    if (target <= 0) return Infinity;
    var z = expectedMaxSharpeZ(n) / target;
    return z * z;
  }

  function maxTrialsForLength(years, target) {
    if (years <= 0 || target <= 0) return 1;
    var lo = 1, hi = 2;
    while (minBacktestLength(hi, target) <= years && hi < 1e9) { lo = hi; hi = hi * 2; }
    while (hi - lo > 1) {
      var mid = Math.floor((lo + hi) / 2);
      if (minBacktestLength(mid, target) <= years) lo = mid; else hi = mid;
    }
    return lo;
  }

  function probabilisticSharpeRatio(sr, srb, nObs, skew, kurt) {
    if (nObs < 2) return NaN;
    var v = 1 - skew * sr + (kurt - 1) / 4 * sr * sr;
    if (v <= 0) return NaN;
    return normCdf((sr - srb) * Math.sqrt(nObs - 1) / Math.sqrt(v));
  }

  function deflatedSharpeRatio(srAnnual, nTrials, years, ppy, varTrials, skew, kurt) {
    ppy = ppy || 252;
    skew = skew == null ? 0 : skew;
    kurt = kurt == null ? 3 : kurt;
    var nObs = Math.floor(years * ppy + 0.5);
    if (varTrials == null) varTrials = years > 0 ? 1 / years : 1;
    var em = expectedMaxSharpeZ(nTrials);
    var sr0 = Math.sqrt(Math.max(varTrials, 0)) * em;
    var scale = Math.sqrt(ppy);
    return {
      dsr: probabilisticSharpeRatio(srAnnual / scale, sr0 / scale, nObs, skew, kurt),
      sr0_annual: sr0, sr0_per_period: sr0 / scale, n_obs: nObs,
      var_trials_sr_annual: varTrials, expected_max_z: em
    };
  }

  function sharpeToT(sr, years) { return sr * Math.sqrt(Math.max(years, 0)); }
  function tToPvalue(t) { return 2 * normCdf(-Math.abs(t)); }
  function pvalueToT(p) { return -normPpf(Math.min(Math.max(p, 0), 1) / 2); }

  function adjustPvalue(p, m, method) {
    m = Math.max(Math.floor(m), 1);
    p = Math.min(Math.max(p, 0), 1);
    if (method === 'sidak') return p < 1 ? -Math.expm1(m * Math.log1p(-p)) : 1;
    return Math.min(m * p, 1);
  }

  function haircutSharpe(sr, years, nTests, method) {
    method = method || 'bonferroni';
    var t = sharpeToT(sr, years), p = tToPvalue(t), pa = adjustPvalue(p, nTests, method);
    var ta = pa < 1 ? pvalueToT(pa) : 0;
    if (!isFinite(ta)) ta = Math.abs(t);  // p underflowed: the haircut is negligible
    var sra = years > 0 ? ta / Math.sqrt(years) : 0;
    if (sr < 0) sra = -sra;
    return {
      t_stat: t, p_value: p, p_adjusted: pa, t_adjusted: ta, sharpe_haircut: sra,
      haircut_pct: sr !== 0 ? 1 - sra / sr : 0, passes_t3: Math.abs(t) >= 3, method: method
    };
  }

  function bonferroniTThreshold(n, alpha) {
    return pvalueToT((alpha == null ? 0.05 : alpha) / Math.max(Math.floor(n), 1));
  }

  function monthlyCostBps(turnover, cost, longShort) {
    return Math.max(turnover, 0) * Math.max(cost, 0) * (longShort ? 2 : 1);
  }

  function breakevenRoundtripCostBps(gross, turnover, longShort) {
    if (turnover <= 0) return Infinity;
    return gross / (turnover * (longShort ? 2 : 1));
  }

  function bodieShortfallPutCost(sigma, years) {
    return 2 * normCdf(sigma * Math.sqrt(Math.max(years, 0)) / 2) - 1;
  }

  function probRealLossLognormal(mu, sigma, years) {
    if (years <= 0 || sigma <= 0) return NaN;
    var k = Math.log(1 + Math.pow(sigma / (1 + mu), 2));
    var m = Math.log(1 + mu) - 0.5 * k, s = Math.sqrt(k);
    return normCdf(-(m * years) / (s * Math.sqrt(years)));
  }

  function kellyFraction(mu, r, sigma, gamma) {
    if (sigma <= 0) return mu === r ? 0 : (mu > r ? Infinity : -Infinity);
    return (mu - r) / ((gamma == null ? 1 : gamma) * sigma * sigma);
  }
  function growthRate(f, mu, r, sigma) { return r + f * (mu - r) - 0.5 * f * f * sigma * sigma; }
  function kellyGrowthShare(x) { return 2 * x - x * x; }
  function campbellThompsonGain(r2, s2) { return s2 <= 0 ? Infinity : r2 / s2; }

  var MP_OOS = 0.26, MP_POST = 0.58;

  // ── evaluator.py ──────────────────────────────────────────────────────────
  var WEIGHTS_WITH_STATS = { prior: 0.35, statistical: 0.25, implementability: 0.25, context: 0.15 };
  var WEIGHTS_NO_STATS = { prior: 0.5, implementability: 0.3, context: 0.2 };
  var MICROCAP_ALPHA_SHARE = { alta: 0.6, media: 0.3, baja: 0.05 };
  var DEFAULT_ROUNDTRIP_BPS = { retail: 40, institutional: 15 };
  var MX_COST_MULTIPLIER = 1.5;
  var MARKET_SCORE = { global: 1.0, us: 0.8, other: 0.7, mx: 0.6 };
  var EDGE_FAMILIES = ['factores', 'machine learning', 'timing', 'calendario'];
  var DSR_NAN_TEXT = 'No se puede calcular el DSR: hacen falta al menos 2 observaciones y que la asimetría y la curtosis den una varianza positiva del estimador del Sharpe. Revisa años, frecuencia, asimetría y curtosis.';
  var VERDICTS = [
    [70, 'respaldada', 'Respaldada por la evidencia'],
    [50, 'condicionada', 'Condicionada: depende de supuestos'],
    [30, 'debil', 'Débil'],
    [0, 'no_respaldada', 'No respaldada por la evidencia']
  ];

  var SRC = {
    decay: { label: 'McLean y Pontiff (CFA Digest)', url: 'https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary' },
    dsr: { label: 'Bailey y López de Prado, JPM 2014', url: 'https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf' },
    hl: { label: 'Harvey y Liu, Backtesting (JPM 2015)', url: 'https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF' },
    hlz: { label: 'Harvey, Liu y Zhu, NBER w20592', url: 'https://www.nber.org/system/files/working_papers/w20592/w20592.pdf' },
    minbtl: { label: 'Bailey, Borwein, López de Prado y Zhu 2014', url: 'https://carmamaths.org/resources/jon/backtest.pdf' },
    cost: { label: 'Novy-Marx y Velikov, RFS 2016', url: 'https://ideas.repec.org/a/oup/rfinst/v29y2016i1p104-147..html' },
    microcap: { label: 'Avramov, Cheng y Metzker, MS 2023', url: 'https://si-cheng.net/wp-content/uploads/2023/05/2023-ms-avramov_cheng_metzker-machine-learning-vs.-economic-restrictions.pdf' },
    longOnly: { label: 'Chen y Welch, arXiv 2607.06502 [WP]', url: 'https://arxiv.org/abs/2607.06502' },
    live: { label: 'Arnott, Harvey y Markowitz 2019', url: 'https://people.duke.edu/~charvey/Research/Published_Papers/G138_A_backtesting_protocol.pdf' },
    horizon: { label: "Anarkulova, Cederburg y O'Doherty, JFE 2022", url: 'https://repository.arizona.edu/handle/10150/661101' },
    kelly: { label: 'MacLean, Thorp y Ziemba 2010', url: 'https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf' },
    mx: { label: 'Diaz-Ruiz, Herrerías y Vasquez, NAJEF 2020', url: 'https://ideas.repec.org/a/eee/ecofin/v53y2020ics1062940820300851.html' },
    chenVelikov: { label: 'Chen y Velikov, JFQA 2023', url: 'https://www.cambridge.org/core/services/aop-cambridge-core/content/view/945133D5A3ECEEAF466AEE91551FD225/S0022109022000874a.pdf/zeroing_in_on_the_expected_returns_of_anomalies.pdf' }
  };

  function clamp(x, lo, hi) {
    lo = lo == null ? 0 : lo; hi = hi == null ? 1 : hi;
    if (x !== x) return lo;
    return Math.max(lo, Math.min(hi, x));
  }
  function own(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  // Same coercion rules as evaluator._num / _bool.
  function num(v, d) {
    var dflt = d === undefined ? null : d;
    if (v === null || v === undefined || typeof v === 'object') return dflt;
    if (typeof v === 'string' && v.trim() === '') return dflt;
    var x = Number(v);
    return isFinite(x) ? x : dflt;
  }
  function bool(v, d) {
    if (v === null || v === undefined || v === '') return d;
    if (typeof v === 'string') return ['1', 'true', 'si', 'sí', 'yes', 'y'].indexOf(v.trim().toLowerCase()) >= 0;
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === 'object') return Object.keys(v).length > 0;
    return !!v;
  }
  function fmt(x, nd) { return Number(x).toFixed(nd == null ? 2 : nd); }
  function pct0(x) { return (x * 100).toFixed(0); }
  function check(id, label, status, detail, source) {
    return { id: id, label: label, status: status, detail: detail, source: source || null };
  }
  function getStrategy(kb, id) {
    for (var i = 0; i < kb.strategies.length; i++) if (kb.strategies[i].id === id) return kb.strategies[i];
    return null;
  }

  function resolveInputs(raw, s) {
    var ev = s.evidence;
    var investor = raw.investor || 'retail';
    if (!own(DEFAULT_ROUNDTRIP_BPS, investor)) investor = 'retail';
    var market = raw.market || 'global';
    if (!own(MARKET_SCORE, market)) market = 'other';
    var defCost = DEFAULT_ROUNDTRIP_BPS[investor] * (market === 'mx' ? MX_COST_MULTIPLIER : 1);
    var sharpe = num(raw.sharpe_annual), years = num(raw.years);
    var hasBt = sharpe !== null && years !== null && years > 0;
    var live = num(raw.live_months, 0);
    var mshare = MICROCAP_ALPHA_SHARE[ev.microcap_dependence];
    return {
      strategy_id: s.id,
      has_backtest: hasBt,
      sharpe_annual: hasBt ? sharpe : null,
      years: hasBt ? years : null,
      n_trials: Math.max(Math.trunc(num(raw.n_trials, 1)), 1),
      periods_per_year: Math.max(Math.trunc(num(raw.periods_per_year, 252)), 1),
      skew: num(raw.skew, 0),
      kurtosis: num(raw.kurtosis, 3),
      var_trials_sr: num(raw.var_trials_sr),
      gross_alpha_monthly_bps: num(raw.gross_alpha_monthly_bps),
      volatility_annual: num(raw.volatility_annual, 0.15),
      turnover_monthly: num(raw.turnover_monthly, ev.typical_turnover_monthly || 0),
      roundtrip_cost_bps: num(raw.roundtrip_cost_bps, defCost),
      long_short: bool(raw.long_short, !!ev.requires_short),
      uses_leverage: bool(raw.uses_leverage, !!ev.requires_leverage),
      microcap_share: clamp(num(raw.microcap_share, mshare === undefined ? 0.05 : mshare)),
      published: bool(raw.published, true),
      out_of_sample: bool(raw.out_of_sample, false) || live >= 12,
      live_months: live,
      investor: investor,
      market: market,
      horizon_years: num(raw.horizon_years, 10),
      kelly_multiple: num(raw.kelly_multiple)
    };
  }

  function evaluateDecision(raw, kb, repoMap) {
    var s = getStrategy(kb, raw.strategy_id);
    if (!s) throw new Error('Estrategia desconocida: ' + raw.strategy_id);
    var inp = resolveInputs(raw, s), ev = s.evidence, checks = [];
    var scores = { prior: Number(s.prior.score) };

    var prior = scores.prior;
    checks.push(check('evidence', 'Evidencia académica del tipo de estrategia',
      prior >= 60 ? 'pass' : prior >= 30 ? 'warn' : 'fail',
      s.survives + ' (valoración sintética: ' + Math.trunc(prior) + '/100)',
      s.sources.length ? s.sources[0] : null));

    var st = null;
    if (inp.has_backtest) {
      var sr = inp.sharpe_annual, years = inp.years, n = inp.n_trials;
      var hl = haircutSharpe(sr, years, n);
      var d = deflatedSharpeRatio(sr, n, years, inp.periods_per_year, inp.var_trials_sr, inp.skew, inp.kurtosis);
      var minbtl = sr > 0 ? minBacktestLength(n, sr) : Infinity;
      var maxTr = sr > 0 ? maxTrialsForLength(years, sr) : 1;
      var sDsr = d.dsr === d.dsr ? clamp((d.dsr - 0.5) / 0.45) : 0;
      var sHair = sr > 0 ? clamp(hl.t_adjusted / 1.96) : 0;
      var sLen = isFinite(minbtl) && minbtl > 0 ? clamp(years / minbtl) : (n <= 1 && sr > 0 ? 1 : 0);
      scores.statistical = 100 * (0.4 * sDsr + 0.3 * sHair + 0.3 * sLen);
      st = {
        t_stat: hl.t_stat, p_value: hl.p_value, p_adjusted: hl.p_adjusted, t_adjusted: hl.t_adjusted,
        sharpe_haircut: hl.sharpe_haircut, haircut_pct: hl.haircut_pct,
        dsr: d.dsr, sr0_annual: d.sr0_annual, n_obs: d.n_obs, var_trials_sr_annual: d.var_trials_sr_annual,
        min_backtest_years: minbtl, max_trials_for_length: maxTr,
        bonferroni_t_threshold: bonferroniTThreshold(n)
      };
      checks.push(check('t3', 'Umbral t > 3.0 (Harvey, Liu y Zhu)',
        hl.t_stat >= 3 ? 'pass' : hl.t_stat >= 1.96 ? 'warn' : 'fail',
        't = ' + fmt(hl.t_stat) + ' con ' + n + ' prueba(s); el mejor de ' + n + ' debe superar t = ' +
        fmt(st.bonferroni_t_threshold) + ' (Bonferroni, 5%).', SRC.hlz));
      checks.push(check('haircut', 'Sharpe con recorte por pruebas múltiples',
        sr > 0 && hl.t_adjusted >= 1.96 ? 'pass' : hl.sharpe_haircut > 0 ? 'warn' : 'fail',
        'Sharpe ' + fmt(sr) + ' → ' + fmt(hl.sharpe_haircut) + ' tras ajustar por ' + n +
        ' prueba(s) (recorte de ' + pct0(hl.haircut_pct) + '%).', SRC.hl));
      var dsrOk = d.dsr === d.dsr;
      checks.push(check('dsr', 'Deflated Sharpe Ratio ≥ 0.95',
        !dsrOk ? 'info' : d.dsr >= 0.95 ? 'pass' : d.dsr >= 0.5 ? 'warn' : 'fail',
        !dsrOk ? DSR_NAN_TEXT : 'DSR = ' + fmt(d.dsr, 3) + ': probabilidad de que el Sharpe verdadero sea positivo descontando ' + n +
        ' intento(s), asimetría ' + fmt(inp.skew, 1) + ' y curtosis ' + fmt(inp.kurtosis, 1) +
        '. Sharpe esperable del mejor intento sin habilidad: ' + fmt(d.sr0_annual) + '.', SRC.dsr));
      if (sr > 0) {
        checks.push(check('minbtl', 'Longitud mínima del backtest (MinBTL)',
          years >= minbtl ? 'pass' : 'fail',
          'Con ' + n + ' configuración(es) hacen falta ' + fmt(minbtl, 1) + ' años para un Sharpe de ' + fmt(sr) +
          '; hay ' + fmt(years, 1) + '. Con esa longitud no deberían probarse más de ' + maxTr + ' configuraciones.',
          SRC.minbtl));
      }
    }

    var cascade = [];
    var edge = EDGE_FAMILIES.indexOf(s.family) >= 0 || inp.gross_alpha_monthly_bps !== null || inp.has_backtest;
    var net = null;
    if (edge) {
      var g0 = null, origin = null, g = null;
      if (inp.gross_alpha_monthly_bps !== null) { g0 = inp.gross_alpha_monthly_bps; origin = 'alfa bruta capturada por el usuario'; }
      else if (inp.has_backtest) {
        g0 = inp.sharpe_annual * inp.volatility_annual / 12 * 1e4;
        origin = 'Sharpe ' + fmt(inp.sharpe_annual) + ' × volatilidad ' + pct0(inp.volatility_annual) + '% / 12';
      } else if (ev.net_monthly_bps === null || ev.net_monthly_bps === undefined) {
        if (ev.gross_monthly_bps !== null && ev.gross_monthly_bps !== undefined) {
          g0 = Number(ev.gross_monthly_bps); origin = 'cifra bruta del informe para la familia';
        }
      }
      if (g0 === null && ev.net_monthly_bps !== null && ev.net_monthly_bps !== undefined) {
        g = Number(ev.net_monthly_bps);
        cascade.push({ stage: 'Neto según la literatura', monthly_bps: g, note: 'Cifra neta del informe para la familia (ya descuenta costos).' });
      } else if (g0 !== null) {
        g = g0;
        cascade.push({ stage: 'Bruto', monthly_bps: g, note: origin });
        if (inp.has_backtest && inp.sharpe_annual > 0 && st) {
          var ratio = clamp(st.sharpe_haircut / inp.sharpe_annual);
          g = g * ratio;
          cascade.push({ stage: 'Tras pruebas múltiples', monthly_bps: g, note: '× ' + fmt(ratio) + ' (Sharpe con recorte / Sharpe original)' });
        }
        if (inp.published) {
          g = g * (1 - MP_POST);
          cascade.push({ stage: 'Tras publicación', monthly_bps: g, note: '× 0.42 (−58% después de publicarse)' });
        } else if (!inp.out_of_sample) {
          g = g * (1 - MP_OOS);
          cascade.push({ stage: 'Fuera de muestra', monthly_bps: g, note: '× 0.74 (−26% fuera de muestra)' });
        }
        if (inp.microcap_share > 0) {
          g = g * (1 - inp.microcap_share);
          cascade.push({ stage: 'Sin microcaps', monthly_bps: g, note: '× ' + fmt(1 - inp.microcap_share) + ' (parte del alfa en microcaps, no capturable a costos realistas)' });
        }
        var cost = monthlyCostBps(inp.turnover_monthly, inp.roundtrip_cost_bps, inp.long_short);
        g = g - cost;
        cascade.push({ stage: 'Neto de costos', monthly_bps: g, note: '− ' + fmt(cost, 1) + ' pb: rotación ' + pct0(inp.turnover_monthly) +
          '% × ' + fmt(inp.roundtrip_cost_bps, 0) + ' pb ida y vuelta' + (inp.long_short ? ' × 2 patas' : '') });
      }
      if (g !== null && ev.requires_short && !inp.long_short &&
          (s.family === 'factores' || s.family === 'machine learning') && g > 0) {
        g = 0;
        cascade.push({ stage: 'Versión solo-largo', monthly_bps: g, note: 'Las versiones solo-largo rinden "at most zero net of selection bias" [WP].' });
      }
      net = g;
    }

    var turnover = inp.turnover_monthly;
    var sTurn = turnover <= 0.5 ? 1 : clamp(0.5 / turnover);
    var retail = inp.investor === 'retail';
    var sAccess = clamp(1 - (retail && inp.long_short ? 0.35 : 0) - (retail && inp.uses_leverage ? 0.35 : 0));
    if (net !== null) {
      var sNet = clamp(net / 20);
      scores.implementability = 100 * (0.5 * sNet + 0.25 * sTurn + 0.25 * sAccess);
      checks.push(check('net_edge', 'Ventaja neta esperada',
        net >= 10 ? 'pass' : net > 0 ? 'warn' : 'fail',
        fmt(net, 1) + ' pb mensuales (' + (net * 12 / 100).toFixed(2) + '% anual) tras la cascada. ' +
        'Referencias: la anomalía promedio deja 4 pb y las combinaciones unos 20 pb.', SRC.chenVelikov));
    } else {
      scores.implementability = 100 * (0.5 * sTurn + 0.5 * sAccess);
    }
    checks.push(check('turnover', 'Rotación mensual frente a la frontera de 50%',
      turnover <= 0.5 ? 'pass' : turnover <= 1 ? 'warn' : 'fail',
      'Rotación de ' + pct0(turnover) + '% mensual. Las estrategias con menos de 50% suelen seguir siendo ' +
      'rentables después de costos; las de mayor rotación generalmente no.', SRC.cost));
    if (edge && inp.published) {
      checks.push(check('decay', 'Decaimiento tras la publicación', 'warn',
        'Si la idea viene de un paper, libro o internet, supón que rinde la mitad o menos en adelante ' +
        '(−26% fuera de muestra, −58% tras publicarse).', SRC.decay));
    }
    if (inp.microcap_share >= 0.3) {
      checks.push(check('microcaps', 'Dependencia de acciones diminutas',
        inp.microcap_share >= 0.5 ? 'fail' : 'warn',
        pct0(inp.microcap_share) + '% del alfa vendría de microcaps. En machine learning el alfa cae 48% a 71% ' +
        'al excluirlas; son 60.7% de las acciones y 3.21% de la capitalización.', SRC.microcap));
    }
    if (retail && (inp.long_short || inp.uses_leverage)) {
      var needs = [];
      if (inp.long_short) needs.push('ventas en corto');
      if (inp.uses_leverage) needs.push('apalancamiento');
      checks.push(check('access', 'Acceso de un minorista',
        inp.long_short && inp.uses_leverage ? 'fail' : 'warn',
        'Requiere ' + needs.join(' y ') + '. Los papers modelan costos de un gran fondo, no de una cuenta minorista; ' +
        'el préstamo de títulos es caro justo donde vive la señal.', SRC.longOnly));
    }

    var ctx = [MARKET_SCORE[inp.market]];
    if (inp.market === 'mx') {
      checks.push(check('market_mx', 'Mercado mexicano', 'warn',
        'Con 71 a 130 emisoras los estadísticos t son frágiles; los efectos locales cambian de signo entre ' +
        'muestras y ninguno se ha demostrado neto de costos. Se aplicó un costo 1.5× mayor por defecto.', SRC.mx));
    }
    var h = inp.horizon_years;
    ctx.push(h < 3 ? 0.3 : h < 10 ? 0.7 : 1.0);
    var put = bodieShortfallPutCost(Math.max(inp.volatility_annual, 0), Math.max(h, 0));
    checks.push(check('horizon', 'Horizonte de inversión', h >= 10 ? 'pass' : 'warn',
      'A ' + h.toFixed(0) + ' años, asegurarse contra rendir menos que la tasa libre de riesgo costaría ' +
      (put * 100).toFixed(1) + '% de lo invertido (Bodie, σ = ' + pct0(inp.volatility_annual) + '%). ' +
      'El plazo baja la probabilidad de perder, no el tamaño de la pérdida: 12% de probabilidad de ' +
      'pérdida real a 30 años en 39 países desarrollados.', SRC.horizon));
    if (edge) {
      ctx.push(clamp(inp.live_months / 36));
      checks.push(check('live', 'Historial en vivo',
        inp.live_months >= 36 ? 'pass' : inp.live_months >= 12 ? 'warn' : 'fail',
        inp.live_months.toFixed(0) + ' meses operando en vivo. El único out-of-sample verdadero es operar en vivo.', SRC.live));
    }
    var k = inp.kelly_multiple;
    if (k !== null) {
      ctx.push(k <= 0.5 ? 1 : k <= 1 ? 0.6 : 0);
      checks.push(check('kelly', 'Tamaño de la apuesta', k <= 0.5 ? 'pass' : k <= 1 ? 'warn' : 'fail',
        fmt(k) + '× Kelly conserva ' + (kellyGrowthShare(k) * 100).toFixed(0) + '% del crecimiento máximo; ' +
        'medio Kelly conserva 75% y el doble de Kelly deja el crecimiento en cero.', SRC.kelly));
    }
    scores.context = 100 * ctx.reduce(function (a, b) { return a + b; }, 0) / ctx.length;

    var weights = 'statistical' in scores ? WEIGHTS_WITH_STATS : WEIGHTS_NO_STATS;
    var fin = 0;
    Object.keys(weights).forEach(function (key) { fin += scores[key] * weights[key]; });
    var caps = [];
    if (net !== null && net <= 0) {
      fin = Math.min(fin, 29);
      caps.push('La ventaja neta esperada es nula o negativa: el puntaje se limita a 29.');
    }
    if (st && !(st.dsr >= 0.5)) {
      fin = Math.min(fin, 40);
      caps.push('El Deflated Sharpe Ratio es menor que 0.5 o no se puede calcular: el puntaje se limita a 40.');
    }
    scores.final = fin;
    var v = VERDICTS.filter(function (x) { return fin >= x[0]; })[0];
    var nFail = checks.filter(function (c) { return c.status === 'fail'; }).length;
    var nWarn = checks.filter(function (c) { return c.status === 'warn'; }).length;

    var modules = [];
    if (repoMap && repoMap.modules) {
      repoMap.modules.forEach(function (m) {
        var cs = (m.categories || []).filter(function (c) { return s.categories.indexOf(c) >= 0; });
        if (cs.length) modules.push({ path: m.path, summary: m.summary_es || m.summary || '', categories: cs });
      });
      modules.sort(function (a, b) {
        return (b.categories.length - a.categories.length) || (a.path < b.path ? -1 : a.path > b.path ? 1 : 0);
      });
    }

    return {
      strategy: { id: s.id, name: s.name, family: s.family, categories: s.categories, claim: s.claim,
        key_figure: s.key_figure, critique: s.critique, survives: s.survives, marks: s.marks },
      inputs: inp,
      stats: st,
      cascade: cascade,
      net_monthly_bps: net,
      net_sharpe_estimate: net !== null && inp.volatility_annual > 0 ? net * 12 / 1e4 / inp.volatility_annual : null,
      scores: scores,
      weights: weights,
      caps: caps,
      verdict: { code: v[1], label: v[2], summary: v[2] + ' (' + Math.floor(fin) + '/100). ' + nFail +
        ' chequeo(s) en rojo y ' + nWarn + ' con advertencia. ' + s.survives },
      checks: checks,
      sources: s.sources,
      related_modules: modules.slice(0, 12),
      habits: kb.habits || [],
      disclaimer: kb.meta.disclaimer
    };
  }

  return {
    normCdf: normCdf, normPpf: normPpf,
    expectedMaxSharpeZ: expectedMaxSharpeZ, minBacktestLength: minBacktestLength,
    maxTrialsForLength: maxTrialsForLength, probabilisticSharpeRatio: probabilisticSharpeRatio,
    deflatedSharpeRatio: deflatedSharpeRatio, sharpeToT: sharpeToT, tToPvalue: tToPvalue,
    pvalueToT: pvalueToT, adjustPvalue: adjustPvalue, haircutSharpe: haircutSharpe,
    bonferroniTThreshold: bonferroniTThreshold, monthlyCostBps: monthlyCostBps,
    breakevenRoundtripCostBps: breakevenRoundtripCostBps, bodieShortfallPutCost: bodieShortfallPutCost,
    probRealLossLognormal: probRealLossLognormal, kellyFraction: kellyFraction, growthRate: growthRate,
    kellyGrowthShare: kellyGrowthShare, campbellThompsonGain: campbellThompsonGain,
    resolveInputs: resolveInputs, evaluateDecision: evaluateDecision, getStrategy: getStrategy
  };
});
