"""Configuración global de Fincept Lite (réplica educativa del servidor de Fincept).

Todo se controla por variables de entorno para que el mismo binario sirva en
modo "live" (datos reales de Yahoo Finance / RSS / DBnomics) o en modo "sim"
(mercado simulado determinista, útil sin internet y para tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    host: str = os.environ.get("FINCEPT_HOST", "127.0.0.1")
    port: int = int(os.environ.get("FINCEPT_PORT", "41800"))
    # "live" = Yahoo/RSS/DBnomics con fallback a simulador; "sim" = solo simulador.
    data_mode: str = os.environ.get("FINCEPT_DATA_MODE", "live").lower()
    db_path: Path = Path(os.environ.get("FINCEPT_DB", str(ROOT / "data" / "fincept_lite.db")))
    # Modo desarrollo: el OTP de registro se devuelve en la respuesta y se crea
    # un usuario demo. En el servidor real el OTP solo viaja por email.
    dev_mode: bool = _env_bool("FINCEPT_DEV", True)
    free_credits: float = float(os.environ.get("FINCEPT_FREE_CREDITS", "350"))
    # Modelo para el chat IA (solo se usa si hay credenciales de Anthropic).
    ai_model: str = os.environ.get("FINCEPT_AI_MODEL", "claude-opus-5-5")
    ai_effort: str = os.environ.get("FINCEPT_AI_EFFORT", "medium")
    # Ventana de gracia del protocolo de jobs MCP: una tool que tarda más
    # devuelve {job_id, status:"running"} y el cliente hace polling.
    mcp_grace_seconds: float = float(os.environ.get("FINCEPT_MCP_GRACE", "8"))
    mcp_result_budget: int = 24 * 1024  # igual que kResultBudgetBytes del C++
    quote_ttl_live_ms: int = 30_000  # = data/refresh_interval_ms por defecto del terminal
    quote_ttl_sim_ms: int = 1_000
    extra_allowed_hosts: list[str] = field(
        default_factory=lambda: [h for h in os.environ.get("FINCEPT_ALLOWED_HOSTS", "").split(",") if h]
    )

    @property
    def live(self) -> bool:
        return self.data_mode != "sim"


settings = Settings()
VERSION = "0.1.0"
