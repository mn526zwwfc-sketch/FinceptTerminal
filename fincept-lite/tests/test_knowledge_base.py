"""Base de conocimiento unificada y acceso a las 39 funciones de quantfin."""
import importlib
import inspect

import pytest

from server import quantfin_catalog as qc
from server.fund import research
from server.tools import REGISTRY

MODS = {m: importlib.import_module(f"server.{m}") for m in ("tools", "analytics", "backtest")}
MODS["agents"] = importlib.import_module("server.fund.agents")
MODS["engine"] = importlib.import_module("server.fund.engine")
MODS["quantfin"] = importlib.import_module("quantfin.avanzados")


def _resolves(path: str) -> bool:
    mod, name = path.split(" ")[0].split(".")
    return hasattr(MODS[mod], name) or name in REGISTRY


def test_catalog_covers_every_public_quantfin_function_with_matching_signature():
    for module in ("mercados", "avanzados"):
        m = importlib.import_module(f"quantfin.{module}")
        public = {n for n, f in inspect.getmembers(m, inspect.isfunction)
                  if f.__module__ == m.__name__ and not n.startswith("_")}
        listed = {n for n, f in qc.FUNCS.items() if f.module == module}
        assert public == listed, (module, public ^ listed)
        for n in listed:
            sig = list(inspect.signature(getattr(m, n)).parameters)
            assert sig == [p.name for p in qc.FUNCS[n].params], n
    assert len(qc.FUNCS) == 39


@pytest.mark.parametrize("name", sorted(qc.FUNCS))
def test_every_function_runs_its_example(name):
    d = qc.describe(name)
    out = qc.call(name, d["example"])
    assert set(out["result"]) == set(d["outputs"]) and out["papers"]
    for u in d["used_in"]:
        assert _resolves(u), f"{name}: {u}"


def test_call_validates_arguments():
    with pytest.raises(qc.QfArgError, match="Missing argument"):
        qc.call("black_scholes", {"S": 100})
    with pytest.raises(qc.QfArgError, match="Unknown argument"):
        qc.call("kelly_binario", {"p_propia": 0.6, "precio": 0.5, "x": 1})
    with pytest.raises(qc.QfArgError, match="≤"):
        qc.call("pnl_cobertura", {"sims": 10_000_000})
    with pytest.raises(qc.QfArgError, match="max"):
        qc.call("sharpe", {"r": [0.01] * (qc.MAX_VEC + 1)})
    with pytest.raises(qc.QfArgError, match="rectangular"):
        qc.call("min_varianza", {"cov": [[1, 0], [0]]})
    assert qc.call("ajustar_ns", qc.describe("ajustar_ns")["example"])["result"]["lambda"] > 0


def test_qf_function_and_catalog_tools(client, user):
    def call(name, args):
        return client.post("/api/tools/call", headers=user["headers"], json={"name": name, "arguments": args}).json()
    bs = call("qf_function", {"function": "black_scholes", "args": {"S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": 0.2}})
    assert bs["success"] and abs(bs["data"]["result"]["precio"] - 10.4506) < 1e-3
    ex = call("qf_function", {"function": "carry_trade"})  # sin args → ejemplo del catálogo
    assert ex["data"]["result"]["carry_esperado"] > 0
    bad = call("qf_function", {"function": "nope"})
    assert not bad["success"] and "qf_catalog" in bad["message"]
    bad = call("qf_function", {"function": "black_scholes", "args": {"S": 100}})
    assert not bad["success"] and "Missing argument" in bad["message"]
    cat = call("qf_catalog", {"query": "predicción"})["data"]
    assert {f["name"] for f in cat["functions"]} == {"kelly_binario", "lmsr_precio", "brier"}
    assert call("qf_catalog", {})["data"]["total"] == 39


def test_knowledge_base_merges_all_sources_without_duplicates():
    kb = research.knowledge_base()
    ids = [e["id"] for e in kb]
    assert len(ids) == len(set(ids))
    assert sum(len(e["videos"]) for e in kb) == len(research._library_rows()) == 43  # todos los papers del CSV
    assert {r["id"] for r in research.REFERENCES} <= set(ids)  # todas las referencias del fondo
    assert {f for e in kb for f in e["functions"]} == set(qc.FUNCS)  # todas las funciones tienen su paper
    merged = {e["id"] for e in kb if len(e["sources"]) > 1}
    assert {"phillips2015", "kritzman2011", "bailey2014", "higham2002"} <= merged
    for e in kb:
        assert e["title"] and e["finding"] and e["applied"]
        for path in e["applied_in"]:
            assert _resolves(path), f"{e['id']}: {path}"


def test_knowledge_document_is_up_to_date():
    assert research.KB_DOC.read_text(encoding="utf-8") == research.knowledge_markdown(), \
        "Regenera el documento: python -m server.fund.research"


def test_research_endpoints(client, user):
    kb = client.get("/fund/research", headers=user["headers"]).json()["data"]
    assert len(kb) == len(research.knowledge_base())
    fns = client.get("/fund/research/functions", headers=user["headers"]).json()["data"]
    assert len(fns) == 39 and all(f["example"] for f in fns)
