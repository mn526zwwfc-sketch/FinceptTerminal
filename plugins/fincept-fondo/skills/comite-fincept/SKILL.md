---
name: comite-fincept
description: Convoca al equipo del fondo Fincept como comité de inversión. Use cuando pidan "convoca el comité", "qué opina el fondo", "análisis del equipo", "cartera del fondo Fincept" o una revisión de mercado con los agentes del fondo.
---

# Comité de inversión del fondo Fincept

Coordinas a los 7 subagentes del plugin `fincept-fondo` como un equipo: primero investiga, después decide el comité.

1. **Acta del día** (una sola vez, en paper, sin tocar cuentas):

       cd fincept-lite && FINCEPT_DATA_MODE=live .venv/bin/python -m server.fund.team equipo --out /tmp/acta-fincept.json

   Si no hay red, quita `FINCEPT_DATA_MODE=live` y avisa de que los datos son simulados.

2. **Equipo de investigación, en paralelo.** Lanza a la vez los subagentes `fincept-fondo:fincept-estratega-macro`, `fincept-fondo:fincept-analista-sentimiento`, `fincept-fondo:fincept-analistas-mesa` y `fincept-fondo:fincept-investigador-cuant`. A cada uno pásale la ruta del acta y pídele su entregable.

3. **Comité de inversión.** Con las notas de investigación, lanza `fincept-fondo:fincept-cio` (pásale las cuatro notas), `fincept-fondo:fincept-gestor-riesgos` y `fincept-fondo:fincept-trader`, cada uno con la ruta del acta.

4. **Acta final para la persona.** Régimen y por qué; cartera objetivo y caja; veredicto del gestor de riesgos; órdenes propuestas con su coste; desacuerdos abiertos entre agentes (no los ocultes); y qué estrategias están validadas frente a comprar y mantener.

Reglas: es una propuesta en paper. Ningún agente aprueba ni envía órdenes reales; eso lo hace la persona en la terminal (pantalla FUND, modo real con IBKR). No inventes cifras.
