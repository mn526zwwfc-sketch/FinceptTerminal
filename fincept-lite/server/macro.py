"""Macro: series económicas vía DBnomics (conector sin API key que Fincept integra).

El servidor real tiene /macro/* (CEIC, calendario, World Government Bonds) de
pago. La réplica usa DBnomics —agregador público de BLS, FED, ECB, Eurostat,
IMF, BEA...— que el terminal también ofrece como conector y como tools MCP
(search_dbnomics, get_dbnomics_observations).
"""

from __future__ import annotations

import re
import time

import httpx

from .config import settings
from .market.providers import UA

BASE = "https://api.db.nomics.world/v22"

PRESETS = [
    {"id": "FED/H15/RIFSPFF_N.M", "label": "Fed Funds (EE. UU.)", "unit": "%"},
    {"id": "ECB/FM/D.U2.EUR.4F.KR.DFR.LEV", "label": "Tipo depósito BCE", "unit": "%"},
    {"id": "BLS/ln/LNS14000000", "label": "Desempleo EE. UU.", "unit": "%"},
    {"id": "Eurostat/une_rt_m/M.SA.TOTAL.PC_ACT.T.EA20", "label": "Desempleo zona euro", "unit": "%"},
    {"id": "BLS/cu/CUSR0000SA0", "label": "IPC EE. UU. (índice)", "unit": "idx"},
    {"id": "Eurostat/prc_hicp_manr/M.RCH_A.CP00.EA", "label": "IPCA zona euro (a/a)", "unit": "%"},
    {"id": "BEA/NIPA-T10101/A191RL-Q", "label": "PIB real EE. UU. (t/t anualizado)", "unit": "%"},
]

SERIES_ID = re.compile(r"^[A-Za-z0-9_.:\-]+/[A-Za-z0-9_.:\-]+/[A-Za-z0-9_.:\-]+$")
_cache: dict[str, tuple[float, object]] = {}
_client: httpx.AsyncClient | None = None


class MacroError(Exception):
    pass


async def _get(path: str, params: dict | None = None) -> dict:
    global _client
    if not settings.live:
        raise MacroError("DBnomics no disponible en modo sim")
    key = path + repr(sorted((params or {}).items()))
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 3600:
        return hit[1]  # type: ignore[return-value]
    if _client is None:
        _client = httpx.AsyncClient(timeout=25.0, headers={"User-Agent": UA})
    try:
        r = await _client.get(BASE + path, params=params)
    except httpx.HTTPError as e:
        raise MacroError(f"network: {e.__class__.__name__}") from e
    if r.status_code != 200:
        raise MacroError(f"DBnomics HTTP {r.status_code}")
    data = r.json()
    _cache[key] = (time.time(), data)
    return data


async def search(query: str, limit: int = 10) -> list[dict]:
    data = await _get("/search", {"q": query, "limit": min(limit, 50)})
    return [
        {"provider": d.get("provider_code"), "dataset": d.get("code"), "name": d.get("name"),
         "provider_name": d.get("provider_name"), "series_count": d.get("nb_series")}
        for d in data.get("results", {}).get("docs", [])
    ]


async def dataset_series(provider: str, dataset: str, query: str = "", limit: int = 20) -> list[dict]:
    params = {"limit": min(limit, 50)}
    if query:
        params["q"] = query
    data = await _get(f"/series/{provider}/{dataset}", params)
    return [
        {"id": f"{provider}/{dataset}/{d.get('series_code')}", "name": d.get("series_name")}
        for d in data.get("series", {}).get("docs", [])
    ]


async def observations(series_id: str, limit: int = 120) -> dict:
    if not SERIES_ID.match(series_id):
        raise MacroError("series_id must look like PROVIDER/DATASET/SERIES")
    data = await _get(f"/series/{series_id}", {"observations": 1, "format": "json"})
    docs = data.get("series", {}).get("docs", [])
    if not docs:
        raise MacroError(f"series not found: {series_id}")
    d = docs[0]
    pts = [{"period": p, "value": v} for p, v in zip(d.get("period", []), d.get("value", []))
           if isinstance(v, (int, float))]
    return {
        "id": series_id, "name": d.get("series_name"), "dataset": d.get("dataset_name"),
        "frequency": d.get("@frequency"), "last_period": pts[-1]["period"] if pts else None,
        "last_value": pts[-1]["value"] if pts else None, "observations": pts[-limit:],
        "source": "DBnomics",
    }
