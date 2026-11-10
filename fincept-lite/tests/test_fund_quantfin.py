"""Integración de la librería quantfin (quant-finance-research) en el fondo y en las tools."""
import numpy as np
import pytest

from quantfin import avanzados as qa
from server.fund import agents as A

P = A.RiskPolicy()


def test_our_deflated_sharpe_matches_quantfin():
    r = np.random.default_rng(3).normal(0.0006, 0.01, 1000)
    trials = [0.01, 0.06, 0.03, 0.045, 0.02]
    ours = A.deflated_sharpe(list(r), trials)
    theirs = qa.deflated_sharpe(r, len(trials), float(np.var(trials)))
    assert ours == pytest.approx(float(theirs), abs=1e-9)


def test_new_trend_strategies_in_playbook():
    assert {"ema_20_100", "donchian_20"} <= set(A.PLAYBOOK)
    up = [100 * 1.002 ** i for i in range(300)]
    assert A._strat_ema(up)[-1] == 1 and A._strat_ema(up)[50] is None
    assert A._strat_donchian(up)[-1] == 1 and A._strat_donchian([300 - i for i in range(300)])[-1] == 0


def _cov_info(syms, sd, corr, t=252):
    sd = np.array(sd)
    return syms, np.array(corr) * np.outer(sd, sd), t


def test_portfolio_vol_uses_covariance_and_pafka_kondor():
    info = _cov_info(["SPY", "TLT"], [0.01, 0.01], [[1, -0.5], [-0.5, 1]])
    w = {"SPY": 0.5, "TLT": 0.5}
    vol, method = A.portfolio_vol(w, info, {"SPY": 0.16, "TLT": 0.16})
    expected = np.sqrt(0.25 * 1e-4 * 2 * (1 - 0.5) * 252) / (1 - 2 / 252)
    assert vol == pytest.approx(expected) and "Pafka-Kondor" in method
    upper, _ = A.portfolio_vol(w, None, {"SPY": 0.16, "TLT": 0.16})
    assert upper == pytest.approx(0.16) and vol < upper  # la diversificación ya no se ignora


def test_risk_parity_budget_and_higham_repair():
    info = _cov_info(["SPY", "TLT", "GLD"], [0.02, 0.01, 0.01], np.eye(3))
    views = {s: {"signals": {"vol60": 0.2}} for s in info[0]}
    budget, method = A.risk_budget(["SPY", "TLT", "GLD"], views, info)
    assert method == "paridad de riesgo (covarianza)" and budget["SPY"] < budget["TLT"]
    bad = {"SPY": [0.01, -0.01] * 40, "TLT": [0.01, -0.01] * 40, "GLD": [-0.01, 0.01] * 40}
    syms, cov, _ = A.covariance(bad)
    assert np.linalg.eigvalsh(cov).min() > -1e-10  # válida (reparada con Higham si hacía falta)


def test_bubble_halves_max_weight():
    w, _ = A.apply_risk({"SPY": 0.15, "QQQ": 0.12}, {"SPY": 0.01, "QQQ": 0.01}, P, None, {"SPY"})
    assert w["SPY"] <= A.BY_SYMBOL["SPY"].max_weight / 2 + 1e-9 and w["QQQ"] > w["SPY"]
    rng = np.random.default_rng(1)  # mismo patrón que el test de sadf de quantfin
    walk = np.cumsum(rng.standard_normal(300)) + 300
    bubble = walk.copy()
    bubble[200:] = bubble[199] * 1.02 ** np.arange(1, 101)
    assert A.asset_signals(list(bubble))["bubble"] and not A.asset_signals(list(walk))["bubble"]


def test_square_root_impact_clamps_large_orders():
    orders, checks = A.plan_orders({"SPY": 0.15}, {}, {"SPY": 10.0}, 100_000_000, P,
                                   {"SPY": (0.02, 50_000)})
    o = orders[0]
    assert o["impact_bps"] == pytest.approx(A.MAX_IMPACT_BPS)
    assert any(c["check"] == "impacto SPY" and c["status"] == "clamped" for c in checks)
    small, _ = A.plan_orders({"SPY": 0.15}, {}, {"SPY": 500.0}, 100_000, P, {"SPY": (0.01, 5e7)})
    assert small[0]["impact_bps"] < 1


def test_systemic_fragility_detects_rising_correlation():
    rng = np.random.default_rng(5)
    f = rng.standard_normal((400, 1))
    calm = rng.standard_normal((400, 12)) * 0.01 + f * 0.002
    calm[-63:] = rng.standard_normal((63, 12)) * 0.01 + f[-63:] * 0.03  # el mercado se vuelve un solo factor
    out = A.systemic_fragility(calm)
    assert out["fragile"] and out["z"] >= 1
    regime = A.macro_regime(None, None, None, out)
    assert regime["regime"] == "risk_off" and any("Absorption ratio" in n for n in regime["notes"])


@pytest.mark.parametrize("name,args,key", [
    ("qf_bubble_test", {"symbol": "AAPL"}, "sadf"),
    ("qf_pairs_ou", {"symbol_a": "SPY", "symbol_b": "QQQ"}, "pair"),
    ("qf_risk_parity", {"symbols": ["SPY", "TLT", "GLD"]}, "weights"),
    ("qf_yield_curve", {"maturities": [0.25, 1, 2, 5, 10, 30], "yields": [0.045, 0.043, 0.041, 0.04, 0.042, 0.046]},
     "level"),
    ("qf_bond", {"coupon": 0.05, "ytm": 0.05, "years": 10}, "price"),
    ("qf_kelly_binary", {"probability": 0.6, "price": 0.5}, "kelly_fraction"),
    ("qf_market_making", {"mid": 100, "inventory": 5, "sigma": 2}, "bid"),
    ("qf_execution_plan", {"symbol": "SPY", "qty": 1000}, "impact_bps"),
    ("qf_systemic_fragility", {}, "absorption_ratio"),
])
def test_quantfin_tools(client, user, name, args, key):
    r = client.post("/api/tools/call", headers=user["headers"], json={"name": name, "arguments": args}).json()
    assert r["success"], r
    assert key in r["data"]
    if name == "qf_bond":
        assert r["data"]["price"] == pytest.approx(100)
    if name == "qf_kelly_binary":
        assert r["data"]["kelly_fraction"] == pytest.approx(0.2)


def test_cycle_uses_quantfin(client, user):
    rep = client.post("/fund/cycle", headers=user["headers"], json={}).json()["data"]["report"]
    q = rep["quantfin"]
    assert q["covariance"]["assets"] >= 10 and q["fragility"] is not None
    if rep["raw_weights"]:
        assert q["risk_budget"] == "paridad de riesgo (covarianza)"
    assert all("impact_bps" in o for o in rep["orders"])
    assert any("Absorption ratio" in n for n in rep["macro"]["notes"])
