#!/usr/bin/env bash
# Arranca Fincept Lite: crea el entorno virtual la primera vez y lanza el servidor.
#   ./run.sh                 → datos reales (Yahoo / RSS / DBnomics) con fallback a simulador
#   FINCEPT_DATA_MODE=sim ./run.sh   → mercado simulado, sin red
#   ANTHROPIC_API_KEY=… ./run.sh     → chat IA con Claude (si no, modo offline)
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
export FINCEPT_PORT="${FINCEPT_PORT:-41800}"
echo "Fincept Lite → http://127.0.0.1:${FINCEPT_PORT}  (demo: demo@example.com / demo12345)"
exec .venv/bin/python -m server.main
