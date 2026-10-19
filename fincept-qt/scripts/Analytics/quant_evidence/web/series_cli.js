#!/usr/bin/env node
/*
 * Command line for web/series.js: audits a return or price table the way the
 * Laboratorio page does, so agents and scripts get the same numbers.
 *
 *   node series_cli.js <file.csv|-> [--kind auto|prices|returns|percent]
 *                      [--ppy auto|252|52|12|4] [--series best|<index>] [--trials N]
 *
 * Input: a table with an optional date column and one column per strategy
 * variant (comma, semicolon or tab separated). Output: JSON on stdout,
 * {"success": true, "data": {...}} or {"success": false, "error": "..."}.
 * The data holds the summary of the chosen series, PSR, MinTRL, the bootstrap
 * interval of the Sharpe ratio, PBO by CSCV (two or more variants) and the
 * inputs to pass to quant_evidence_cli.py evaluate.
 */
'use strict';

var fs = require('fs');
var path = require('path');
var S = require(path.join(__dirname, 'series.js'));
var E = require(path.join(__dirname, 'engine.js'));

function args(argv) {
  var out = { file: null, kind: 'auto', ppy: 'auto', series: 'best', trials: null };
  for (var i = 0; i < argv.length; i++) {
    var a = argv[i];
    if (a === '--kind') out.kind = argv[++i];
    else if (a === '--ppy') out.ppy = argv[++i];
    else if (a === '--series') out.series = argv[++i];
    else if (a === '--trials') out.trials = Number(argv[++i]);
    else if (!out.file) out.file = a;
    else throw new Error('Argumento no reconocido: ' + a);
  }
  if (!out.file) throw new Error('Uso: node series_cli.js <archivo.csv|-> [--kind ...] [--ppy ...] [--series best|N] [--trials N]');
  if (['auto', 'prices', 'returns', 'percent'].indexOf(out.kind) < 0) throw new Error('--kind debe ser auto, prices, returns o percent.');
  return out;
}

function audit(text, opt) {
  var t = S.parseTable(text);
  var kind = S.detectKind([].concat.apply([], t.columns), opt.kind === 'auto' ? null : opt.kind);
  var cols = t.columns.map(function (c) { return S.toReturns(c, kind); });
  var ppy = opt.ppy && opt.ppy !== 'auto' ? Number(opt.ppy) : (S.inferPeriodsPerYear(t.dates) || 12);
  if (!(ppy > 0)) throw new Error('--ppy debe ser un número positivo.');
  if (cols[0].length < 12) throw new Error('Hacen falta al menos 12 periodos de rendimiento.');
  var sharpes = cols.map(S.sharpe);
  var idx = opt.series === 'best' ? sharpes.indexOf(Math.max.apply(null, sharpes)) : Number(opt.series);
  if (!(idx >= 0 && idx < cols.length)) throw new Error('--series fuera de rango: hay ' + cols.length + ' serie(s).');
  var r = cols[idx], sum = S.summarize(r, ppy);
  var trials = opt.trials > 0 ? Math.floor(opt.trials) : cols.length;
  var mintrl = S.minTrackRecordLength(sum.sharpe_period, 0, sum.skew, sum.kurtosis, 0.05);
  var out = {
    kind: kind, periods_per_year: ppy, series: t.names[idx], series_index: idx, variants: cols.length, skipped_rows: t.skipped,
    summary: sum,
    psr: E.probabilisticSharpeRatio(sum.sharpe_period, 0, sum.n, sum.skew, sum.kurtosis),
    min_track_record_years: isFinite(mintrl) ? mintrl / ppy : null,
    bootstrap_sharpe: S.bootstrapSharpe(r, ppy, { seed: 7 }),
    pbo: null,
    evaluate_inputs: { sharpe_annual: sum.sharpe_annual, years: sum.years, n_trials: trials, periods_per_year: ppy,
      skew: sum.skew, kurtosis: sum.kurtosis, volatility_annual: sum.vol_annual }
  };
  if (cols.length >= 2) {
    var v = S.trialSharpeVariance(cols, ppy).variance;
    if (v > 0) out.evaluate_inputs.var_trials_sr = v;
    try {
      var p = S.pbo(cols);
      delete p.logits;
      out.pbo = p;
    } catch (e) { out.pbo_error = e.message; }
  }
  return out;
}

function finite(o) {
  return JSON.parse(JSON.stringify(o, function (k, v) { return typeof v === 'number' && !isFinite(v) ? null : v; }));
}

if (require.main === module) {
  var res;
  try {
    var opt = args(process.argv.slice(2));
    var text = opt.file === '-' ? fs.readFileSync(0, 'utf8') : fs.readFileSync(opt.file, 'utf8');
    res = { success: true, data: finite(audit(text, opt)) };
  } catch (e) {
    res = { success: false, error: e && e.message ? e.message : String(e) };
  }
  process.stdout.write(JSON.stringify(res) + '\n');
}

module.exports = { audit: audit };
