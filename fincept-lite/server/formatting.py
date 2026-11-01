"""Render Markdown de resultados de tools (response_format="markdown").

Guía mcp-builder: JSON para procesar, Markdown para leer. El Markdown omite
metadatos verbosos, convierte timestamps a fechas legibles y resume las series
largas (velas, curvas de equity) en vez de volcarlas.
"""

from __future__ import annotations

import time
from typing import Any

TIME_KEYS = {"t", "ts", "published", "created_at", "filled_at", "at", "market_time", "train_from", "train_to",
             "test_from", "test_to", "from", "to", "expires_at"}
SERIES_KEYS = {"candles", "equity_curve", "observations", "trade_log", "fills"}
MAX_ROWS = 50
MAX_COLS = 9


def _fmt(key: str, v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if key in TIME_KEYS and isinstance(v, (int, float)) and v > 1e8:
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(v))
    if isinstance(v, float):
        return f"{v:,.6g}" if abs(v) < 1e15 else f"{v:.3e}"
    if isinstance(v, (list, dict)):
        return f"{len(v)} item(s)"
    return str(v).replace("|", "\\|").replace("\n", " ")


def _table(rows: list[dict]) -> str:
    cols: list[str] = []
    for r in rows[:MAX_ROWS]:
        for k, v in r.items():
            if k not in cols and not isinstance(v, (list, dict)):
                cols.append(k)
    cols = cols[:MAX_COLS]
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(_fmt(c, r.get(c)) for c in cols) + " |" for r in rows[:MAX_ROWS]]
    if len(rows) > MAX_ROWS:
        out.append(f"\n_{len(rows) - MAX_ROWS} more row(s) omitted; use response_format='json'._")
    return "\n".join(out)


def _series_summary(key: str, v: list) -> str:
    first, last = v[0], v[-1]
    if isinstance(first, dict):
        span = ""
        tk = next((k for k in ("t", "period") if k in first), None)
        if tk:
            span = f" from {_fmt(tk, first[tk])} to {_fmt(tk, last[tk])}"
        return f"- **{key}**: {len(v)} points{span} (full series with response_format='json')"
    return f"- **{key}**: {len(v)} item(s)"


def to_markdown(value: Any, title: str = "") -> str:
    head = f"## {title}\n\n" if title else ""
    if isinstance(value, list):
        if not value:
            return head + "_No results._"
        if all(isinstance(x, dict) for x in value):
            return head + _table(value)
        return head + "\n".join(f"- {_fmt('', x)}" for x in value)
    if not isinstance(value, dict):
        return head + _fmt("", value)
    if "items" in value and isinstance(value["items"], list) and "total" in value:  # respuesta paginada
        body = _table(value["items"]) if value["items"] else "_No results._"
        foot = f"\n\n_Showing {value['count']} of {value['total']} (offset {value['offset']})."
        foot += f" Next page: offset={value['next_offset']}._" if value.get("has_more") else "_"
        return head + body + foot
    lines, tables = [], []
    for k, v in value.items():
        if isinstance(v, list) and v:
            if k in SERIES_KEYS or len(v) > MAX_ROWS:
                lines.append(_series_summary(k, v))
            elif all(isinstance(x, dict) for x in v):
                tables.append(f"### {k}\n\n{_table(v)}")
            else:
                lines.append(f"- **{k}**: {', '.join(_fmt(k, x) for x in v[:20])}")
        elif isinstance(v, dict):
            inner = ", ".join(f"{ik}={_fmt(ik, iv)}" for ik, iv in v.items() if not isinstance(iv, (list, dict)))
            lines.append(f"- **{k}**: {inner}")
        else:
            lines.append(f"- **{k}**: {_fmt(k, v)}")
    return head + "\n".join(lines) + ("\n\n" + "\n\n".join(tables) if tables else "")
