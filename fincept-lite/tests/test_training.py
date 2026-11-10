"""Entrenamiento de los agentes: estrategias de la base de conocimiento, validadas sin hacer trampa."""
import importlib
import math
import random

import numpy as np

from server.fund import skills as SK
from server.fund import training as T
from server.fund.research import knowledge_base


def _candles(closes):
    return [{"t": i * 86400, "o": c, "h": c, "l": c, "c": c, "v": 1e6} for i, c in enumerate(closes)]


def _walk(n, drift, vol, seed):
    rnd, px, out = random.Random(seed), 100.0, []
    for _ in range(n):
        px *= math.exp(drift + rnd.gauss(0, vol))
        out.append(px)
    return out


def test_returns_use_next_open_and_charge_costs():
    candles = [{"t": i, "o": o, "c": o} for i, o in enumerate([100, 100, 110, 121, 121])]
    pos = np.array([0, 1, 1, 0, 0], dtype=float)  # entra al cierre de la sesión 1
    r = T.strategy_returns(candles, pos)
    assert r[1] == 0  # la decisión del cierre 1 no puede cobrar la subida de esa misma sesión
    assert math.isclose(r[2], 0.10 - T.COST_BPS / 1e4)  # apertura 2 → apertura 3, menos la entrada
    assert r[3] == 0  # la salida decidida al cierre 3 se ejecuta en la apertura 4 (121 → 121)
    assert math.isclose(r[4], -T.COST_BPS / 1e4)  # sale: solo paga el coste


def test_selection_never_sees_the_final_test_segment():
    closes = _walk(1260, 0.0004, 0.012, 3)
    a = T.train_asset(_candles(closes))
    t2 = a["segments"]["test"][0]
    shocked = closes[:t2] + [c * (0.7 if i % 2 else 1.3) for i, c in enumerate(closes[t2:])]
    b = T.train_asset(_candles(shocked))
    assert [f["config"] for f in a["families"]] == [f["config"] for f in b["families"]]
    assert [m["config"] for m in a["members"]] == [m["config"] for m in b["members"]]
    assert [m["fitted"] for m in a["members"]] == [m["fitted"] for m in b["members"]]  # OU ajustado solo en train


def test_trend_is_learned_on_a_trending_market():
    closes = [100 * math.exp(0.0015 * i + 0.08 * math.sin(i / 40)) * (1 + random.Random(i).gauss(0, 0.004))
              for i in range(1260)]
    a = T.train_asset(_candles(closes))
    assert a["edge"] and a["test"]["sharpe"] > 0
    assert any(T.BY_FAMILY[m["family"]].style == "tendencia" for m in a["members"])
    assert a["trials"] == sum(len(f.grid) * 2 for f in T.FAMILIES)


def test_short_history_is_not_trained():
    assert not T.train_asset(_candles(_walk(400, 0, 0.01, 1)))["trained"]


def test_apply_book_reproduces_trained_exposure():
    candles = _candles(_walk(1260, 0.0005, 0.01, 11))
    entry = T.train_asset(candles)
    st = T.apply_book(entry, candles)
    if entry["members"]:
        assert math.isclose(st["exposure"], entry["exposure_now"], abs_tol=1e-9)
        assert st["trained"] and set(st) >= {"strategy", "current_signal", "validated", "trust", "candidates"}
    assert T.apply_book({"trained": False}, candles) is None


def test_every_paper_and_skill_reaches_an_agent():
    profiles = T.agent_profiles()
    assert len(profiles) == 7
    covered = {p["id"] for a in profiles for p in a["papers"]}
    assert covered == {e["id"] for e in knowledge_base()}  # toda la base de conocimiento se reparte
    skills = {s["name"] for a in profiles for s in a["skills"]}
    assert skills | set(T.PLATFORM_SKILLS) == set(SK.APPLIED)
    for a in profiles:
        for s in a["skills"]:
            assert s["lessons"] and s["applied_in"], (a["name"], s["name"])
    mods = {m: importlib.import_module(f"server.fund.{m}") for m in ("agents", "engine", "training")}
    for a in T.AGENTS:
        for path in a["code"]:
            mod, name = path.split(".")
            assert hasattr(mods[mod], name), path
    for f in T.FAMILIES:
        assert set(f.refs) <= covered


def test_skill_parser_and_snapshot_fallback(monkeypatch):
    text = ("---\nname: demo\ndescription: >\n  Demo skill. Second line.\n---\n# Demo\n## Core Principles\n\n"
            "Always test out of sample. Never trust one backtest.\n\n## Do's\n- **Include costs** in every test\n"
            "```python\n- not a rule\n```\n## Other\n- ignored bullet here\n")
    p = SK.parse_skill(text)
    assert p["name"] == "demo" and p["description"].startswith("Demo skill")
    assert p["lessons"] == ["Always test out of sample.", "Never trust one backtest.", "Include costs in every test"]
    monkeypatch.setattr(SK, "_find", lambda name: None)
    snap = SK.load_skill("llm-trading-agent-security")
    assert snap["origin"].startswith("copia") and snap["lessons"]
    assert SK.load_skill("nope")["origin"] == "no disponible"


def test_cycle_trains_agents_and_uses_the_book(client, user):
    h = user["headers"]
    assert client.get("/fund/training", headers=h).json()["data"] == {}
    rep = client.post("/fund/cycle", headers=h, json={}).json()["data"]["report"]
    assert rep["training"]["summary"]["trained"] > 0  # el primer comité entrena solo
    assert any(v["strategy"].get("trained") for v in rep["views"].values())
    assert "Estrategias entrenadas" in rep["memo"]
    t = client.get("/fund/training", headers=h).json()["data"]
    assert t["id"] == rep["training"]["id"] and t["trigger"] == "auto" and t["desks"]
    again = client.post("/fund/train", headers=h).json()["data"]
    assert again["id"] > t["id"] and again["trigger"] == "manual"
    agents = client.get("/fund/agents", headers=h).json()["data"]
    assert [a["id"] for a in agents] == ["macro", "sentiment", "analysts", "quant", "cio", "risk", "trader"]
    tool = client.post("/api/tools/call", headers=h, json={"name": "fund_get_training",
                                                           "arguments": {"include_profiles": True}}).json()
    assert tool["success"] and tool["data"]["training"]["training_id"] == again["id"] and len(tool["data"]["agents"]) == 7
