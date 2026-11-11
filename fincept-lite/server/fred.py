"""Cliente mínimo de FRED (Federal Reserve Bank of St. Louis) para datos macro al día.

Necesita una clave gratuita en la variable de entorno FRED_API_KEY
(https://fred.stlouisfed.org/docs/api/api_key.html). Sin clave, FRED no se usa y el fondo
sigue con DBnomics. La clave nunca se escribe en disco ni en los registros.
"""

from __future__ import annotations

import os
import re
import time

import httpx

from .config import settings

BASE = "https://api.stlouisfed.org/fred/series/observations"
SERIES_ID = re.compile(r"^[A-Z0-9_]{2,40}$")
_cache: dict[str, tuple[float, list]] = {}
transport: httpx.AsyncBaseTransport | None = None  # los tests lo sustituyen


class FredError(Exception):
    pass


def api_key() -> str:
    return os.environ.get("FRED_API_KEY", "").strip()


def available() -> bool:
    return bool(api_key()) and settings.live


async def observations(series_id: str, limit: int = 40) -> list[dict]:
    """Últimas observaciones [{period 'AAAA-MM-DD', value}], la más reciente al final."""
    if not SERIES_ID.match(series_id):
        raise FredError("series_id no válido")
    if not available():
        raise FredError("FRED no disponible: falta FRED_API_KEY o el servidor está en modo sim")
    hit = _cache.get(f"{series_id}:{limit}")
    if hit and time.time() - hit[0] < 3600:
        return hit[1]
    params = {"series_id": series_id, "api_key": api_key(), "file_type": "json", "sort_order": "desc",
              "limit": limit}
    try:
        async with httpx.AsyncClient(timeout=20.0, transport=transport) as c:
            r = await c.get(BASE, params=params)
    except httpx.HTTPError as e:  # sin str(e): la URL lleva la clave
        raise FredError(f"red: {e.__class__.__name__}") from None
    if r.status_code != 200:
        raise FredError(f"FRED HTTP {r.status_code}" + (": clave no válida" if r.status_code == 400 else ""))
    out = []
    for o in reversed(r.json().get("observations", [])):
        try:
            out.append({"period": o["date"], "value": float(o["value"])})
        except (KeyError, ValueError):  # FRED marca los huecos con "."
            continue
    _cache[f"{series_id}:{limit}"] = (time.time(), out)
    return out


def yoy(obs: list[dict]) -> list[dict]:
    """Variación interanual (%) de un índice mensual."""
    return [{"period": obs[i]["period"], "value": (obs[i]["value"] / obs[i - 12]["value"] - 1) * 100}
            for i in range(12, len(obs)) if obs[i - 12]["value"]]
