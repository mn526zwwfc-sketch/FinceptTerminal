"""Tests de sesgos del backtester (skill backtesting-frameworks)."""
import math

import pytest

from server import backtest as bt


def candles_from(closes, gap=0.0):
    """Velas diarias; la apertura es el cierre anterior desplazado `gap` (para distinguir open de close)."""
    out = []
    for i, c in enumerate(closes):
        o = (closes[i - 1] if i else c) * (1 + gap)
        out.append({"t": 86400 * i, "o": o, "h": max(o, c), "l": min(o, c), "c": c, "v": 1000})
    return out


def test_signal_executes_at_next_open_never_same_close():
    cs = candles_from([100 + i for i in range(30)], gap=0.01)
    sig = [None] * 30
    sig[10] = 1  # decide comprar con el cierre de la barra 10
    for i in range(11, 30):
        sig[i] = 1
    r = bt.run_signals(cs, sig, 0, costs=bt.CostModel(0, 0))
    buy = r["fills"][0]
    assert buy["i"] == 11 and buy["price"] == pytest.approx(cs[11]["o"])  # apertura de i+1
    assert r["equity"][10] == 10_000  # en la barra de la decisión aún estamos en efectivo


def test_round_trip_costs_on_flat_prices():
    cs = candles_from([100.0] * 20)
    sig = [None] * 20
    sig[5], sig[8] = 1, 0
    for i in (6, 7):
        sig[i] = 1
    c = bt.CostModel(commission_bps=10, slippage_bps=20)
    r = bt.run_signals(cs, sig, 0, costs=c)
    s_, k = 20 / 1e4, 10 / 1e4
    expected = 10_000 * (1 - s_) * (1 - k) / ((1 + s_) * (1 + k))
    assert r["equity"][-1] == pytest.approx(expected)
    assert r["costs_paid"] == pytest.approx(10_000 - expected, rel=1e-9)
    free = bt.run_signals(cs, sig, 0, costs=bt.CostModel(0, 0))
    assert free["equity"][-1] == pytest.approx(10_000)


def test_last_bar_signal_is_not_executed():
    cs = candles_from([100.0] * 10)
    sig = [None] * 9 + [1]
    r = bt.run_signals(cs, sig, 0)
    assert r["fills"] == [] and r["exposure"] == 0


def test_strategy_and_benchmark_are_aligned_and_costed():
    up = [100 + i for i in range(80)]
    down = [180 - 2 * i for i in range(60)]
    r = bt.backtest_sma_cross(candles_from(up + down), fast=5, slow=20, mc_sims=0)
    assert r["round_trips"] == 1 and [t["side"] for t in r["trade_log"]] == ["buy", "sell"]
    curve = r["equity_curve"]
    assert curve[0]["t"] == 86400 * 20  # primera ejecución posible = slow-1 + 1
    assert curve[0]["benchmark"] < 10_000 * (up[20] / up[19])  # el B&H también paga costes de entrada
    assert r["excess_return"] == pytest.approx(r["total_return"] - r["buy_and_hold_return"])
    assert 0 < r["exposure"] < 1 and r["costs_paid"] > 0
    with pytest.raises(ValueError):
        bt.backtest_sma_cross(candles_from(up), fast=30, slow=10)


def test_monte_carlo_is_reproducible_and_ordered():
    eq = [10_000 * math.exp(0.0004 * i + 0.01 * math.sin(i)) for i in range(300)]
    a, b = bt.monte_carlo(eq, 300, seed=1), bt.monte_carlo(eq, 300, seed=1)
    assert a == b
    assert a["return_p5"] <= a["return_p50"] <= a["return_p95"]
    assert 0 <= a["prob_loss"] <= 1 and a["max_drawdown_p5"] <= a["max_drawdown_p50"] <= 0


def _wave(n, seed=0):
    return [100 * math.exp(0.15 * math.sin(i / (25 + seed)) + 0.0003 * i) for i in range(n)]


def test_walk_forward_has_no_future_leakage():
    cs = candles_from(_wave(1100))
    kw = dict(train_bars=300, test_bars=100, fast_grid=[5, 10, 20], slow_grid=[40, 60, 100])
    base = bt.walk_forward_sma(cs, **kw)
    assert len(base["splits"]) == (1100 - 300) // 100
    for a_, b_ in zip(base["splits"], base["splits"][1:]):
        assert a_["test_to"] < b_["test_from"] and a_["train_to"] < a_["test_from"]  # ventanas sin solape
    # Alterar el FUTURO (últimas 250 barras) no puede cambiar las decisiones de ventanas anteriores.
    tampered = candles_from(_wave(850) + [c * 3 for c in _wave(1100)[850:]])
    alt = bt.walk_forward_sma(tampered, **kw)
    for s0, s1 in zip(base["splits"][:5], alt["splits"][:5]):  # splits cuyo test termina antes de la barra 850
        assert (s0["fast"], s0["slow"], s0["oos_return"]) == (s1["fast"], s1["slow"], s1["oos_return"])
    assert 0 <= base["param_stability"] <= 1


def test_holdout_ranking_ignores_holdout_data():
    cs = candles_from(_wave(1000))
    a = bt.optimize_holdout(cs, 0.3, [5, 10, 20], [40, 60, 100])
    tampered = candles_from(_wave(700) + [c * 0.5 for c in _wave(1000)[700:]])
    b = bt.optimize_holdout(tampered, 0.3, [5, 10, 20], [40, 60, 100])
    assert [(r["fast"], r["slow"], r["sharpe"]) for r in a["top10"]] == \
           [(r["fast"], r["slow"], r["sharpe"]) for r in b["top10"]]
    assert all("oos_sharpe" in r for r in a["top10"])


def test_cost_model_validation():
    with pytest.raises(ValueError):
        bt.CostModel(-1, 0)
