# Agentes entrenados

Entrenados el 2026-11-11 12:21 UTC con 5 años de datos diarios reales (yahoo) de los 17 activos del fondo. Protocolo: 60 % entrenar, 20 % validar, 20 % prueba final; ejecución en la apertura siguiente; Deflated Sharpe por las 32 configuraciones probadas.

Se regeneran con `FINCEPT_DATA_MODE=live python -m server.fund.export_agents`. El fondo los usa hasta que entrenes tú (botón ENTRENAR AGENTES) o pasen 30 días.

## Coste 10 pb por operación (modo paper)

17 activos · 17 con ventaja en validación · **6 validados** en la prueba final · 3 por encima de comprar y mantener.

| Activo | Mesa | Veredicto | Estrategias del conjunto | Sharpe validación | Sharpe prueba | Comprar y mantener | Exposición hoy |
|---|---|---|---|---|---|---|---|
| SPY | equities | validada | donchian(20)+vt ×0.51, trend_sma(100)+vt ×0.31, tsmom(252) ×0.18 | 0.78 | 0.16 | 0.80 | 18% |
| QQQ | equities | validada | donchian(20)+vt ×0.46, trend_sma(200) ×0.36, tsmom(252) ×0.18 | 1.08 | 0.10 | 0.51 | 18% |
| VGK | equities | validada | ou_reversion(1.0) ×0.45, tsmom(126) ×0.30, ema_cross(20,100) ×0.25 | 2.07 | 0.35 | 0.66 | 30% |
| EWJ | equities | validada | rsi_reversion(30,55) ×0.44, tsmom(252) ×0.35, ou_reversion(1.0) ×0.21 | 1.71 | 0.10 | 0.47 | 100% |
| EEM | equities | validada | rsi_reversion(25,50)+vt ×0.44, tsmom(126) ×0.30, sma_cross(20,100)+vt ×0.26 | 1.45 | 0.45 | 0.48 | 23% |
| EWP | equities | positiva fuera de muestra pero sin superar el DSR | sma_cross(20,100) ×0.34, trend_sma(200) ×0.33, ema_cross(50,200) ×0.33 | 2.05 | 0.52 | 0.88 | 66% |
| TLT | rates | falla en la prueba final | rsi_reversion(25,50) ×1.00 | 0.13 | -0.67 | -0.94 | 0% |
| IEF | rates | falla en la prueba final | ou_reversion(1.0) ×0.52, rsi_reversion(30,55) ×0.48 | 0.96 | -0.30 | -1.08 | 0% |
| GLD | commodities | validada | sma_cross(20,100) ×0.33, ema_cross(20,100) ×0.33, donchian(55) ×0.33 | 2.51 | 0.12 | 0.06 | 0% |
| SLV | commodities | positiva fuera de muestra pero sin superar el DSR | rsi_reversion(30,55) ×0.36, tsmom(252)+vt ×0.32, sma_cross(50,200) ×0.32 | 2.35 | 0.22 | 0.33 | 48% |
| USO | commodities | falla en la prueba final | ou_reversion(1.0)+vt ×0.52, rsi_reversion(30,55) ×0.48 | 1.19 | -0.08 | 1.50 | 16% |
| UUP | fx | positiva fuera de muestra pero sin superar el DSR | ou_reversion(2.0) ×0.60, rsi_reversion(30,55) ×0.35, sma_cross(20,100) ×0.04 | 0.22 | 0.32 | 0.55 | 4% |
| FXE | fx | falla en la prueba final | ema_cross(10,50) ×0.61, donchian(20) ×0.39 | 1.13 | -1.27 | -0.60 | 0% |
| FXY | fx | falla en la prueba final | ou_reversion(1.0) ×0.71, ema_cross(10,50) ×0.29 | 1.04 | -2.28 | -0.38 | 0% |
| BTC-USD | crypto | falla en la prueba final | rsi_reversion(30,55) ×0.55, ema_cross(50,200) ×0.29, ou_reversion(1.0)+vt ×0.16 | 1.13 | -0.71 | -0.50 | 84% |
| ETH-USD | crypto | falla en la prueba final | rsi_reversion(30,55) ×0.36, donchian(55)+vt ×0.33, tsmom(63)+vt ×0.31 | 1.30 | -1.06 | -0.51 | 36% |
| SOL-USD | crypto | falla en la prueba final | rsi_reversion(30,55)+vt ×0.62, donchian(20)+vt ×0.38 | 0.59 | -1.31 | -0.68 | 21% |

**Lo que aprendió cada mesa:**

- equities: funcionan tsmom, rsi_reversion, trend_sma
- rates: funcionan rsi_reversion, ou_reversion, sma_cross; no funcionan tsmom, ema_cross, trend_sma, donchian
- commodities: funcionan rsi_reversion, tsmom, donchian
- fx: funcionan ema_cross, ou_reversion, sma_cross; no funcionan donchian
- crypto: funcionan rsi_reversion, donchian, tsmom; no funcionan ou_reversion

## Coste 105 pb por operación (cuenta de 200 USD, IBKR fixed)

17 activos · 12 con ventaja en validación · **1 validados** en la prueba final · 0 por encima de comprar y mantener.

| Activo | Mesa | Veredicto | Estrategias del conjunto | Sharpe validación | Sharpe prueba | Comprar y mantener | Exposición hoy |
|---|---|---|---|---|---|---|---|
| SPY | equities | validada | donchian(55)+vt ×0.59, tsmom(252) ×0.21, ema_cross(50,200) ×0.20 | 0.49 | 0.53 | 0.80 | 41% |
| QQQ | equities | falla en la prueba final | donchian(55) ×0.44, trend_sma(200) ×0.39, tsmom(252) ×0.18 | 0.89 | -0.04 | 0.51 | 18% |
| VGK | equities | falla en la prueba final | ou_reversion(1.0) ×0.41, ema_cross(20,100) ×0.31, sma_cross(20,100) ×0.28 | 1.37 | -0.25 | 0.66 | 0% |
| EWJ | equities | falla en la prueba final | rsi_reversion(30,55) ×0.50, tsmom(252) ×0.32, ou_reversion(1.0) ×0.19 | 1.03 | -0.16 | 0.47 | 100% |
| EEM | equities | falla en la prueba final | rsi_reversion(25,50) ×0.49, ou_reversion(1.0) ×0.36, sma_cross(50,200) ×0.14 | 0.78 | -0.00 | 0.48 | 100% |
| EWP | equities | positiva fuera de muestra pero sin superar el DSR | donchian(55) ×0.35, tsmom(252) ×0.34, sma_cross(20,100) ×0.30 | 2.20 | 0.35 | 0.88 | 34% |
| TLT | rates | sin ventaja: ninguna familia gana en validación; el comité usa solo las señales | — | — | — | -0.94 | — |
| IEF | rates | sin ventaja: ninguna familia gana en validación; el comité usa solo las señales | — | — | — | -1.08 | — |
| GLD | commodities | falla en la prueba final | sma_cross(20,100) ×0.33, ema_cross(20,100) ×0.33, donchian(55) ×0.33 | 2.51 | -0.00 | 0.06 | 0% |
| SLV | commodities | positiva fuera de muestra pero sin superar el DSR | sma_cross(50,200) ×0.36, ema_cross(50,200) ×0.36, rsi_reversion(30,55) ×0.28 | 2.11 | 0.25 | 0.33 | 28% |
| USO | commodities | falla en la prueba final | rsi_reversion(30,55) ×0.66, ou_reversion(2.0) ×0.34 | 0.44 | -0.42 | 1.50 | 0% |
| UUP | fx | sin ventaja: ninguna familia gana en validación; el comité usa solo las señales | — | — | — | 0.55 | — |
| FXE | fx | sin ventaja: ninguna familia gana en validación; el comité usa solo las señales | — | — | — | -0.60 | — |
| FXY | fx | sin ventaja: ninguna familia gana en validación; el comité usa solo las señales | — | — | — | -0.38 | — |
| BTC-USD | crypto | falla en la prueba final | rsi_reversion(30,55) ×0.35, ema_cross(50,200) ×0.33, tsmom(252) ×0.33 | 0.78 | -1.58 | -0.50 | 100% |
| ETH-USD | crypto | falla en la prueba final | donchian(55)+vt ×0.50, rsi_reversion(30,55) ×0.44, trend_sma(200) ×0.06 | 0.92 | -1.44 | -0.51 | 44% |
| SOL-USD | crypto | falla en la prueba final | rsi_reversion(30,55)+vt ×0.67, donchian(20)+vt ×0.33 | 0.33 | -1.80 | -0.68 | 23% |

**Lo que aprendió cada mesa:**

- equities: funcionan tsmom, ema_cross, donchian
- rates: ninguna familia gana en validación; no funcionan ou_reversion, sma_cross, rsi_reversion, ema_cross, donchian, tsmom, trend_sma
- commodities: funcionan rsi_reversion, sma_cross, donchian
- fx: ninguna familia gana en validación; no funcionan ou_reversion, ema_cross, donchian, sma_cross, trend_sma, rsi_reversion, tsmom
- crypto: funcionan rsi_reversion, donchian, ema_cross; no funcionan trend_sma, sma_cross, ou_reversion

## Qué sabe cada agente

### Estratega macro

8 papers · funciones quantfin: absorption_ratio, adf_t, duracion_convexidad, sadf · código: agents.macro_regime, agents.systemic_fragility

- Skill **macro-rates-monitor**: Macro analysis synthesizes multiple indicators into a narrative.; Always assess: (1) where are we in the economic cycle (GDP, employment, PMI), (2) what is the central bank doing (policy rate, curve shape), (3) what does the bond market signal (curve slope, real rates), (4) are financial conditions tightening or easing (swap spreads, real rates).; Start broad, drill down.
- Skill **economic-calendar-fetcher**: High Impact: Major market-moving events; FOMC rate decisions, ECB/BOJ policy meetings; Non-Farm Payrolls (NFP), CPI, GDP

### Analista de sentimiento

12 papers · funciones quantfin: — · código: agents.news_sentiment, agents.sanitize_headline

- Skill **llm-trading-agent-security**: External data is sanitized before entering the LLM context; Spend limits are enforced independently from model output; Transactions are simulated before send

### Analistas por mesa

20 papers · funciones quantfin: basis_momentum, black_scholes, brier, carry_trade, garch11, impermanent_loss, lmsr_precio, lvr_producto_constante, momentum_seccion_cruzada, monte_carlo_call, pnl_cobertura, regresion_factores, roll_yield, sadf · código: agents.asset_signals, agents.debate

- Skill **equity-research**: Every piece of data must connect to an investment thesis.; Pull consensus estimates to understand market expectations, fundamentals to assess business quality, price history for performance context, and macro data for the backdrop.; The key question is always: where might consensus be wrong?
- Skill **yfinance-data**: Always wrap in try/except — Yahoo Finance may rate-limit or return empty data; Use yf.download() for multi-ticker comparisons — it's faster with multi-threading; For options, list expiration dates first with ticker.options before calling ticker.option_chain(date)
- Skill **option-vol-analysis**: Always start from the vol surface — it encodes the market's view of future uncertainty across strikes and expiries.; Individual option prices are derived from this surface.; Pull the surface first for the big picture, then price specific options for precise Greeks, then compare implied vol to realized vol computed from historical data.

### Investigador cuant

21 papers · funciones quantfin: ajustar_ns, ajustar_ou, avellaneda_stoikov, deflated_sharpe, ema, kelly_binario, nelson_siegel, senal_donchian, senal_ema, tsmom, vol_target, zscore_pairs · código: training.train_asset, training.apply_book, agents.deflated_sharpe

- Skill **backtesting-frameworks**: Use point-in-time data - Avoid look-ahead bias; Include transaction costs - Realistic estimates; Test out-of-sample - Always reserve data

### CIO

7 papers · funciones quantfin: risk_parity · código: agents.build_portfolio, agents.risk_budget, engine._llm_memo


### Gestor de riesgos

21 papers · funciones quantfin: absorption_ratio, adf_t, diversity_weighted, mejora_sharpe, min_varianza, nearest_correlation, sadf, sesgo_optimizador, sharpe, var_es, vol_target · código: agents.apply_risk, agents.covariance, agents.portfolio_vol, agents.circuit_breaker

- Skill **backtesting-frameworks**: Use point-in-time data - Avoid look-ahead bias; Include transaction costs - Realistic estimates; Test out-of-sample - Always reserve data
- Skill **option-vol-analysis**: Always start from the vol surface — it encodes the market's view of future uncertainty across strikes and expiries.; Individual option prices are derived from this surface.; Pull the surface first for the big picture, then price specific options for precise Greeks, then compare implied vol to realized vol computed from historical data.
- Skill **llm-trading-agent-security**: External data is sanitized before entering the LLM context; Spend limits are enforced independently from model output; Transactions are simulated before send

### Trader

2 papers · funciones quantfin: almgren_chriss, impacto_raiz · código: agents.plan_orders

- Skill **llm-trading-agent-security**: External data is sanitized before entering the LLM context; Spend limits are enforced independently from model output; Transactions are simulated before send
