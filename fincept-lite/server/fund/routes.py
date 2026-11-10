"""API REST del fondo (/fund/*). En paper, ejecutar exige una llamada explícita; en modo real (IBKR),
cada orden la aprueba una persona con sesión iniciada en la terminal."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import fail, ok, require_auth
from . import agents as A
from . import engine
from . import live
from .research import knowledge_base

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
    out = engine.set_halt(user["id"], body.halted, body.reason or "parada manual")
    if body.halted:  # la parada de emergencia también caduca lo pendiente y cancela en IBKR lo enviado
        out["live_cancelled"] = await live.cancel_open(user["id"], "parada de emergencia")
    return ok(out)


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
    """Base de conocimiento: papers del fondo + quant-finance-research + funciones de quantfin."""
    return ok(knowledge_base())


@router.get("/research/functions")
async def research_functions(user: dict = Depends(require_auth)):
    """Catálogo de las 39 funciones de quantfin con parámetros, papers y ejemplo."""
    from ..quantfin_catalog import catalog
    return ok(catalog())


@router.post("/train")
async def train(user: dict = Depends(require_auth)):
    """Los agentes entrenan sus estrategias con la base de conocimiento (solo cálculo, no opera)."""
    try:
        return ok(await engine.train(user["id"]))
    except engine.FundError as e:
        return fail(str(e))


@router.get("/training")
async def training_state(user: dict = Depends(require_auth)):
    """Último entrenamiento (libro de estrategias por activo y lo aprendido por mesa)."""
    from . import training as T
    t = T.latest(user["id"])
    return ok(t, "OK" if t else "Los agentes aún no han entrenado: POST /fund/train o convoca el comité.")


@router.get("/agents")
async def agents_profiles(user: dict = Depends(require_auth)):
    """Perfil de cada agente: skills con sus reglas, papers de la base y código que los aplica."""
    from . import training as T
    return ok(T.agent_profiles())


# ── modo real (Interactive Brokers) ─────────────────────────────────────────

class LiveConfigIn(BaseModel):
    capital: float = Field(gt=0, le=10_000_000)
    max_order: float = Field(gt=0)
    daily_loss_pct: float = Field(gt=0, le=0.2)
    account: str = Field(min_length=4, max_length=20)


class LiveModeIn(BaseModel):
    mode: str = Field(pattern="^(paper|live)$")


class ApproveIn(BaseModel):
    confirm: str = Field(max_length=80)


@router.get("/live")
async def live_status(user: dict = Depends(require_auth)):
    await live.refresh(user["id"])  # también en paper: lo ya enviado a IBKR sigue su curso
    return ok(await live.status(user["id"]))


@router.put("/live/config")
async def live_config(body: LiveConfigIn, user: dict = Depends(require_auth)):
    try:
        return ok(live.set_config(user["id"], body.model_dump()))
    except live.LiveError as e:
        return fail(str(e))


@router.put("/live/mode")
async def live_mode(body: LiveModeIn, user: dict = Depends(require_auth)):
    try:
        return ok(await live.set_mode(user["id"], body.mode))
    except live.LiveError as e:
        return fail(str(e))


def _human_session(request: Request) -> None:
    """Las órdenes reales solo las aprueba una persona con sesión iniciada en la terminal (no una API key sola,
    no un agente por MCP)."""
    if not getattr(request.state, "session_token", None):
        raise HTTPException(status_code=403, detail="Aprobar órdenes reales requiere una sesión iniciada en la terminal.")


@router.post("/live/orders/{order_id}/approve")
async def live_approve(order_id: int, body: ApproveIn, request: Request, user: dict = Depends(require_auth)):
    _human_session(request)
    from . import training as T
    o = next((x for x in live.orders(user["id"], 500) if x["id"] == order_id), None)
    if not o:
        return fail("Orden no encontrada.")
    try:
        run = engine.get_run(user["id"], o["run_id"])
        book = (T.latest(user["id"]) or {}).get("book", {})
        latest = engine.last_run(user["id"], with_report=False)
        return ok(await live.approve(user["id"], order_id, body.confirm, run["finished"],
                                     engine.get_state(user["id"])["halted"], book, latest["id"] if latest else None))
    except (live.LiveError, engine.FundError) as e:
        return fail(str(e))


@router.post("/live/orders/{order_id}/confirm-warnings")
async def live_confirm_warnings(order_id: int, request: Request, user: dict = Depends(require_auth)):
    """Segundo clic: confirmar los avisos que IBKR muestra antes de aceptar la orden."""
    _human_session(request)
    o = next((x for x in live.orders(user["id"], 500) if x["id"] == order_id), None)
    if not o:
        return fail("Orden no encontrada.")
    try:
        run = engine.get_run(user["id"], o["run_id"])
        return ok(await live.confirm_warnings(user["id"], order_id, run["finished"],
                                              engine.get_state(user["id"])["halted"]))
    except (live.LiveError, engine.FundError) as e:
        return fail(str(e))


class ReconcileIn(BaseModel):
    filled_qty: float = Field(ge=0)
    avg_price: float | None = Field(default=None, gt=0)


@router.post("/live/orders/{order_id}/reconcile")
async def live_reconcile(order_id: int, body: ReconcileIn, request: Request, user: dict = Depends(require_auth)):
    """Resolver a mano una orden que IBKR dejó de listar, con lo que muestra tu cuenta de IBKR."""
    _human_session(request)
    try:
        return ok(live.reconcile(user["id"], order_id, body.filled_qty, body.avg_price))
    except live.LiveError as e:
        return fail(str(e))


@router.post("/live/orders/{order_id}/reject")
async def live_reject(order_id: int, request: Request, user: dict = Depends(require_auth)):
    _human_session(request)
    try:
        return ok(live.reject(user["id"], order_id))
    except live.LiveError as e:
        return fail(str(e))
