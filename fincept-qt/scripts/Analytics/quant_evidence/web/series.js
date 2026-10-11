/*
 * quant_evidence series analytics — turns a return series (or a matrix of
 * strategy variants) into the inputs the engine needs, and adds the
 * backtest-overfitting statistics that work on the data itself:
 *
 *   - moments, Sharpe, drawdowns, rolling Sharpe
 *   - Minimum Track Record Length (Bailey & Lopez de Prado 2012)
 *   - stationary-bootstrap interval for the Sharpe ratio (Politis & Romano 1994)
 *   - Probability of Backtest Overfitting by CSCV (Bailey, Borwein,
 *     Lopez de Prado & Zhu 2017)
 *
 * Plain ES5, no dependencies. Runs in the browser (window.QuantSeries) and in
 * Node (module.exports) so tests/test_series.py can check it.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.QuantSeries = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // ── Normal quantile (Acklam), enough for confidence levels ───────────────
  function normPpf(p) {
    if (p <= 0) return -Infinity;
    if (p >= 1) return Infinity;
    var a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    var b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    var c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    var d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    var q, r;
    if (p < 0.02425) {
      q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p > 1 - 0.02425) return -normPpf(1 - p);
    q = p - 0.5; r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  // Deterministic generator so bootstrap results are reproducible.
  function rng(seed) {
    var s = (seed >>> 0) || 1;
    return function () {
      s = (s + 0x6D2B79F5) >>> 0;
      var t = s;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ── Parsing ──────────────────────────────────────────────────────────────
  var DATE_RE = /^(\d{4})[-\/.](\d{1,2})(?:[-\/.](\d{1,2}))?$/;
  var DMY_RE = /^(\d{1,2})[-\/.](\d{1,2})[-\/.](\d{4})$/;
  var NUM_RE = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)([eE][+-]?\d+)?%?$/;

  function parseNumber(s) {
    s = String(s).trim().replace(/\s/g, '');
    if (!NUM_RE.test(s)) return null;
    var pct = s.charAt(s.length - 1) === '%';
    var v = parseFloat(s.replace('%', '').replace(',', '.'));
    if (!isFinite(v)) return null;
    return pct ? v / 100 : v;
  }

  function parseDate(s) {
    s = String(s).trim();
    var m = DATE_RE.exec(s), y, mo, d;
    if (m) { y = +m[1]; mo = +m[2]; d = m[3] ? +m[3] : 28; }
    else {
      m = DMY_RE.exec(s);
      if (!m) return null;
      d = +m[1]; mo = +m[2]; y = +m[3];
    }
    if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
    return Date.UTC(y, mo - 1, d);
  }

  function splitLine(line, sep) {
    return line.split(sep).map(function (c) { return c.trim().replace(/^"|"$/g, ''); });
  }

  /**
   * Reads pasted or uploaded text: one optional date column and one or more
   * numeric columns (one per strategy variant). Separator is detected among
   * tab, semicolon and comma (a comma inside numbers needs ; or tab).
   * Returns {dates: [ms]|null, names: [..], columns: [[..]], skipped}.
   */
  function parseTable(text) {
    var lines = String(text || '').split(/\r?\n/).filter(function (l) { return l.trim() !== ''; });
    if (!lines.length) throw new Error('No hay datos: pega una tabla o sube un archivo CSV.');
    var first = lines[0];
    var sep = first.indexOf('\t') >= 0 ? '\t' : first.indexOf(';') >= 0 ? ';' : first.indexOf(',') >= 0 ? ',' : /\s+/;
    var rows = lines.map(function (l) { return splitLine(l, sep); });
    var width = rows.reduce(function (w, r) { return Math.max(w, r.length); }, 0);
    var header = rows[0].every(function (c, i) { return i === 0 && c === '' ? true : parseNumber(c) === null && parseDate(c) === null; });
    var body = header ? rows.slice(1) : rows;
    // A date column when most rows (over half) start with a date; rows whose date does not parse are skipped.
    var dated = body.filter(function (r) { return parseDate(r[0]) !== null; }).length;
    var hasDate = body.length > 0 && dated > body.length / 2;
    var first0 = hasDate ? 1 : 0;
    var names = [], columns = [], dates = hasDate ? [] : null, skipped = 0, j;
    for (j = first0; j < width; j++) {
      names.push(header && rows[0][j] ? rows[0][j] : 'Serie ' + (j - first0 + 1));
      columns.push([]);
    }
    body.forEach(function (r) {
      var vals = [], ok = true;
      for (var k = first0; k < width; k++) {
        var v = parseNumber(r[k] == null ? '' : r[k]);
        if (v === null) { ok = false; break; }
        vals.push(v);
      }
      var dt = hasDate ? parseDate(r[0]) : 0;
      if (!ok || dt === null) { skipped++; return; }
      if (hasDate) dates.push(dt);
      vals.forEach(function (v, k) { columns[k].push(v); });
    });
    if (!columns.length || columns[0].length < 3) throw new Error('No encontré al menos 3 filas numéricas. Revisa el separador y que no haya texto en las columnas de valores.');
    if (hasDate) {
      // Oldest first.
      var idx = dates.map(function (_, i) { return i; }).sort(function (a, b) { return dates[a] - dates[b]; });
      dates = idx.map(function (i) { return dates[i]; });
      columns = columns.map(function (c) { return idx.map(function (i) { return c[i]; }); });
    }
    return { dates: dates, names: names, columns: columns, skipped: skipped };
  }

  /** Periods per year from the median spacing of the dates. */
  function inferPeriodsPerYear(dates) {
    if (!dates || dates.length < 3) return null;
    var gaps = [];
    for (var i = 1; i < dates.length; i++) gaps.push((dates[i] - dates[i - 1]) / 864e5);
    gaps.sort(function (a, b) { return a - b; });
    var g = gaps[Math.floor(gaps.length / 2)];
    if (g <= 4) return 252;
    if (g <= 10) return 52;
    if (g <= 45) return 12;
    if (g <= 120) return 4;
    return 1;
  }

  /**
   * Prices or returns? Prices are all positive and drift; returns are small
   * and change sign. `mode` forces 'prices', 'returns' or 'percent'.
   */
  function detectKind(values, mode) {
    if (mode === 'prices' || mode === 'returns' || mode === 'percent') return mode;
    var pos = values.every(function (v) { return v > 0; });
    var maxAbs = values.reduce(function (m, v) { return Math.max(m, Math.abs(v)); }, 0);
    if (pos && (maxAbs > 2 || values.length > 3 && values.every(function (v) { return v > 0.5; }))) return 'prices';
    if (maxAbs > 1.5) return 'percent';
    return 'returns';
  }

  function toReturns(values, kind) {
    var out = [], i;
    if (kind === 'prices') {
      for (i = 1; i < values.length; i++) out.push(values[i] / values[i - 1] - 1);
      return out;
    }
    for (i = 0; i < values.length; i++) out.push(kind === 'percent' ? values[i] / 100 : values[i]);
    return out;
  }

  // ── Moments and summary ─────────────────────────────────────────────────
  function moments(r) {
    var n = r.length, mean = 0, i;
    for (i = 0; i < n; i++) mean += r[i];
    mean /= n;
    var m2 = 0, m3 = 0, m4 = 0;
    for (i = 0; i < n; i++) { var d = r[i] - mean, d2 = d * d; m2 += d2; m3 += d2 * d; m4 += d2 * d2; }
    m2 /= n; m3 /= n; m4 /= n;
    var sd = Math.sqrt(m2 * n / Math.max(n - 1, 1));
    return {
      n: n, mean: mean, sd: sd,
      skew: m2 > 0 ? m3 / Math.pow(m2, 1.5) : 0,
      kurtosis: m2 > 0 ? m4 / (m2 * m2) : 3          // raw kurtosis, normal = 3
    };
  }

  function sharpe(r) {
    var m = moments(r);
    return m.sd > 0 ? m.mean / m.sd : 0;
  }

  function drawdowns(r) {
    var eq = [1], peak = 1, dd = [0], maxDd = 0, start = 0, worstStart = 0, worstEnd = 0, i;
    for (i = 0; i < r.length; i++) {
      var v = eq[i] * (1 + r[i]);
      eq.push(v);
      if (v > peak) { peak = v; start = i + 1; }
      var d = v / peak - 1;
      dd.push(d);
      if (d < maxDd) { maxDd = d; worstStart = start; worstEnd = i + 1; }
    }
    return { equity: eq, drawdown: dd, max: maxDd, peakIndex: worstStart, troughIndex: worstEnd };
  }

  function rollingSharpe(r, window, ppy) {
    var out = [], i;
    for (i = 0; i < r.length; i++) {
      if (i + 1 < window) { out.push(null); continue; }
      out.push(sharpe(r.slice(i + 1 - window, i + 1)) * Math.sqrt(ppy));
    }
    return out;
  }

  function summarize(r, ppy) {
    var m = moments(r), dd = drawdowns(r);
    var years = r.length / ppy;
    var growth = dd.equity[dd.equity.length - 1];
    var wins = r.filter(function (x) { return x > 0; }).length;
    var cagr = years > 0 && growth > 0 ? Math.pow(growth, 1 / years) - 1 : null;
    return {
      n: r.length, periods_per_year: ppy, years: years,
      mean_period: m.mean, vol_annual: m.sd * Math.sqrt(ppy),
      sharpe_period: m.sd > 0 ? m.mean / m.sd : 0,
      sharpe_annual: m.sd > 0 ? m.mean / m.sd * Math.sqrt(ppy) : 0,
      skew: m.skew, kurtosis: m.kurtosis,
      cagr: cagr, total_return: growth - 1,
      max_drawdown: dd.max, calmar: cagr !== null && dd.max < 0 ? cagr / -dd.max : null,
      hit_rate: wins / r.length,
      best: Math.max.apply(null, r), worst: Math.min.apply(null, r)
    };
  }

  // ── Minimum Track Record Length (Bailey & Lopez de Prado 2012) ──────────
  /**
   * Observations needed before an observed per-period Sharpe `sr` beats the
   * benchmark `srb` with confidence 1 - alpha, given skew and raw kurtosis.
   * Returns Infinity when sr <= srb.
   */
  function minTrackRecordLength(sr, srb, skew, kurt, alpha) {
    if (!(sr > srb)) return Infinity;
    var z = normPpf(1 - (alpha == null ? 0.05 : alpha));
    var v = 1 - skew * sr + (kurt - 1) / 4 * sr * sr;
    if (v <= 0) return NaN;
    return 1 + v * Math.pow(z / (sr - srb), 2);
  }

  // ── Stationary bootstrap of the annualized Sharpe ratio ──────────────────
  function bootstrapSharpe(r, ppy, opts) {
    opts = opts || {};
    var B = opts.resamples || 2000, n = r.length;
    var block = opts.block || Math.max(1, Math.round(Math.pow(n, 1 / 3)));
    var p = 1 / block, rand = rng(opts.seed || 7), out = new Array(B), b, i;
    var x = new Array(n);
    for (b = 0; b < B; b++) {
      var pos = Math.floor(rand() * n);
      for (i = 0; i < n; i++) {
        if (i > 0 && rand() < p) pos = Math.floor(rand() * n);
        else if (i > 0) pos = (pos + 1) % n;
        x[i] = r[pos];
      }
      out[b] = sharpe(x) * Math.sqrt(ppy);
    }
    out.sort(function (a, c) { return a - c; });
    var q = function (u) { return out[Math.min(B - 1, Math.max(0, Math.floor(u * B)))]; };
    var below = 0;
    for (b = 0; b < B; b++) if (out[b] <= 0) below++;
    return { lo: q(0.025), median: q(0.5), hi: q(0.975), prob_le_zero: below / B, block: block, resamples: B };
  }

  // ── Probability of Backtest Overfitting by CSCV ─────────────────────────
  function combinations(n, k) {
    var out = [], idx = [], i;
    for (i = 0; i < k; i++) idx.push(i);
    while (true) {
      out.push(idx.slice());
      for (i = k - 1; i >= 0 && idx[i] === n - k + i; i--);
      if (i < 0) return out;
      idx[i]++;
      for (var j = i + 1; j < k; j++) idx[j] = idx[j - 1] + 1;
    }
  }

  /**
   * columns: N variant return series of equal length T (N >= 2).
   * Splits the sample into S blocks (even), and for every way of using half
   * the blocks in-sample picks the variant with the best in-sample Sharpe,
   * then looks at its rank out of sample. PBO is the share of splits where
   * that pick lands in the bottom half out of sample.
   */
  function pbo(columns, opts) {
    opts = opts || {};
    var N = columns.length;
    if (N < 2) throw new Error('El PBO necesita al menos 2 variantes (columnas).');
    var T = columns[0].length;
    var S = opts.blocks || 16;
    while (S > 4 && Math.floor(T / S) < 4) S -= 2;
    if (Math.floor(T / S) < 2) throw new Error('Muy pocas observaciones para dividir la muestra: se necesitan al menos ' + (S * 2) + '.');
    var L = Math.floor(T / S), start = T - L * S;     // drop the oldest rows that do not fill a block
    // Per block and variant: count, sum, sum of squares.
    var sum = [], sq = [], s, k, t;
    for (s = 0; s < S; s++) {
      sum.push(new Array(N).fill(0)); sq.push(new Array(N).fill(0));
      for (k = 0; k < N; k++) {
        for (t = start + s * L; t < start + (s + 1) * L; t++) { var v = columns[k][t]; sum[s][k] += v; sq[s][k] += v * v; }
      }
    }
    function sr(blocks, k) {
      var a = 0, b = 0, n = blocks.length * L;
      for (var i = 0; i < blocks.length; i++) { a += sum[blocks[i]][k]; b += sq[blocks[i]][k]; }
      var mean = a / n, varr = (b - n * mean * mean) / Math.max(n - 1, 1);
      return varr > 0 ? mean / Math.sqrt(varr) : 0;
    }
    var combos = combinations(S, S / 2), logits = [], isBest = [], oosBest = [], losses = 0;
    combos.forEach(function (isBlocks) {
      var inIs = {}, oos = [], i;
      isBlocks.forEach(function (b) { inIs[b] = true; });
      for (i = 0; i < S; i++) if (!inIs[i]) oos.push(i);
      var bestK = 0, bestSr = -Infinity, oosSr = [];
      for (k = 0; k < N; k++) {
        var a = sr(isBlocks, k);
        if (a > bestSr) { bestSr = a; bestK = k; }
        oosSr.push(sr(oos, k));
      }
      var pick = oosSr[bestK], below = 0, ties = 0;
      for (k = 0; k < N; k++) { if (oosSr[k] < pick) below++; else if (oosSr[k] === pick && k !== bestK) ties++; }
      var omega = (below + 1 + ties / 2) / (N + 1);       // relative rank in (0, 1)
      logits.push(Math.log(omega / (1 - omega)));
      isBest.push(bestSr); oosBest.push(pick);
      if (pick < 0) losses++;
    });
    var over = logits.filter(function (l) { return l <= 0; }).length;
    // Degradation: OOS Sharpe of the pick regressed on its IS Sharpe.
    var mx = 0, my = 0, i2, n2 = isBest.length;
    for (i2 = 0; i2 < n2; i2++) { mx += isBest[i2]; my += oosBest[i2]; }
    mx /= n2; my /= n2;
    var sxy = 0, sxx = 0;
    for (i2 = 0; i2 < n2; i2++) { sxy += (isBest[i2] - mx) * (oosBest[i2] - my); sxx += (isBest[i2] - mx) * (isBest[i2] - mx); }
    return {
      pbo: over / logits.length, logits: logits, splits: logits.length, blocks: S, block_length: L,
      dropped_rows: start, variants: N,
      prob_oos_loss: losses / n2,
      degradation_slope: sxx > 0 ? sxy / sxx : null,
      is_sharpe_mean: mx, oos_sharpe_mean: my
    };
  }

  /** Cross-variant variance of annualized Sharpe ratios (input for the DSR). */
  function trialSharpeVariance(columns, ppy) {
    var srs = columns.map(function (c) { return sharpe(c) * Math.sqrt(ppy); });
    var m = srs.reduce(function (a, b) { return a + b; }, 0) / srs.length;
    var v = srs.reduce(function (a, b) { return a + (b - m) * (b - m); }, 0) / Math.max(srs.length - 1, 1);
    return { variance: v, sharpes: srs };
  }

  /**
   * A clearly synthetic example: `variants` random strategies that share a
   * market-like drift and common shock, with no variant truly better than
   * another. The best in-sample one looks skilled; PBO shows the choice does
   * not carry out of sample. Monthly, `years` long.
   */
  function simulatedVariants(variants, years, seed) {
    var rand = rng(seed || 2026), T = Math.round(years * 12), cols = [], k, t;
    function gauss() { var u = 0, v = 0; while (u === 0) u = rand(); v = rand(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
    var common = [];
    for (t = 0; t < T; t++) common.push(gauss());
    for (k = 0; k < variants; k++) {
      var col = [];
      for (t = 0; t < T; t++) col.push(0.004 + 0.035 * (0.6 * common[t] + 0.8 * gauss()));
      cols.push(col);
    }
    return cols;
  }

  return {
    normPpf: normPpf, rng: rng, parseNumber: parseNumber, parseDate: parseDate, parseTable: parseTable,
    inferPeriodsPerYear: inferPeriodsPerYear, detectKind: detectKind, toReturns: toReturns,
    moments: moments, sharpe: sharpe, drawdowns: drawdowns, rollingSharpe: rollingSharpe, summarize: summarize,
    minTrackRecordLength: minTrackRecordLength, bootstrapSharpe: bootstrapSharpe,
    combinations: combinations, pbo: pbo, trialSharpeVariance: trialSharpeVariance,
    simulatedVariants: simulatedVariants
  };
});
