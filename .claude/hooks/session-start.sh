#!/bin/bash
# Prepara fincept-lite para los agentes del plugin fincept-fondo en sesiones en la nube:
# crea el entorno virtual e instala las dependencias (solo si cambiaron).
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}/fincept-lite"

hashes=.venv/.session-start.sha256
if ! sha256sum --check --status "$hashes" 2>/dev/null; then
  rm -f "$hashes"
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
  sha256sum ../.claude/hooks/session-start.sh requirements.txt > "$hashes" || rm -f "$hashes"
fi
