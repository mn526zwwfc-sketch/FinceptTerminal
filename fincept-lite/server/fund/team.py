"""El equipo del fondo desde la línea de comandos, sin abrir la terminal.

    python -m server.fund.team [rol] [--out acta.json]   # convoca el comité y muestra la parte del rol
    python -m server.fund.team <rol> --from acta.json     # la parte del rol de un acta ya guardada

    rol: macro, sentimiento, analistas, cuant, cio, riesgos, trader, equipo, todos (por defecto)

Convoca un comité en PAPER sobre una base de datos en memoria (no toca tus cuentas ni tus datos) y
devuelve en JSON la parte del acta que le corresponde a cada agente. Los subagentes del plugin
`fincept-fondo` lo usan para trabajar con datos de verdad: con FINCEPT_DATA_MODE=live usa Yahoo y
DBnomics; sin red, el simulador. Los agentes entrenados se cargan de `agentes/` si están al día.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

ROLES = ("macro", "sentimiento", "analistas", "cuant", "cio", "riesgos", "trader", "equipo", "todos")


def section(rep: dict, role: str) -> dict:
    views = rep["views"]
    if role == "macro":
        return {"regimen": rep["macro"], "fragilidad_sistemica": rep["quantfin"]["fragility"],
                "evidencia": rep["evidence"]["macro"]}
    if role == "sentimiento":
        return {"sentimiento": rep["sentiment"], "evidencia": rep["evidence"]["sentiment"]}
    if role == "analistas":
        return {"activos": {s: {"mesa": v["desk"], "puntuacion": round(v["score"], 3),
                                "senales": {k: v["signals"][k] for k in (
                                    "price", "trend", "momentum", "mom_12_1", "mom_3m", "rsi14", "vol20", "vol60",
                                    "drawdown", "panic_state", "sadf", "bubble")},
                                "debate": v["debate"]} for s, v in views.items()},
                "evidencia": rep["evidence"]["analysts"]}
    if role == "cuant":
        return {"entrenamiento": rep.get("training"),
                "estrategias": {s: {k: v["strategy"].get(k) for k in (
                    "strategy", "label", "trained", "validated", "deflated_sharpe", "is_sharpe", "oos_sharpe",
                    "current_signal", "exposure", "trust")} for s, v in views.items()},
                "evidencia": rep["evidence"]["quant"]}
    if role == "cio":
        return {"pesos_brutos": rep["raw_weights"], "objetivo": rep["target"],
                "presupuesto_de_riesgo": rep["quantfin"]["risk_budget"], "confianza_mesas": rep["desk_trust"],
                "desacuerdo_medio": rep["disagreement"], "acta": rep.get("memo_llm") or rep["memo"],
                "evidencia": rep["evidence"]["cio"]}
    if role == "riesgos":
        return {"controles": rep["risk_checks"], "cortacircuitos": rep["circuit_breaker"],
                "burbujas": rep["quantfin"]["bubbles"], "covarianza": rep["quantfin"]["covariance"],
                "politica": rep["policy"], "evidencia": rep["evidence"]["risk"]}
    if role == "trader":
        return {"ordenes": rep["orders"], "comprobaciones": rep["order_checks"], "patrimonio": rep["equity"],
                "caja": rep["cash"], "evidencia": rep["evidence"]["execution"]}
    if role == "equipo":
        return rep["team"]
    return {r: section(rep, r) for r in ROLES if r != "todos"} | {"fuente_de_datos": rep["data_source"]}


async def committee() -> dict:
    from ..auth import create_user
    from ..db import get_db
    from . import engine
    row = get_db().one("SELECT id FROM users WHERE email=?", ("equipo@example.com",))
    uid = row["id"] if row else create_user("equipo", "equipo@example.com", os.urandom(12).hex(), verified=True)["id"]
    run = await engine.run_cycle(uid, execute=False, trigger="cli")
    return run["report"]


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m server.fund.team")
    ap.add_argument("rol", nargs="?", default="todos", choices=ROLES)
    ap.add_argument("--out", help="guarda el acta completa en este archivo JSON")
    ap.add_argument("--from", dest="src", help="lee un acta guardada en vez de convocar el comité")
    a = ap.parse_args(argv)
    if a.src:
        with open(a.src, encoding="utf-8") as fh:
            rep = json.load(fh)
    else:
        os.environ.setdefault("FINCEPT_DB", ":memory:")  # nunca toca la base de datos de la terminal
        rep = asyncio.run(committee())
        if a.out:
            with open(a.out, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, default=str)
    print(json.dumps(section(rep, a.rol), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
