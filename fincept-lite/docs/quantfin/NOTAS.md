# CLAUDE.md — quant-finance-research

Proyecto de estudio de finanzas cuantitativas de Agustín Ortega. Junta una investigación de papers y cursos (nov 2026) con código en Python que implementa los modelos. El usuario escribe en español: responde y comenta el código en español.

## Qué hay aquí

```
docs/investigacion.md        Investigación completa: tendencias 2025-2026, papers por mercado,
                             cursos, librerías, 43 papers de los videos de @vince.quant, fuentes
data/vince_quant_videos.csv  Índice de los 43 videos: tema, url, paper, idea clave, función
src/quantfin/mercados.py     Modelos base por mercado (23 funciones)
src/quantfin/avanzados.py    Modelos de los papers de @vince.quant (16 funciones)
tests/test_modelos.py        21 pruebas contra valores de referencia de libros y papers
examples/demo.py             Corre los ejemplos de ambos módulos
```

## Comandos

```bash
pip install -e ".[dev]"     # o: pip install -r requirements.txt
pytest -q                   # debe dar 21 passed
python examples/demo.py     # ejemplos con datos sintéticos
```

## Mapa de funciones

| Mercado | Módulo | Funciones |
|---|---|---|
| Derivados | mercados | `black_scholes`, `monte_carlo_call`, `garch11` |
| Derivados | avanzados | `pnl_cobertura` (El Karoui et al. 1998) |
| Acciones | mercados | `regresion_factores`, `momentum_seccion_cruzada` |
| Renta fija | mercados | `nelson_siegel`, `ajustar_ns`, `duracion_convexidad` |
| Divisas | mercados | `carry_trade` |
| Materias primas | mercados | `basis_momentum`, `roll_yield` |
| Multi-activo / tendencia | mercados | `tsmom` |
| Multi-activo / tendencia | avanzados | `senal_ema`, `senal_donchian`, `vol_target`, `ajustar_ou`, `zscore_pairs` |
| Microestructura | mercados | `avellaneda_stoikov`, `almgren_chriss` |
| Microestructura | avanzados | `impacto_raiz` |
| Cripto / DeFi | mercados | `lvr_producto_constante`, `impermanent_loss` |
| Mercados de predicción | mercados | `kelly_binario`, `lmsr_precio`, `brier` |
| Riesgo y portafolio | mercados | `var_es`, `min_varianza`, `risk_parity`, `sharpe` |
| Riesgo y portafolio | avanzados | `nearest_correlation`, `sesgo_optimizador`, `diversity_weighted`, `mejora_sharpe`, `absorption_ratio` |
| Burbujas | avanzados | `adf_t`, `sadf` |
| Validación de backtests | avanzados | `deflated_sharpe` |

Cada modelo está explicado, con su paper, en `docs/investigacion.md` (secciones 3 y 7).

## Reglas para trabajar en este repo

1. **Antes de implementar un modelo, lee su sección en `docs/investigacion.md`** y cita el paper (autores, año, revista o arXiv) en el docstring.
2. **Todo modelo nuevo lleva prueba** en `tests/` contra un valor de referencia conocido (libro, tabla del paper o caso límite analítico). No marques algo como terminado si `pytest -q` no pasa.
3. **Dependencias mínimas:** solo `numpy` y `scipy` en el núcleo. `pandas`/`yfinance` solo en código de datos reales (extra `datos`), nunca dentro de `src/quantfin` sin preguntar.
4. **Datos sintéticos por defecto** con `np.random.default_rng(semilla)` para que todo sea reproducible y corra sin internet.
5. **Sé honesto con los resultados:** reporta costos de transacción, fuera de muestra vs. dentro de muestra y el número de pruebas que hiciste (usa `deflated_sharpe`). Un backtest bonito sin eso no cuenta.
6. No hagas operaciones reales ni conectes cuentas de broker. Es material de estudio, no asesoría financiera.

## Cuidados conocidos

- Varios papers de 2026 son **preprints sin revisión por pares** (marcados en la investigación).
- En el video "overnight vs. intraday", el DOI que da @vince.quant es incorrecto; el correcto es 10.1016/j.jfineco.2019.03.011.
- El MinervaScore es de la plataforma del propio autor de los videos (conflicto de interés); úsalo solo como referencia del Deflated Sharpe Ratio y la PBO.
- `sesgo_optimizador` (Pafka-Kondor): el factor (1 − n/T) aplica a la desviación estándar, no a la varianza.
- `ajustar_ou` estima θ con bastante ruido en muestras cortas; σ sale mucho más preciso.

## Siguientes pasos sugeridos (en orden)

1. `src/quantfin/datos.py`: cargar precios reales con `yfinance` (acciones de la BMV como `WALMEX.MX`, USD/MXN `MXN=X`, futuros, BTC) con caché en `data/raw/`.
2. `src/quantfin/backtest.py`: backtester vectorizado con costos, rebalanceo y métricas (Sharpe, drawdown, turnover).
3. CPCV y PBO de López de Prado (sección 7.8) para validar cualquier estrategia.
4. Limpieza de covarianza: Ledoit-Wolf y clustering jerárquico tipo k-BAHC (sección 7.7).
5. Simulación de Heston y rough Bergomi (secciones 3.5 y 7.1).
6. Detector de regímenes con statistical jump model (Shu, Yu y Mulvey 2024).
