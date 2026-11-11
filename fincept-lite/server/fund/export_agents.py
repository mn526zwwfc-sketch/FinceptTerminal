"""Entrena a los agentes con datos reales y guarda el resultado en `fincept-lite/agentes/`.

    FINCEPT_DATA_MODE=live python -m server.fund.export_agents [--capital 200 --max-order 200 --plan fixed]

Genera, sin abrir la terminal:
* `entrenamiento_<coste>pb.json`: el libro de estrategias de cada activo, entrenado al coste del modo paper
  (10 pb) y al coste real de la cuenta indicada (comisiones de IBKR).
* `perfiles.json`: lo que sabe cada agente (skills con sus reglas, papers y código).
* `RESUMEN.md`: lo mismo, para leer.

El fondo carga estos archivos solo si el usuario aún no ha entrenado (ver training.seed).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone

from ..config import settings
from . import live as L
from . import training as T

OUT = T.SEED_DIR


def _md(trainings: list[dict], profiles: list[dict]) -> str:
    when = datetime.fromtimestamp(trainings[0]["created"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = ["# Agentes entrenados", "",
           f"Entrenados el {when} con 5 años de datos diarios reales ({', '.join(trainings[0]['data_sources'])}) "
           "de los 17 activos del fondo. Protocolo: 60 % entrenar, 20 % validar, 20 % prueba final; ejecución en "
           "la apertura siguiente; Deflated Sharpe por las 32 configuraciones probadas.", "",
           "Se regeneran con `FINCEPT_DATA_MODE=live python -m server.fund.export_agents`. El fondo los usa "
           "hasta que entrenes tú (botón ENTRENAR AGENTES) o pasen 30 días.", ""]
    for t in trainings:
        s = t["summary"]
        out += [f"## Coste {t['protocol']['cost_bps']:.0f} pb por operación ({t['label']})", "",
                f"{s['trained']} activos · {s['with_edge']} con ventaja en validación · **{s['validated']} validados** "
                f"en la prueba final · {s['beats_buy_hold']} por encima de comprar y mantener.", "",
                "| Activo | Mesa | Veredicto | Estrategias del conjunto | Sharpe validación | Sharpe prueba | "
                "Comprar y mantener | Exposición hoy |", "|---|---|---|---|---|---|---|---|"]
        for sym, b in t["book"].items():
            f2 = lambda v: "—" if v is None else f"{v:.2f}"  # noqa: E731
            members = ", ".join(f"{m['config']} ×{m['weight']:.2f}" for m in b.get("members", [])) or "—"
            exp = "—" if b.get("exposure_now") is None else f"{b['exposure_now']:.0%}"
            out.append(f"| {sym} | {b['desk']} | {b.get('verdict') or b.get('reason')} | {members} | "
                       f"{f2((b.get('valid') or {}).get('sharpe'))} | {f2((b.get('test') or {}).get('sharpe'))} | "
                       f"{f2((b.get('buy_hold_test') or {}).get('sharpe'))} | {exp} |")
        out += ["", "**Lo que aprendió cada mesa:**", ""]
        out += [f"- {d}: {v['lesson']}" for d, v in t["desks"].items()]
        out.append("")
    out += ["## Qué sabe cada agente", ""]
    for p in profiles:
        out += [f"### {p['name']}", "",
                f"{len(p['papers'])} papers · funciones quantfin: {', '.join(p['functions']) or '—'} · "
                f"código: {', '.join(p['code'])}", ""]
        for sk in p["skills"]:
            out.append(f"- Skill **{sk['name']}**: " + "; ".join(sk["lessons"][:3]))
        out.append("")
    return "\n".join(out)


async def main(capital: float, max_order: float, plan: str) -> None:
    if settings.data_mode != "live":
        raise SystemExit("Usa datos reales: FINCEPT_DATA_MODE=live python -m server.fund.export_agents")
    from .engine import _fetch_histories
    hist, sources = await _fetch_histories()
    if set(sources.values()) != {L.LIVE_SOURCE}:
        raise SystemExit(f"Algunos históricos no son reales ({sources}); reintenta más tarde.")
    cfg = {"capital": capital, "max_order": max_order, "commission_plan": plan}
    costs = [(T.COST_BPS, "modo paper"),
             (max(T.COST_BPS, L.live_cost_bps(cfg)), f"cuenta de {capital:g} USD, IBKR {plan}")]
    OUT.mkdir(exist_ok=True)
    trainings = []
    for cost, label in costs:
        t0 = time.time()
        res = await asyncio.to_thread(T.train_all, hist, sources, cost)
        res |= {"trigger": "precargado", "label": label}
        path = OUT / f"entrenamiento_{cost:.0f}pb.json"
        path.write_text(json.dumps(res, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
        trainings.append(res)
        print(f"{path.name}: {res['summary']} ({time.time() - t0:.1f} s)")
    profiles = T.agent_profiles()
    (OUT / "perfiles.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "RESUMEN.md").write_text(_md(trainings, profiles), encoding="utf-8")
    print(f"perfiles.json y RESUMEN.md en {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--capital", type=float, default=200.0)
    ap.add_argument("--max-order", type=float, default=200.0)
    ap.add_argument("--plan", choices=sorted(L.COMMISSION_PLANS), default="fixed")
    a = ap.parse_args()
    asyncio.run(main(a.capital, a.max_order, a.plan))
