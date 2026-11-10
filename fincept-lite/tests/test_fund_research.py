"""Lo que aportan los papers: DSR, TSMOM, estado de pánico, debate y la base de investigación."""
import importlib
import math
import random

import pytest

from server.fund import agents as A
from server.fund.research import BY_ID, REFERENCES, cite


def test_deflated_sharpe_penalizes_selection_among_many_trials():
    rnd = random.Random(1)
    good = [0.001 + rnd.gauss(0, 0.01) for _ in range(750)]
    sr = A._moments(good)[0]
    alone = A.deflated_sharpe(good, [sr])  # 1 sola prueba = probabilistic Sharpe ratio
    many = A.deflated_sharpe(good, [sr] + [rnd.gauss(0, 0.04) for _ in range(30)])  # elegida entre 31
    assert 0 <= many < alone <= 1
    noise = [rnd.gauss(0, 0.01) for _ in range(750)]
    assert A.deflated_sharpe(noise, [A._moments(noise)[0], 0.03, -0.02, 0.01]) < 0.9


def test_tsmom_12m_strategy_follows_paper_definition():
    assert "tsmom_12m" in A.PLAYBOOK
    closes = [100 + i for i in range(300)]
    sig = A._strat_tsmom12(closes)
    assert sig[251] is None and sig[252] == 1
    assert A._strat_tsmom12([300 - i for i in range(300)])[-1] == 0


def test_panic_state_halves_momentum():
    calm = [100 * 1.001 ** i for i in range(300)]
    crash = calm[:285] + [calm[284] * (0.96 ** k) * (1.04 if k % 2 else 0.97) for k in range(1, 16)]  # desplome brusco
    s = A.asset_signals(crash)
    assert s["panic_state"] and not A.asset_signals(calm)["panic_state"]


def test_debate_keeps_both_sides_and_measures_disagreement():
    closes = [100 * math.exp(0.2 * math.sin(i / 30) + 0.0004 * i) for i in range(900)]
    candles = [{"t": i, "o": c, "h": c, "l": c, "c": c, "v": 1} for i, c in enumerate(closes)]
    view = {"desk": "equities", "signals": A.asset_signals(closes), "strategy": A.select_strategy(candles)}
    d = A.debate(view, "risk_off")
    assert d["bull"] or d["bear"]
    assert any("régimen risk_off" in b for b in d["bear"])  # el régimen defensivo penaliza renta variable
    assert 0 <= d["disagreement"] <= 1 and d["verdict"] in {"alcista", "bajista", "dividido"}


def test_every_reference_is_wired_to_real_code():
    assert len(REFERENCES) >= 20 and len(BY_ID) == len(REFERENCES)
    mods = {"agents": importlib.import_module("server.fund.agents"), "tools": importlib.import_module("server.tools"),
            "engine": importlib.import_module("server.fund.engine")}
    for r in REFERENCES:
        assert r["finding"] and r["applied"] and r["applied_in"], r["id"]
        for path in r["applied_in"]:
            mod, name = path.split(".")
            assert hasattr(mods[mod], name), f"{r['id']} cita {path}, que no existe"
    assert any(r["year"] >= 2025 for r in REFERENCES)  # incluye investigación reciente
    assert cite("bailey2014", "nope") == [{"id": "bailey2014", "short": "Bailey (2014)",
                                           "doi": "10.3905/jpm.2014.40.5.094"}]


def test_cycle_report_carries_debate_and_evidence(client, user):
    rep = client.post("/fund/cycle", headers=user["headers"], json={}).json()["data"]["report"]
    assert set(rep["evidence"]) == {"memory", "macro", "sentiment", "analysts", "quant", "cio", "risk", "execution"}
    v = next(iter(rep["views"].values()))
    assert {"bull", "bear", "disagreement"} <= set(v["debate"]) and "deflated_sharpe" in v["strategy"]
    assert "Deflated Sharpe" in rep["memo"]
    refs = client.get("/fund/research", headers=user["headers"]).json()["data"]
    assert any(r["id"] == "huang2026" for r in refs) and any("quant-finance-research" in r["sources"] for r in refs)
