# quant_evidence

The literature review "La academia quant desinfla sus propias estrategias" (Modelos quant académicos de inversión, 2026) turned into code. The report itself is not tracked (the repository only tracks README.md files), so every figure in the knowledge base keeps a link to its primary source:

1. **Structured evidence** (`data/evidence_kb.json`): 44 strategies or decisions, from buy-and-hold to LLM news signals. Each one carries the paper's claim, its key figure, the main critique, what survives in practice, the reliability marks (`WP` working paper, `ext.` machine-extracted table, `sec.` secondary source, `1p` from the report's single-pass portfolio section) and links to its sources. They are grouped into 22 evidence categories.
2. **Repository map** (`data/repo_map.json` + `repo_indexer.py`): the FinceptTerminal modules that implement each category, with summaries verified by reading the code, plus the gaps where the repo has nothing comparable to the evidence. There is also a live keyword scan of `fincept-qt/scripts` and `fincept-qt/src`.
3. **Statistics** (`stats.py`, stdlib only): Deflated Sharpe Ratio, Probabilistic Sharpe Ratio, expected maximum Sharpe of N trials, minimum backtest length, Harvey-Liu multiple-testing haircut, cost drag and break-even cost, Bodie shortfall put, Kelly and fractional Kelly, Campbell-Thompson utility gain, and McLean-Pontiff decay.
4. **Decision evaluator** (`evaluator.py`): scores a proposed decision from 0 to 100, with itemized checks and the net-edge cascade.
5. **Web page** (`web/`): *Árbitro Quant*, a self-contained HTML page that runs the same engine in the browser (`engine.js` is a line-by-line port of `stats.py` + `evaluator.py`, and a test keeps the two in parity).

Everything here is educational. It is not personalized financial advice and it makes no market predictions.

## Fincept Quant Studio (app)

`app/` packages everything above, plus the repository source, as a single-page app with two interfaces over the same engine and data.

The default interface (`terminal.html`, *Fincept Quant Terminal*) is a financial-terminal layout. A command line with autocomplete (`MOM <GO>`, `DSR 2.5 100 5`, `CODE stats.py`, `HELP`), function keys and dense panels that can be minimized, maximized, closed and restored. It has six screens:

- **MONITOR**: the decision analyzer with live sensitivity charts (net edge and score against cost, turnover, trials or years), the parameter sheet with the net-edge cascade, the checks wire, and the matrix of the 44 strategies.
- **CABLE**: the evidence wire (every strategy and repository gap as a story) and a reader with claims, critiques and sources.
- **CÓDIGO**: a code explorer grouped by evidence category, plus the new package, with syntax highlighting and a description of each module.
- **REPOSITORIO**: the category matrix (curated modules, keyword-scan hits, strategies, gaps), the 19 gaps and the modules per category.
- **CÁLCULO**: Deflated Sharpe, Harvey-Liu haircut, MinBTL, cost drag, Bodie and Kelly calculators, plus the formulas and score weights.
- **CONSOLA**: the command log, saved decisions and `RUN` (local app only).

The scores and curves are computed by the evaluator; the ticker shows the knowledge base's 0-100 evidence ratings. No market prices or quotes are shown.

`--studio` builds the alternative product-page interface (`template.html`): a configurator with activity rings, strategy cards, the code explorer and the method page. The local server also serves it at `/studio`.

Run it locally (stdlib only; the page then uses the Python engine, can browse every file under `fincept-qt/` and can run the Analytics CLIs `quant_evidence_cli.py`, `quant_analytics_cli.py`, `statsmodels_cli.py` and `financial_analysis_cli.py`):

```bash
cd fincept-qt/scripts/Analytics
python quant_studio.py                 # http://127.0.0.1:8765
python quant_studio.py --port 9000 --no-browser --no-scan
```

The server binds to 127.0.0.1, accepts only localhost `Host` headers and JSON POST bodies, and refuses any path outside `fincept-qt/`. To produce a static copy (page plus `code/<id>.txt` sources) run `python -m quant_evidence.app.build_app [out_dir] [--fragment] [--studio]`; without the local server it runs the JavaScript engine and shows the curated files only.

## Usage

```bash
cd fincept-qt/scripts/Analytics

python quant_evidence_cli.py list
python quant_evidence_cli.py strategies '{"family": "timing"}'
python quant_evidence_cli.py strategy '{"id": "cape_timing"}'
python quant_evidence_cli.py categories            # strategies + repo modules per category
python quant_evidence_cli.py evaluate '{"strategy_id": "momentum", "sharpe_annual": 1.2, "years": 8, "n_trials": 50, "periods_per_year": 12}'
python quant_evidence_cli.py evaluate decision.json   # JSON copied from the web page
python quant_evidence_cli.py deflated_sharpe '{"sharpe_annual": 2.5, "n_trials": 100, "years": 5, "periods_per_year": 250, "var_trials_sr": 0.5, "skew": -3, "kurtosis": 10}'
python quant_evidence_cli.py haircut_sharpe '{"sharpe_annual": 0.75, "years": 20, "n_tests": 200}'
python quant_evidence_cli.py min_backtest_length '{"n_trials": 45, "target_sharpe": 1}'
python quant_evidence_cli.py cost_drag '{"turnover_monthly": 0.6, "roundtrip_cost_bps": 40, "long_short": true, "gross_monthly_bps": 50}'
python quant_evidence_cli.py repo_scan
python quant_evidence_cli.py export_web            # rebuilds web/decision_lab.html
```

Output follows the convention of the other Analytics CLIs: `{"success": true, "data": ...}` or `{"success": false, "error": ...}`.

From Python:

```python
from quant_evidence import evaluate_decision, stats
r = evaluate_decision({"strategy_id": "ipc_calendar", "market": "mx", "sharpe_annual": 0.9, "years": 10, "n_trials": 30})
r["verdict"], r["scores"], r["cascade"], r["checks"]
```

## Evaluator inputs

| Field | Meaning | Default |
|---|---|---|
| `strategy_id` | id from `evidence_kb.json` (required) | |
| `sharpe_annual`, `years` | backtest Sharpe and length; together they enable the statistical block | none |
| `n_trials` | variants, parameters or models compared before choosing this one | 1 |
| `periods_per_year`, `skew`, `kurtosis` | return frequency and shape for the DSR (raw kurtosis, normal = 3) | 252, 0, 3 |
| `var_trials_sr` | cross-trial variance of annualized Sharpe ratios | 1 / years (pure noise) |
| `gross_alpha_monthly_bps` | gross edge; otherwise Sharpe × volatility / 12, otherwise the literature figure | |
| `volatility_annual` | fraction, 0.15 = 15% | 0.15 |
| `turnover_monthly` | fraction of each leg replaced per month | strategy profile |
| `roundtrip_cost_bps` | spread + commission + impact for a sell and buy | 40 retail, 15 institutional, × 1.5 in Mexico |
| `long_short`, `uses_leverage` | needs short sales / leverage | strategy profile |
| `microcap_share` | share of the alpha that comes from microcaps | 0.6 / 0.3 / 0.05 by profile |
| `published`, `out_of_sample`, `live_months` | decay and live track record | true, false, 0 |
| `investor` | `retail` or `institutional` | `retail` |
| `market` | `global`, `us`, `mx`, `other` | `global` |
| `horizon_years`, `kelly_multiple` | context | 10, none |

## Scoring

The final score is a weighted blend: evidence 35%, statistics 25%, implementability 25%, context 15%. Without a backtest the weights are 50 / 30 / 20 and there is no statistics block. The verdict thresholds are 70 (*respaldada*), 50 (*condicionada*), 30 (*débil*) and below that *no respaldada*. A net edge of zero or less caps the score at 29.

The net-edge cascade is: gross → × (haircut Sharpe / Sharpe) → × 0.42 if published (−58%) or × 0.74 if not validated out of sample (−26%) → × (1 − microcap share) → − turnover × round-trip cost × legs. A long-short factor or ML strategy implemented long-only is capped at zero (Chen & Welch).

The displayed score is floored, so it never contradicts the verdict band. A DSR below 0.5, or one that cannot be computed, caps the score at 40.

The weights, thresholds and the `prior.score` of each strategy are a transparent heuristic built on the report's conclusions. They are not a published model. Change them in `evaluator.py` **and** `web/engine.js`; the parity test fails if the two drift apart.

## Updating

- **Add or edit a strategy**: edit `data/evidence_kb.json`. Use only figures from the report or its sources, and keep the reliability marks. Run the tests (they check ids, categories, marks and source URLs).
- **Refresh the repo map**: `data/repo_map.json` is curated (each module was read). For a quick refresh of where each category's vocabulary appears, run `repo_scan`.
- **Rebuild the page**: `python -m quant_evidence.build_web` (or `quant_evidence_cli.py export_web`). The default output is a standalone HTML document; `--fragment` omits the `<!doctype>`/`<html>` wrapper for hosts that add their own (such as a claude.ai artifact).

## Tests

```bash
cd fincept-qt/scripts/Analytics
python -m unittest discover -s quant_evidence/tests -t .
```

The formula tests reproduce the report's worked examples: DSR 0.90 for a Sharpe of 2.5 among 100 trials; a 0.75 Sharpe cut to about 0.32 after 200 tests; 45 trials in 5 years; Bonferroni t of 3.78 for 316 factors; Bodie put costs of 7.98%, 24.84% and 41.61%; half Kelly keeping 75% of growth. If Node.js is installed, the parity test runs `engine.js` against the Python evaluator.
