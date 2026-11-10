# quant-finance-research

Investigación de finanzas cuantitativas (noviembre 2026) + código en Python probado, organizado por mercado.

## Contenido

- **`docs/investigacion.md`**: la investigación completa.
  - Tendencias 2025-2026: machine learning, agentes con LLM y replicación de factores.
  - Papers, estrategias y fórmulas para acciones, renta fija, divisas, materias primas, derivados, microestructura, cripto/DeFi y mercados de predicción.
  - 9 cursos de Yale, Wharton, MIT, Columbia, NYU y Oxford.
  - Librerías y datos abiertos.
  - 43 papers explicados por @vince.quant, verificados.
  - Más de 30 fuentes.
- **`src/quantfin/`**: 39 funciones con solo `numpy` y `scipy`.
- **`tests/`**: 21 pruebas contra valores de referencia (por ejemplo, Black-Scholes = 10.4506; Pafka-Kondor = 3.00×).
- **`data/vince_quant_videos.csv`**: índice de los videos con su paper y la función que lo implementa.

## Inicio rápido

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
python examples/demo.py
```

```python
from quantfin import mercados as m, avanzados as a

m.black_scholes(100, 100, 1, 0.05, 0.2)        # (precio, delta, gamma, vega)
a.deflated_sharpe(retornos, n_pruebas=500, var_sharpes=0.001)
```

## Usarlo con Claude Code

Abre la carpeta en Claude Code. Al iniciar, Claude Code lee `CLAUDE.md`, que trae el mapa del proyecto, las reglas (todo modelo con prueba y paper citado) y los siguientes pasos. Para empezar, puedes escribirle algo como:

> Lee CLAUDE.md y docs/investigacion.md. Corre las pruebas. Luego implementa el paso 1 de "Siguientes pasos" (datos reales con yfinance) con sus pruebas.

---

Material de estudio, no asesoría financiera.
