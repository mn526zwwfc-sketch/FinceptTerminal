"""API REST del fondo (/fund/*). Ejecutar exige una llamada explícita y siempre es PAPER."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..auth import fail, ok, require_auth
from . import agents as A
from . import engine
from .research import REFERENCES

router = APIRouter(prefix="/fund")


def _public_state(uid: int) -> dict:
    st = engine.get_state(uid)
    return {**{k: st[k] for k in ("autopilot", "interval_min", "halted", "halt_reason", "peak_equity",
                                  "consecutive_losses", "desk_trust", "last_cycle_at")},
            "universe": [vars(a) for a in A.UNIVERSE], "desks": A.DESKS, "desk_max": A.DESK_MAX,
            "policy": vars(engine.POLICY), "mode": "paper"}


@router.get("/state")
async def state(user: dict = Depends(require_auth)):
    return ok({**_public_state(user["id"]), "last_run": engine.last_run(user["id"]),
               "runs": engine.list_runs(user["id"])})


class CycleIn(BaseModel):
    execute: bool = False


@router.post("/cycle")
async def cycle(body: CycleIn, user: dict = Depends(require_auth)):
    try:
        return ok(await engine.run_cycle(user["id"], execute=body.execute))
    except engine.FundError as e:
        return fail(str(e))


@router.post("/runs/{run_id}/execute")
async def execute(run_id: int, user: dict = Depends(require_auth)):
    try:
        return ok(await engine.execute_run(user["id"], run_id))
    except engine.FundError as e:
        return fail(str(e))


@router.get("/runs/{run_id}")
async def run(run_id: int, user: dict = Depends(require_auth)):
    try:
        return ok(engine.get_run(user["id"], run_id))
    except engine.FundError as e:
        return fail(str(e))


class HaltIn(BaseModel):
    halted: bool
    reason: str | None = Field(default=None, max_length=200)


@router.post("/halt")
async def halt(body: HaltIn, user: dict = Depends(require_auth)):
    return ok(engine.set_halt(user["id"], body.halted, body.reason or "parada manual"))


class AutopilotIn(BaseModel):
    on: bool
    interval_min: int | None = Field(default=None, ge=engine.MIN_AUTOPILOT_MINUTES, le=1440)


@router.put("/autopilot")
async def autopilot(body: AutopilotIn, user: dict = Depends(require_auth)):
    try:
        return ok(engine.set_autopilot(user["id"], body.on, body.interval_min))
    except engine.FundError as e:
        return fail(str(e))


@router.get("/research")
async def research(user: dict = Depends(require_auth)):
    return ok(REFERENCES)
