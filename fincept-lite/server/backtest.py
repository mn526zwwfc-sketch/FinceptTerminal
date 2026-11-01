"""Motor de backtesting sin sesgos evidentes (aplica la skill backtesting-frameworks).

Reglas que garantiza el motor:

* **Sin look-ahead**: la señal se calcula con el cierre de la barra *i* (solo
  datos hasta *i*) y la orden se ejecuta en la **apertura de la barra i+1**.
  Nunca se opera al mismo precio con el que se decide.
* **Costes realistas**: comisión y slippage (en puntos básicos, por lado);
  el slippage siempre va en contra (compras más caro, vendes más barato).
* **Benchmark alineado**: buy & hold que entra en la misma apertura en que la
  estrategia podía actuar por primera vez, pagando los mismos costes.
* **Fuera de muestra**: la optimización reserva un tramo final que no se toca
  (hold-out) y el walk-forward re-optimiza en ventanas pasadas y evalúa solo
  en la ventana siguiente. Lo que se reporta como rendimiento es el OOS.
* **Incertidumbre**: Monte Carlo por bootstrap de los retornos diarios.

Supuestos que se declaran en la respuesta: un único símbolo (no aplica sesgo de
supervivencia, sí sesgo de selección del símbolo), precios ajustados por
splits pero no por dividendos (Yahoo `close`), largo/fuera, sin apalancamiento.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import asdict, dataclass

PERIODS_PER_YEAR = 252


@dataclass(frozen=True)
class CostModel:
    commission_bps: float = 5.0  # por lado, sobre el nominal
    slippage_bps: float = 5.0  # por lado, adverso

    def __post_init__(self) -> None:
        if not (0 <= self.commission_bps <= 500 and 0 <= self.slippage_bps <= 500):
            raise ValueError("commission_bps and slippage_bps must be between 0 and 500")


ASSUMPTIONS = [
    "Señal al cierre de la barra i, ejecución en la apertura de i+1 (sin look-ahead).",
    "Comisión y slippage por lado; el slippage siempre es adverso.",
    "Un solo símbolo, largo o fuera, sin apalancamiento ni cortos.",
    "Precios ajustados por splits, no por dividendos (rentabilidad de B&H ligeramente infraestimada).",
    "El rendimiento pasado, incluso fuera de muestra, no garantiza resultados futuros.",
]


# ── indicadores y señales ───────────────────────────────────────────────────

def sma(values: list[float], n: int) -> list[float | None]:
    """SMA causal: el valor en i solo usa values[i-n+1..i]."""
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def cross_signals(fast_vals: list[float | None], slow_vals: list[float | None]) -> list[int | None]:
    """1 = quiero estar largo, 0 = fuera, None = aún calentando indicadores."""
    return [None if f is None or s is None else int(f > s) for f, s in zip(fast_vals, slow_vals)]


# ── métricas ────────────────────────────────────────────────────────────────

def perf_metrics(equity: list[float]) -> dict:
    if len(equity) < 2 or equity[0] <= 0:
        raise ValueError("need at least 2 equity points")
    rets = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity))]
    total = equity[-1] / equity[0] - 1
    years = len(rets) / PERIODS_PER_YEAR
    cagr = (equity[-1] / equity[0]) ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else -1.0
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    vol = sd * math.sqrt(PERIODS_PER_YEAR)
    mean_ann = statistics.fmean(rets) * PERIODS_PER_YEAR
    downside = [min(0.0, r) for r in rets]
    dd_dev = math.sqrt(sum(d * d for d in downside) / len(downside)) * math.sqrt(PERIODS_PER_YEAR)
    peak, mdd = equity[0], 0.0
    for e in equity:
        peak = max(peak, e)
        mdd = min(mdd, e / peak - 1)
    return {
        "total_return": total,
        "cagr": cagr,
        "annualized_volatility": vol,
        "sharpe": mean_ann / vol if vol else 0.0,
        "sortino": mean_ann / dd_dev if dd_dev else 0.0,
        "max_drawdown": mdd,
        "calmar": cagr / abs(mdd) if mdd else 0.0,
    }


# ── motor ───────────────────────────────────────────────────────────────────

def run_signals(candles: list[dict], signals: list[int | None], start: int, end: int | None = None,
                initial_cash: float = 10_000.0, costs: CostModel = CostModel()) -> dict:
    """Simula de la barra `start` a `end` (exclusivo). Empieza siempre en efectivo.

    `signals[i]` solo puede depender de datos hasta i; se ejecuta en candles[i+1]["o"].
    """
    end = len(candles) if end is None else end
    comm, slip = costs.commission_bps / 1e4, costs.slippage_bps / 1e4
    cash, units, pending = initial_cash, 0.0, None
    equity, fills, invested_bars, costs_paid = [], [], 0, 0.0
    entry_value = 0.0
    for i in range(start, end):
        bar = candles[i]
        open_px = bar.get("o") or bar["c"]
        if pending == 1 and units == 0:
            px = open_px * (1 + slip)
            units = cash / (px * (1 + comm))
            fee = units * px * comm
            costs_paid += fee + units * (px - open_px)
            entry_value = cash
            cash = 0.0
            fills.append({"t": bar["t"], "i": i, "side": "buy", "price": px})
        elif pending == 0 and units > 0:
            px = open_px * (1 - slip)
            gross = units * px
            fee = gross * comm
            costs_paid += fee + units * (open_px - px)
            cash = gross - fee
            fills.append({"t": bar["t"], "i": i, "side": "sell", "price": px, "pnl_pct": cash / entry_value - 1})
            units = 0.0
        pending = None
        invested_bars += units > 0
        equity.append(cash + units * bar["c"])
        sig = signals[i]
        if sig == 1 and units == 0:
            pending = 1
        elif sig == 0 and units > 0:
            pending = 0
    return {"equity": equity, "fills": fills, "exposure": invested_bars / max(1, len(equity)),
            "costs_paid": costs_paid, "open_position": units > 0}


def buy_and_hold(candles: list[dict], start: int, end: int | None = None, initial_cash: float = 10_000.0,
                 costs: CostModel = CostModel()) -> list[float]:
    """Compra en la apertura de `start` con los mismos costes que la estrategia."""
    end = len(candles) if end is None else end
    px = (candles[start].get("o") or candles[start]["c"]) * (1 + costs.slippage_bps / 1e4)
    units = initial_cash / (px * (1 + costs.commission_bps / 1e4))
    return [units * candles[i]["c"] for i in range(start, end)]


def trade_stats(fills: list[dict]) -> dict:
    closed = [f["pnl_pct"] for f in fills if f["side"] == "sell"]
    wins = [p for p in closed if p > 0]
    losses = [p for p in closed if p <= 0]
    holds = [s["i"] - b["i"] for b, s in zip(fills[::2], fills[1::2])]
    return {
        "round_trips": len(closed),
        "win_rate": len(wins) / len(closed) if closed else None,
        "avg_trade": statistics.fmean(closed) if closed else None,
        "best_trade": max(closed) if closed else None,
        "worst_trade": min(closed) if closed else None,
        "profit_factor": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None,
        "avg_bars_held": statistics.fmean(holds) if holds else None,
    }


def monte_carlo(equity: list[float], n_sims: int = 500, horizon: int = PERIODS_PER_YEAR, seed: int = 7) -> dict:
    """Bootstrap de retornos diarios → distribución de rentabilidad y drawdown a `horizon` barras."""
    rets = [equity[i] / equity[i - 1] - 1 for i in range(1, len(equity))]
    if len(rets) < 20:
        raise ValueError("need at least 20 returns for Monte Carlo")
    rnd = random.Random(seed)  # reproducible
    finals, mdds = [], []
    for _ in range(n_sims):
        e, peak, mdd = 1.0, 1.0, 0.0
        for r in rnd.choices(rets, k=horizon):
            e *= 1 + r
            peak = max(peak, e)
            mdd = min(mdd, e / peak - 1)
        finals.append(e - 1)
        mdds.append(mdd)
    finals.sort()
    mdds.sort()

    def pct(xs: list[float], q: float) -> float:
        return xs[min(len(xs) - 1, max(0, int(q * len(xs))))]

    return {
        "simulations": n_sims, "horizon_bars": horizon, "seed": seed,
        "return_p5": pct(finals, 0.05), "return_p50": pct(finals, 0.50), "return_p95": pct(finals, 0.95),
        "prob_loss": sum(f < 0 for f in finals) / n_sims,
        "max_drawdown_p50": pct(mdds, 0.50), "max_drawdown_p5": pct(mdds, 0.05),
    }


def _downsample(points: list[dict], max_points: int = 400) -> list[dict]:
    step = max(1, math.ceil(len(points) / max_points))
    out = points[::step]
    if out[-1] is not points[-1]:
        out.append(points[-1])
    return out


# ── estrategia SMA ──────────────────────────────────────────────────────────

def backtest_sma_cross(candles: list[dict], fast: int = 20, slow: int = 50, initial_cash: float = 10_000.0,
                       costs: CostModel = CostModel(), mc_sims: int = 500) -> dict:
    if fast < 2 or fast >= slow:
        raise ValueError("need 2 <= fast < slow")
    if len(candles) < slow + 30:
        raise ValueError(f"need at least {slow + 30} candles, got {len(candles)}")
    closes = [c["c"] for c in candles]
    signals = cross_signals(sma(closes, fast), sma(closes, slow))
    start = slow - 1  # primera barra con señal; la primera ejecución posible es start+1
    res = run_signals(candles, signals, start, initial_cash=initial_cash, costs=costs)
    bench = buy_and_hold(candles, start + 1, initial_cash=initial_cash, costs=costs)
    strat_eq = res["equity"][1:]  # alineado con el benchmark desde start+1
    m, bm = perf_metrics([initial_cash] + strat_eq), perf_metrics([initial_cash] + bench)
    curve = [{"t": candles[start + 1 + k]["t"], "equity": e, "benchmark": b}
             for k, (e, b) in enumerate(zip(strat_eq, bench))]
    out = {
        "strategy": f"SMA({fast}/{slow}) crossover",
        "params": {"fast": fast, "slow": slow},
        "costs": asdict(costs),
        "initial_cash": initial_cash,
        "final_equity": strat_eq[-1],
        "bars": len(strat_eq),
        **m,
        "buy_and_hold_return": bm["total_return"],
        "benchmark": bm,
        "excess_return": m["total_return"] - bm["total_return"],
        "exposure": res["exposure"],
        "costs_paid": res["costs_paid"],
        "trades": len(res["fills"]),
        **trade_stats(res["fills"]),
        "equity_curve": _downsample(curve),
        "trade_log": [{k: v for k, v in f.items() if k != "i"} for f in res["fills"][-60:]],
        "assumptions": ASSUMPTIONS,
    }
    if mc_sims:
        out["monte_carlo"] = monte_carlo([initial_cash] + strat_eq, mc_sims)
    return out


DEFAULT_FAST = list(range(5, 55, 5))
DEFAULT_SLOW = list(range(30, 210, 20))


def _grid_eval(candles: list[dict], smas: dict[int, list], start: int, end: int, fast_grid, slow_grid,
               costs: CostModel) -> list[dict]:
    rows = []
    for f in fast_grid:
        for s in slow_grid:
            if f >= s:
                continue
            sig = cross_signals(smas[f], smas[s])
            r = run_signals(candles, sig, max(start, s - 1), end, costs=costs)
            if len(r["equity"]) < 20:
                continue
            m = perf_metrics([10_000.0] + r["equity"])
            rows.append({"fast": f, "slow": s, "sharpe": m["sharpe"], "total_return": m["total_return"],
                         "max_drawdown": m["max_drawdown"], "trades": len(r["fills"])})
    rows.sort(key=lambda x: x["sharpe"], reverse=True)
    return rows


def optimize_holdout(candles: list[dict], holdout: float = 0.3, fast_grid=None, slow_grid=None,
                     costs: CostModel = CostModel()) -> dict:
    """Optimiza en el tramo inicial (in-sample) y evalúa el top-10 en el tramo final reservado."""
    fast_grid, slow_grid = fast_grid or DEFAULT_FAST, slow_grid or DEFAULT_SLOW
    n = len(candles)
    split = int(n * (1 - holdout))
    if split < max(slow_grid) + 60 or n - split < 60:
        raise ValueError("not enough history for an in-sample/hold-out split")
    closes = [c["c"] for c in candles]
    smas = {p: sma(closes, p) for p in set(fast_grid) | set(slow_grid)}
    is_rows = _grid_eval(candles, smas, 0, split, fast_grid, slow_grid, costs)
    top = is_rows[:10]
    for row in top:  # misma configuración, datos nunca vistos durante la optimización
        sig = cross_signals(smas[row["fast"]], smas[row["slow"]])
        r = run_signals(candles, sig, split, costs=costs)
        m = perf_metrics([10_000.0] + r["equity"])
        row.update(oos_sharpe=m["sharpe"], oos_return=m["total_return"], oos_max_drawdown=m["max_drawdown"])
    bench = perf_metrics([10_000.0] + buy_and_hold(candles, split, costs=costs))
    return {
        "method": "in-sample / hold-out",
        "in_sample": {"from": candles[0]["t"], "to": candles[split - 1]["t"], "bars": split},
        "hold_out": {"from": candles[split]["t"], "to": candles[-1]["t"], "bars": n - split,
                     "buy_and_hold_return": bench["total_return"]},
        "tested": len(is_rows),
        "top10": top,
        "warning": "El ranking se hizo SOLO con datos in-sample; juzga cada fila por sus columnas oos_*.",
    }


def walk_forward_sma(candles: list[dict], train_bars: int = 504, test_bars: int = 126, anchored: bool = False,
                     fast_grid=None, slow_grid=None, initial_cash: float = 10_000.0,
                     costs: CostModel = CostModel()) -> dict:
    """Walk-forward: optimiza en [train] y opera con esos parámetros en el [test] siguiente.

    Los indicadores son causales, así que calentarlos con datos anteriores a la
    ventana no introduce información futura.
    """
    fast_grid, slow_grid = fast_grid or DEFAULT_FAST, slow_grid or DEFAULT_SLOW
    n = len(candles)
    if train_bars < max(slow_grid) + 40:
        raise ValueError(f"train_bars must be >= {max(slow_grid) + 40}")
    if n < train_bars + test_bars:
        raise ValueError(f"need at least {train_bars + test_bars} candles, got {n}")
    closes = [c["c"] for c in candles]
    smas = {p: sma(closes, p) for p in set(fast_grid) | set(slow_grid)}
    splits, oos_equity, curve = [], [initial_cash], []
    bench_equity = [initial_cash]
    start = 0
    while start + train_bars + test_bars <= n:
        tr_lo = 0 if anchored else start
        tr_hi = start + train_bars
        te_hi = min(tr_hi + test_bars, n)
        ranked = _grid_eval(candles, smas, tr_lo, tr_hi, fast_grid, slow_grid, costs)
        best = ranked[0]
        sig = cross_signals(smas[best["fast"]], smas[best["slow"]])
        seg = run_signals(candles, sig, tr_hi, te_hi, initial_cash=1.0, costs=costs)  # empieza en efectivo
        bseg = buy_and_hold(candles, tr_hi, te_hi, initial_cash=1.0, costs=costs)
        prev, bprev = oos_equity[-1], bench_equity[-1]
        for k, (e, b) in enumerate(zip(seg["equity"], bseg)):  # encadenar como una cuenta continua
            oos_equity.append(prev * e)
            bench_equity.append(bprev * b)
            curve.append({"t": candles[tr_hi + k]["t"], "equity": prev * e, "benchmark": bprev * b})
        seg_m = perf_metrics([1.0] + seg["equity"])
        splits.append({
            "train_from": candles[tr_lo]["t"], "train_to": candles[tr_hi - 1]["t"],
            "test_from": candles[tr_hi]["t"], "test_to": candles[te_hi - 1]["t"],
            "fast": best["fast"], "slow": best["slow"], "is_sharpe": best["sharpe"],
            "is_return": best["total_return"], "oos_return": seg_m["total_return"], "oos_sharpe": seg_m["sharpe"],
            "oos_trades": len(seg["fills"]), "benchmark_return": bseg[-1] - 1,
        })
        start += test_bars
    oos = perf_metrics(oos_equity)
    bench = perf_metrics(bench_equity)
    is_sharpes = [s["is_sharpe"] for s in splits]
    params = {(s["fast"], s["slow"]) for s in splits}
    return {
        "method": f"walk-forward ({'anclado' if anchored else 'ventana móvil'})",
        "train_bars": train_bars, "test_bars": test_bars, "splits": splits,
        "oos": oos, "benchmark": bench, "excess_return": oos["total_return"] - bench["total_return"],
        # Eficiencia walk-forward: cuánto del Sharpe in-sample sobrevive fuera de muestra.
        "wf_efficiency": (oos["sharpe"] / statistics.fmean(is_sharpes)) if is_sharpes and statistics.fmean(
            is_sharpes) > 0 else None,
        "param_stability": 1 - (len(params) - 1) / max(1, len(splits) - 1) if len(splits) > 1 else 1.0,
        "equity_curve": _downsample(curve),
        "costs": asdict(costs),
        "assumptions": ASSUMPTIONS,
    }
