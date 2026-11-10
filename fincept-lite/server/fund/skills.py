"""Skills de los agentes: qué enseña cada skill y en qué parte del código se aplica.

Lee los SKILL.md instalados (carpetas `.claude/skills` del proyecto y del repositorio, y las de
plugins del usuario) y extrae sus principios y reglas. Como esas carpetas dependen de la
máquina, `python -m server.fund.skills` guarda una copia en `skills_snapshot.json`, que se usa
cuando una skill no está instalada. Las skills de terceros conservan su origen y licencia.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
SNAPSHOT = HERE / "skills_snapshot.json"
SEARCH = [APP / ".claude" / "skills", APP.parent / ".claude" / "skills", Path.home() / ".claude" / "skills"]
PLUGIN_ROOT = Path.home() / ".claude" / "plugins"

SOURCES = {
    "backtesting-frameworks": "wshobson/agents (MIT)", "economic-calendar-fetcher": "tradermonty/claude-trading-skills",
    "equity-research": "anthropics/financial-services", "macro-rates-monitor": "anthropics/financial-services",
    "option-vol-analysis": "anthropics/financial-services", "yfinance-data": "anthropics/financial-services",
    "fastapi": "fastapi/fastapi", "mcp-builder": "anthropics/skills",
    "llm-trading-agent-security": "affaan-m/everything-claude-code (MIT)",
}

# Dónde se hace cumplir cada skill en el código (no basta con leerla: tiene que cambiar el comportamiento).
APPLIED = {
    "backtesting-frameworks": ["training.train_asset: walk-forward 60/20/20, ejecución en la apertura siguiente y "
                               "costes en cada cambio de posición", "agents.select_strategy: hold-out 30 % + DSR",
                               "backtest.run_signals: sin sesgo de anticipación"],
    "macro-rates-monitor": ["agents.macro_regime: tipos, paro (regla de Sahm) e inflación",
                            "tools.qf_yield_curve: nivel, pendiente y curvatura de la curva"],
    "economic-calendar-fetcher": ["engine._macro_series: series macro de DBnomics (sin clave de FMP)"],
    "equity-research": ["agents.asset_signals: tendencia, momentum, RSI, volatilidad y drawdown por activo"],
    "yfinance-data": ["market.providers.YahooProvider: históricos diarios de 5 años para entrenar"],
    "option-vol-analysis": ["agents.realized_vol: volatilidad realizada 20/60 sesiones",
                            "tools.bs_option_price e implied_vol"],
    "llm-trading-agent-security": ["agents.sanitize_headline: el texto externo se sanea antes del LLM",
                                   "agents.apply_risk y circuit_breaker: límites que no dependen del modelo",
                                   "engine.execute_run: revalidación antes de ejecutar (simulación previa)",
                                   "fund_runs: cada decisión queda auditada, también las bloqueadas"],
    "fastapi": ["server/*: rutas, dependencias y modelos Pydantic"],
    "mcp-builder": ["server/mcp_server.py: tools con anotaciones, paginación y errores accionables"],
}

LESSON_SECTIONS = re.compile(r"principle|best practice|do'?s|don'?ts|key rules|checklist|biases|assess market impact",
                             re.I)


def _clean(line: str) -> str:
    line = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", line)
    line = re.sub(r"\*\*|__|`", "", line)
    line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
    return line.strip()[:400]


def parse_skill(text: str, max_lessons: int = 8) -> dict:
    """Nombre, descripción y reglas (viñetas de las secciones de principios, buenas prácticas o checklist)."""
    meta = {}
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if m:
        cur = None
        for raw in m.group(1).splitlines():
            kv = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", raw)
            if kv:
                cur, val = kv.group(1), kv.group(2).strip()
                meta[cur] = "" if val in (">", "|", ">-", "|-") else val.strip('"')
            elif cur and raw.startswith(" "):
                meta[cur] = (meta[cur] + " " + raw.strip()).strip()
    lessons, take, code = [], False, False
    for line in text[m.end() if m else 0:].splitlines():
        if line.strip().startswith("```"):
            code = not code
            continue
        if code:
            continue
        if line.startswith("#"):
            take = bool(LESSON_SECTIONS.search(line))
            continue
        if not take or not line.strip() or line.lstrip().startswith(("|", ">")):
            continue
        if re.match(r"^\s*(?:[-*]|\d+\.)\s+\S", line):
            items = [_clean(line)]
        else:  # párrafo: una regla por frase
            items = [_clean(x) for x in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line.strip())]
        for item in items:
            if len(item) > 12 and not item.endswith(":") and item not in lessons:
                lessons.append(item)
        if len(lessons) >= max_lessons:
            break
    lessons = lessons[:max_lessons]
    if not lessons and meta.get("description"):
        lessons = [_clean(x) for x in re.split(r"(?<=\.)\s+", meta["description"]) if len(x) > 12][:3]
    return {"name": meta.get("name", ""), "description": meta.get("description", "")[:400], "lessons": lessons}


def _find(name: str) -> Path | None:
    for d in SEARCH:
        p = d / name / "SKILL.md"
        if p.is_file():
            return p
    if PLUGIN_ROOT.is_dir():
        for p in sorted(PLUGIN_ROOT.glob(f"**/skills/{name}/SKILL.md")):
            return p
    return None


def _snapshot() -> dict:
    try:
        return json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_skill(name: str) -> dict:
    path = _find(name)
    if path:
        info, origin = parse_skill(path.read_text(encoding="utf-8")), "instalada"
    elif name in _snapshot():
        info, origin = _snapshot()[name], "copia en skills_snapshot.json"
    else:
        info, origin = {"name": name, "description": "", "lessons": []}, "no disponible"
    return {"name": name, "description": info["description"], "lessons": info["lessons"], "origin": origin,
            "source": SOURCES.get(name, ""), "applied_in": APPLIED.get(name, [])}


def write_snapshot(names) -> dict:
    data = {}
    for n in sorted(set(names)):
        path = _find(n)
        if path:
            data[n] = parse_skill(path.read_text(encoding="utf-8")) | {"source": SOURCES.get(n, "")}
    SNAPSHOT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


if __name__ == "__main__":
    out = write_snapshot(APPLIED)
    print(f"{SNAPSHOT.name}: {len(out)} skills ({', '.join(out)})")
