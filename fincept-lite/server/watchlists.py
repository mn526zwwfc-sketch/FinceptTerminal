"""Cloud sync /v1 — réplica del servicio Go "finceptgo" (network/cloud/CloudClient).

Diferencias con la API FastAPI "legacy":
* Autenticación `Authorization: Bearer <api_key>` (+ X-Session-Token opcional).
* Toda respuesta usa el sobre {success, message, data, error, hint}; el
  cliente considera OK solo si success=true **y** HTTP 2xx.
Aquí se sincronizan las watchlists del usuario.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth import public_profile, require_auth
from .db import get_db
from .market.providers import normalize_symbol

router = APIRouter(prefix="/v1")


def envelope(data=None, message: str = "ok", status: int = 200, error: str | None = None, hint: str | None = None):
    body = {"success": error is None, "message": message, "data": data}
    if error:
        body["error"] = error
    if hint:
        body["hint"] = hint
    return JSONResponse(status_code=status, content=body)


class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    symbols: list[str] = Field(default_factory=list, max_length=200)


def _row_out(r: dict) -> dict:
    return {"id": r["id"], "name": r["name"], "symbols": json.loads(r["symbols"]), "updated_at": r["updated_at"]}


def _clean(symbols: list[str]) -> list[str]:
    return list(dict.fromkeys(normalize_symbol(s) for s in symbols if s.strip()))


def upsert_symbols(uid: int, name: str, symbols: list[str]) -> dict:
    db = get_db()
    row = db.one("SELECT * FROM watchlists WHERE user_id=? AND name=?", (uid, name))
    if row:
        merged = list(dict.fromkeys(json.loads(row["symbols"]) + symbols))
        db.execute("UPDATE watchlists SET symbols=?, updated_at=? WHERE id=?", (json.dumps(merged), time.time(), row["id"]))
        return db.one("SELECT * FROM watchlists WHERE id=?", (row["id"],))
    cur = db.execute("INSERT INTO watchlists(user_id, name, symbols, updated_at) VALUES (?,?,?,?)",
                     (uid, name, json.dumps(symbols), time.time()))
    return db.one("SELECT * FROM watchlists WHERE id=?", (cur.lastrowid,))


def ensure_default_watchlist(uid: int) -> None:
    if not get_db().one("SELECT id FROM watchlists WHERE user_id=?", (uid,)):
        upsert_symbols(uid, "Principal", ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "TSLA", "SAN.MC", "BTC-USD"])


@router.get("/me")
async def me(user: dict = Depends(require_auth)):
    return envelope(public_profile(user))


@router.get("/watchlists")
async def list_watchlists(user: dict = Depends(require_auth)):
    ensure_default_watchlist(user["id"])
    rows = get_db().all("SELECT * FROM watchlists WHERE user_id=? ORDER BY id", (user["id"],))
    return envelope([_row_out(r) for r in rows])


@router.post("/watchlists")
async def create_watchlist(body: WatchlistIn, user: dict = Depends(require_auth)):
    try:
        syms = _clean(body.symbols)
    except ValueError as e:
        return envelope(None, str(e), 400, "invalid_symbol")
    if get_db().one("SELECT id FROM watchlists WHERE user_id=? AND name=?", (user["id"], body.name)):
        return envelope(None, "A watchlist with that name exists", 409, "conflict", "Use PUT to update it.")
    return envelope(_row_out(upsert_symbols(user["id"], body.name, syms)), "created", 201)


@router.put("/watchlists/{wid}")
async def update_watchlist(wid: int, body: WatchlistIn, user: dict = Depends(require_auth)):
    row = get_db().one("SELECT * FROM watchlists WHERE id=? AND user_id=?", (wid, user["id"]))
    if not row:
        return envelope(None, "not found", 404, "not_found")
    try:
        syms = _clean(body.symbols)
    except ValueError as e:
        return envelope(None, str(e), 400, "invalid_symbol")
    get_db().execute("UPDATE watchlists SET name=?, symbols=?, updated_at=? WHERE id=?",
                     (body.name, json.dumps(syms), time.time(), wid))
    return envelope(_row_out(get_db().one("SELECT * FROM watchlists WHERE id=?", (wid,))), "updated")


@router.delete("/watchlists/{wid}")
async def delete_watchlist(wid: int, user: dict = Depends(require_auth)):
    cur = get_db().execute("DELETE FROM watchlists WHERE id=? AND user_id=?", (wid, user["id"]))
    if not cur.rowcount:
        return envelope(None, "not found", 404, "not_found")
    return envelope({"id": wid}, "deleted")
