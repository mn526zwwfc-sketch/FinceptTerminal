# Base de conocimiento de Fincept Lite

Generado con `python -m server.fund.research`. Junta en un solo documento:

- **36 papers del fondo multi-agente** (`server/fund/research.py`).
- **43 papers de quant-finance-research** (`docs/quantfin/vince_quant_videos.csv`; el texto completo está en `docs/quantfin/investigacion.md`).
- **39 funciones de la librería `quantfin`** (`quantfin/`, catálogo en `server/quantfin_catalog.py`).

En total, **83 entradas** sin duplicados. En la terminal: pantalla FUND (panel *Base de conocimiento*), `GET /fund/research`, y las tools `qf_catalog` y `qf_function` (MCP, chat y Laboratorio quantfin en QUANTLIB).

## 1. Papers por tema

### Acciones

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 1993 | Fama y French (1993); Jensen, Kelly y Pedersen (2023) | Alfa y betas de un activo contra factores (tipo Fama-French). | `tools.qf_function` | quantfin |

### Anomalías y sesgos de backtest

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2019 | Lou, Polk y Skouras (2019), JFE (DOI correcto: 10.1016/j.jfineco.2019.03.011) | El momentum gana casi todo de noche; valor y baja volatilidad, de día | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7648745291696327969) |
| 2006 | Ang, Hodrick, Xing y Zhang (2006, Columbia), Journal of Finance | No: las de mayor volatilidad idiosincrática rinden mucho menos, un rompecabezas que sigue sin explicación de consenso | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7667342646741847329) |
| 1999 | Shumway y Warther (1999), Journal of Finance | Al corregir los rendimientos de empresas deslistadas, el "efecto tamaño" en Nasdaq desaparece; usa datos point-in-time | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7654760641697271072) |
| 1989 | Bernard y Thomas (1989); Martineau (2022), Critical Finance Review | El "drift" posterior a resultados ya casi desapareció en acciones grandes desde 2006 | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7678127234648902944) |

### Burbujas, regímenes y riesgo sistémico

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2025 | Cao, Shao, Yan y Geman (2025), Johns Hopkins, preprint | Combina LPPL de Sornette, sentimiento con FinBERT y un índice de atención mediática en un Transformer; probado solo en 32 acciones | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7638388467214339331) |
| 2024 | Shu, Yu y Mulvey (2024, Princeton), J. of Asset Management; Bemporad et al. (2018) | "Statistical jump model": clustering con penalización por cambiar de estado; cambia de señal menos que un HMM y redujo caídas en S&P, DAX y Nikkei | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7665436911741177121) |
| 2015 | Phillips, Shi, Yu: [Testing for Multiple Bubbles: Historical Episodes of Exuberance and Collapse in the S&P 500](https://doi.org/10.1111/iere.12132) | La prueba recursiva SADF detecta un régimen explosivo mientras ocurre (no predice cuándo revienta). / Prueba recursiva (SADF/GSADF) que detecta un régimen explosivo mientras ocurre, pero no predice cuándo revienta | `agents.asset_signals`, `agents.apply_risk`, `tools._qf_bubble`, `tools.qf_bubble_test`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7648366968596122912) |
| 2011 | Kritzman, Li, Page, Rigobon: [Principal Components as a Measure of Systemic Risk](https://doi.org/10.3905/jpm.2011.37.4.112) | El 'absorption ratio' (varianza que absorben los primeros componentes principales) sube antes de las crisis. / "Absorption ratio": cuánta varianza absorben los primeros componentes principales; sube antes de las crisis | `agents.systemic_fragility`, `agents.macro_regime`, `tools._qf_fragility`, `tools.qf_systemic_fragility`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7657337921137020193) |
| 2010 | Dai, Zhang y Zhu (2010), SIAM J. Financial Math | Con regímenes alcista y bajista ocultos, la regla óptima vende cuando la probabilidad de régimen alcista cae bajo un umbral, no según el precio | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7652814545672539425) |
| 1979 | Dickey y Fuller (1979) | Estadístico t de Dickey-Fuller aumentado. | `tools.qf_function` | quantfin |

### Cripto y DeFi

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2022 | Milionis, Moallemi, Roughgarden y Zhang (2022) | Loss-versus-rebalancing anual de un pool x·y = k. | `tools.qf_function` | quantfin |
| 2020 | Uniswap v2 (Adams et al. 2020) | Pérdida impermanente para un cambio de precio ρ. | `tools.qf_function` | quantfin |

### Divisas

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2011 | Lustig, Roussanov y Verdelhan (2011); Menkhoff et al. (2012) | Cartera carry: compra las monedas de tipo alto y vende las de tipo bajo. | `tools.qf_function` | quantfin |

### Eficiencia y estructura del mercado

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2024 | van der Beck, Bouchaud y Villamaina (2024), Harvard WP | En ETFs concentrados, los flujos inflan precios por impacto, y los inversionistas persiguen ese rendimiento inflado | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7683309762619985185) |
| 2022 | Lou y Polk (2022, LSE), RFS | "Comomentum": la correlación anormal entre ganadores y perdedores mide qué tan saturado está el trade y anticipa rendimientos bajos | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7655445298029825312) |
| 2021 | Gabaix y Koijen (2021), NBER WP 28967 | Multiplicador ≈ 5: un dólar que entra a acciones sube la capitalización total unos 5 dólares (working paper, sin revisión por pares) | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7639108958111681825) |
| 2014 | Hanson y Sunderam (2014), RFS | El alfa que queda = desajuste × (1 − fracción de inversionistas que usan la señal); se mide con interés en corto | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7678851890184047905) |
| 2007 | Khandani y Lo (2007, MIT), J. Investment Management | Estrategias de reversión muy apalancadas y concentradas perdieron cerca de 27% en tres días por una liquidación forzada | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7685159240763264289) |
| 2005 | Brunnermeier y Pedersen (2005), Journal of Finance | Si todos saben que un fondo tiene que vender, los demás venden con él y recompran en el fondo | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7671454876953562400) |
| 1990 | De Long et al. (1990); Shleifer y Vishny (1997); Baker y Wurgler (2006) | El sentimiento es ruido, riesgo y señal a la vez; si está alto, se esperan rendimientos bajos en acciones difíciles de valuar | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7647602360021273889) |
| 1981 | Shiller (1981), AER | Los precios son mucho más volátiles que los dividendos que descuentan; citado por el Nobel 2013 | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7658724052189629729) |
| 1980 | Grossman y Stiglitz (1980), AER | Si la información cuesta, un mercado perfectamente eficiente no puede existir: siempre queda algo de alfa | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7638708965861231894) |

### Ejecución y microestructura

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2026 | Bonart: Ley de la raíz cuadrada del impacto de mercado (arXiv 2606.07059) | El impacto de una orden es ∝ σ·√(Q/V) (volatilidad diaria, tamaño, volumen diario). / Explica por qué el impacto ∝ σ√(Q/V) y da una prueba de consistencia para modelos de impacto | `agents.plan_orders`, `tools._qf_impact`, `tools.qf_execution_plan`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7650178525793635616) |
| 2001 | Almgren, Chriss: [Optimal execution of portfolio transactions](https://doi.org/10.21314/jor.2001.041) | Calendario óptimo de liquidación: equilibra impacto y riesgo de precio (TWAP si no hay aversión). / Calendario óptimo de liquidación: TWAP si no hay aversión al riesgo, más cargado al inicio si la hay | `tools._qf_impact`, `tools.qf_execution_plan`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7652137153161415969) |

### Fondo · Analista de sentimiento

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2024 | Kirtac, Germano: [Sentiment trading with large language models](https://doi.org/10.1016/j.frl.2024.105227) | El sentimiento extraído con LLM de 965.375 noticias predice rendimientos mejor que diccionarios. | `agents.news_sentiment` | fondo |
| 2007 | Tetlock: [Giving Content to Investor Sentiment: The Role of Media in the Stock Market](https://doi.org/10.1111/j.1540-6261.2007.01232.x) | El pesimismo de los medios predice presión bajista temporal sobre los precios. | `agents.news_sentiment` | fondo |

### Fondo · Analistas por mesa

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2016 | Daniel, Moskowitz: [Momentum crashes](https://doi.org/10.1016/j.jfineco.2015.12.002) | El momentum sufre caídas bruscas en 'estados de pánico': tras fuertes descensos y con volatilidad alta. | `agents.asset_signals` | fondo |
| 2013 | Asness, Moskowitz, Pedersen: [Value and Momentum Everywhere](https://doi.org/10.1111/jofi.12021) | El momentum aparece en todas las clases de activos y países, con correlación entre ellas. | `agents.asset_signals` | fondo |
| 1993 | Jegadeesh, Titman: [Returns to Buying Winners and Selling Losers](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x) | Los ganadores de 3-12 meses siguen ganando a corto plazo; se omite el último mes por reversión. | `agents.asset_signals`, `agents._strat_momentum`, `tools.qf_function` | fondo |

### Fondo · Arquitectura

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2026 | Huang et al.: [Multi-Agent Debate for Explainable Trading](https://doi.org/10.48550/arxiv.2609.29701) | Fallo principal: 'convergencia complaciente'. Preservar el desacuerdo mejoró el Sharpe en +0,14; mejorar el razonamiento medido no mejoró resultados. | `agents.debate` | fondo |
| 2026 | Miyazaki, Kawahara, Roberts, Zohren: [Toward Expert Investment Teams: A Multi-Agent LLM System with Fine-Grained Trading Tasks](https://doi.org/10.3905/jfds.2026.008) | Descomponer el análisis en tareas finas y concretas mejora el rendimiento ajustado al riesgo frente a roles genéricos. | `agents.asset_signals` | fondo |
| 2025 | Saha, Lyu, Saxena, Zhao, Mehta (BlackRock): [Large Language Model Agents for Investment Management: Foundations, Benchmarks, and Research Frontiers](https://doi.org/10.1145/3768292.3770387) | Revisión del estado del arte de agentes LLM en inversión: cartera, riesgo y generación de estrategias. | `engine._run_cycle` | fondo |
| 2024 | Xiao, Sun, Luo, Wang: [TradingAgents: Multi-Agents LLM Financial Trading Framework](https://doi.org/10.48550/arxiv.2412.20138) | Analistas especializados, investigadores alcistas/bajistas que debaten, trader y equipo de riesgo. | `agents.debate` | fondo |

### Fondo · CIO

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2010 | Maillard, Roncalli, Teïletche: [The Properties of Equally Weighted Risk Contribution Portfolios](https://doi.org/10.3905/jpm.2010.36.4.060) | Igualar contribuciones al riesgo da carteras más diversificadas que pesos iguales. | `agents.build_portfolio`, `agents.risk_budget`, `tools.qf_risk_parity`, `tools.qf_function` | fondo |

### Fondo · CIO / diseño

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2023 | Glasserman, Lin: [Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT Sentiment Analysis](https://doi.org/10.3905/jfds.2023.1.143) | Backtestear señales de un LLM sobre periodos que el modelo vio en su entrenamiento produce sesgo de anticipación. | `engine._llm_memo` | fondo |

### Fondo · Estratega macro

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2019 | Direct Stimulus Payments to Individuals (regla de Sahm) | Si la media de 3 meses del paro sube ≥ 0,5 pp sobre su mínimo de 12 meses, la economía suele estar entrando en recesión. | `agents.macro_regime` | fondo |

### Fondo · Gestor de riesgos

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2025 | Li, Zeng, Xing, Xu, Xu: [HedgeAgents: A Balanced-aware Multi-agent Financial Trading System](https://doi.org/10.1145/3701716.3715232) | Los agentes LLM sufren pérdidas de ~20 % en caídas rápidas; expertos de cobertura por clase de activo y un gestor central mejoran la robustez. | `agents.apply_risk`, `agents.circuit_breaker` | fondo |
| 2024 | DeMiguel, Martín-Utrera, Uppal: [A Multifactor Perspective on Volatility-Managed Portfolios](https://doi.org/10.1111/jofi.13395) | Las versiones de un solo factor fallan fuera de muestra y no sobreviven a costes; solo la versión condicional multifactor lo hace. | `agents.apply_risk` | fondo |
| 2017 | Moreira, Muir: [Volatility-Managed Portfolios](https://doi.org/10.1111/jofi.12513) | Reducir exposición cuando la volatilidad es alta mejora el Sharpe de muchos factores. | `agents.apply_risk` | fondo |

### Fondo · Investigador cuant

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2017 | Hurst, Ooi, Pedersen: [A Century of Evidence on Trend-Following Investing](https://doi.org/10.3905/jpm.2017.44.1.015) | El seguimiento de tendencia multiactivo fue rentable en cada década desde 1880, también en crisis. | `agents._strat_trend`, `agents._strat_tsmom12` | fondo |
| 2016 | Bailey, Borwein, López de Prado, Zhu: [The probability of backtest overfitting](https://doi.org/10.21314/jcf.2016.322) | La probabilidad de que la mejor estrategia in-sample rinda por debajo de la mediana fuera de muestra puede ser alta. | `agents.select_strategy` | fondo |
| 2016 | Harvey, Liu, Zhu: [… and the Cross-Section of Expected Returns](https://doi.org/10.1093/rfs/hhv059) | Con cientos de factores probados, el umbral de significación debe subir (t > 3). | `agents.PLAYBOOK`, `agents.deflated_sharpe` | fondo |
| 2016 | Levine, Pedersen: [Which Trend Is Your Friend?](https://doi.org/10.2469/faj.v72.n3.3) | Cruces de medias móviles y time-series momentum son casi la misma señal con distintos filtros. | `agents._strat_ema`, `agents.select_strategy`, `tools.qf_function` | fondo |
| 2012 | Moskowitz, Ooi, Pedersen: [Time Series Momentum](https://doi.org/10.1016/j.jfineco.2011.11.003) | El rendimiento pasado de 12 meses de un activo predice su rendimiento futuro en renta variable, bonos, divisas y materias primas (58 futuros). | `agents._strat_tsmom12`, `agents.asset_signals`, `tools.qf_function` | fondo |
| 2007 | Faber: [A Quantitative Approach to Tactical Asset Allocation](https://doi.org/10.3905/jwm.2007.674809) | Estar largo solo cuando el precio supera su media de 10 meses reduce el drawdown sin sacrificar mucha rentabilidad. | `agents._strat_trend` | fondo |

### Fondo · Laboratorio quant

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2008 | Avellaneda, Stoikov: [High-frequency trading in a limit order book](https://doi.org/10.1080/14697680701381228) | Un creador de mercado ajusta su precio de reserva según su inventario y la volatilidad. | `tools._qf_mm`, `tools.qf_market_making`, `tools.qf_function` | fondo |
| 1987 | Nelson, Siegel: [Parsimonious Modeling of Yield Curves](https://doi.org/10.1086/296409) | Tres factores (nivel, pendiente, curvatura) describen la curva de tipos. | `tools._qf_curve`, `tools._qf_bond`, `tools.qf_yield_curve`, `tools.qf_function` | fondo |
| 1956 | Kelly: [A New Interpretation of Information Rate](https://doi.org/10.1002/j.1538-7305.1956.tb03809.x) | La fracción óptima a apostar maximiza el crecimiento logarítmico del capital. | `tools._qf_kelly`, `tools.qf_kelly_binary`, `tools.qf_function` | fondo |

### Fondo · Memoria

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2024 | Yu et al.: [FinCon: A Synthesized LLM Multi-Agent System with Conceptual Verbal Reinforcement](https://doi.org/10.52202/079017-4354) | Un gestor que actualiza sus creencias con la experiencia de episodios previos mejora las decisiones. | `agents.update_desk_trust` | fondo |

### Fondo · Seguridad

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2023 | Greshake et al.: [Not What You've Signed Up For: Compromising Real-World LLM-Integrated Applications with Indirect Prompt Injection](https://doi.org/10.1145/3605764.3623985) | El contenido externo que lee un LLM (webs, noticias) puede contener instrucciones que lo secuestren. | `agents.sanitize_headline`, `engine._llm_memo` | fondo |

### Materias primas

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2019 | Boons y Porras Prado (2019) | Momentum del 1.er vencimiento menos el del 2.º. | `tools.qf_function` | quantfin |
| 2006 | Erb y Harvey (2006); Koijen et al. (2018) | Roll yield anualizado (> 0 = backwardation). | `tools.qf_function` | quantfin |

### Mercados de predicción

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2003 | Hanson (2003) | Precios del market maker LMSR de Hanson. | `tools.qf_function` | quantfin |
| 1950 | Brier (1950) | Brier score de unas probabilidades frente al resultado. | `tools.qf_function` | quantfin |

### Portafolios y limpieza de covarianza

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2026 | Bongiorno, Manolakis y Mantegna (2026), J. of Finance and Data Science | RIEnet: red neuronal entrenada de punta a punta para minimizar la varianza; `pip install rienet` | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7684830015623531809) |
| 2024 | Bongiorno y Challet (2024), Quantitative Finance | 10,000 backtests: el "Average Oracle" gana a la contracción no lineal con 19 veces menos rotación | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7673941163413343521) |
| 2022 | Blanchet (Stanford), Chen y Zhou (Columbia) (2022), Management Science | Ridge o Lasso sobre los pesos equivale exactamente a protegerse del peor caso dentro de una bola de Wasserstein | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7687299730002529569) |
| 2022 | Bongiorno y Challet (2022), European J. of Finance | k-BAHC: limpia las direcciones (eigenvectores) con clustering jerárquico; necesita unas 4 veces menos datos | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7655807373725945121) |
| 2022 | Goldberg, Papanicolaou y Shkolnik (2022, Berkeley), SIAM JFM; Goldberg y Kercheval (2023), PNAS | El error grande está en el eigenvector principal; se corrige con contracción tipo James-Stein | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7663208250577390880) |
| 2005 | Fernholz, Karatzas y Kardaras (2005, Columbia), Finance and Stochastics | Teoría estocástica de portafolios: el portafolio ponderado por diversidad le gana al mercado si éste se mantiene diverso | `tools.qf_function` | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7654358350649478432) |
| 2003 | Pafka, Kondor: [Noisy covariance matrices and portfolio optimization II](https://doi.org/10.1016/s0378-4371(02)01499-1) | El riesgo estimado con una covarianza de muestra es (1 − n/T) del real (en desviación típica). / El riesgo que reporta el optimizador es (1 − n/T) del real; con 500 activos y 750 días el real es 3 veces el predicho | `agents.portfolio_vol`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7668319896933109024) |
| 2002 | Higham: [Computing the nearest correlation matrix — a problem from finance](https://doi.org/10.1093/imanum/22.3.329) | La correlación válida más cercana se obtiene con proyecciones alternadas y corrección de Dykstra. / La matriz de correlación válida más cercana se obtiene con proyecciones alternadas y la corrección de Dykstra | `agents.covariance`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7684019834069257504) |
| 1952 | Markowitz (1952); Tobin (1958); Merton (1972); Broadie (1993) | El portafolio tangente maximiza el Sharpe; el error de estimación aleja la frontera calculada de la real / Agregar una estrategia sube tu Sharpe si Sharpe\_nueva > ρ × Sharpe\_tuya; con ρ negativo, incluso una perdedora ayuda | `tools.qf_function` | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7698826024460504352) · [video](https://www.tiktok.com/@vince.quant/video/7691789099467935009) |

### Renta fija

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 1938 | Macaulay (1938); Fabozzi | Precio, duración modificada y convexidad de un bono. | `tools.qf_bond`, `tools.qf_function` | quantfin |

### Riesgo y portafolio

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 1999 | Artzner et al. (1999); Basilea FRTB | VaR y Expected Shortfall históricos. | `analytics.risk_metrics`, `tools.qf_function` | quantfin |
| 1966 | Sharpe (1966) | Sharpe anualizado. | `backtest.perf_metrics`, `tools.qf_function` | quantfin |

### Tendencia y señales

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2025 | Futter, Horvath (Oxford) y Wiese (2025), Quantitative Finance | Cualquier indicador se aproxima con la "firma" de la trayectoria; extiende Markowitz a estrategias que dependen del camino. Librerías: signatory, iisignature | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7685492396775197984) |
| 2018 | Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert: [The Impact of Volatility Targeting](https://doi.org/10.3905/jpm.2018.45.1.014) | El objetivo de volatilidad mejora el Sharpe en activos de riesgo y siempre reduce la volatilidad de la volatilidad. / El volatility targeting mejora el Sharpe en activos de riesgo y siempre reduce la volatilidad de la volatilidad | `agents.apply_risk`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7683702624553536801) |
| 1992 | Brock, Lakonishok, LeBaron: [Simple Technical Trading Rules and the Stochastic Properties of Stock Returns](https://doi.org/10.1111/j.1540-6261.1992.tb04681.x) | Medias móviles y rupturas de rango tuvieron poder predictivo en el Dow Jones (1897-1986); la ventaja en un solo activo se ha erosionado con el tiempo. / El cruce de EMAs es una medida de momentum; la ventaja en un solo activo desapareció, pero el time-series momentum diversificado sigue funcionando | `agents._strat_ema`, `agents._strat_donchian`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7662892707567652129) |
| 1930 | Uhlenbeck, Ornstein: [On the Theory of the Brownian Motion](https://doi.org/10.1103/physrev.36.823) | Proceso de reversión a la media dX = θ(μ − X)dt + σdW, base del pairs trading. / `dX = θ(μ − X)dt + σdW`: modelo clásico de reversión a la media para spreads | `tools._qf_pairs`, `tools.qf_pairs_ou`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7641379783162596640) |
|  | Las mismas referencias + historia de Dennis y Eckhardt | Ruptura del máximo o mínimo de 20 días; las ganancias de los Turtles son historia sin auditar | `agents._strat_donchian`, `tools.qf_function` | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7663589331436719393) |

### Validación de backtests y machine learning

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2024 | Kelly, Malamud y Zhou (2024); críticas de Nagel (2025) y Buncic (2025) | Actualiza la sección 2.1: hay debate abierto sobre si la "virtud de la complejidad" es en realidad un efecto de volatility timing | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7658455214260817184) |
| 2018 | López de Prado (2018), Advances in Financial ML; Bailey et al. (2017) | Validación cruzada combinatoria con purga y embargo: da una distribución de Sharpes y la probabilidad de sobreajuste (PBO) | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7649873862196301089) |
| 2014 | Bailey, López de Prado: [The Deflated Sharpe Ratio](https://doi.org/10.3905/jpm.2014.40.5.094) | Elegir la mejor de N estrategias infla su Sharpe; el DSR corrige por número de pruebas, asimetría y curtosis. / El mejor Sharpe de miles de pruebas es casi siempre suerte; el DSR lo corrige. El MinervaScore no mostró poder predictivo en datos reales y los autores lo publicaron | `agents.deflated_sharpe`, `agents.select_strategy`, `tools.qf_function` | fondo, quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7680314011191201056) |

### Volatilidad, derivados y crédito

| Año | Paper | Idea clave | Código | Fuente |
|---|---|---|---|---|
| 2023 | Guyon y Lekeufack (2023), Quantitative Finance | Con solo rendimientos pasados se explica cerca de 90% de la volatilidad implícita del S&P 500 (dentro de muestra); la volatilidad depende sobre todo de la trayectoria | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7638026616345529622) |
| 2018 | Gatheral, Jaisson y Rosenbaum (2018); Hager, Horst, Wagenhofer y Xu (arXiv 2603.13170, 2026) | Volatilidad "rugosa" con Hurst ≈ 0.1; el preprint de 2026 la deriva del flujo de órdenes | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7641646346843245857) |
| 2000 | Li (2000), Journal of Fixed Income | Cópula gaussiana para CDOs: un solo parámetro de correlación que falló cuando los incumplimientos se agruparon | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7646112181519404320) |
| 1998 | El Karoui, Jeanblanc-Picqué y Shreve (1998), Mathematical Finance | Si cubres con una volatilidad siempre mayor a la real, la cobertura no pierde en ninguna trayectoria | `tools.qf_function` | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7691461932414487841) |
| 1986 | Bollerslev (1986) | Volatilidad condicional GARCH(1,1) de una serie de rendimientos. | `tools.qf_function` | quantfin |
| 1977 | Boyle (1977) | Call europea por Monte Carlo (semilla fija). | `tools.qf_function` | quantfin |
| 1973 | Black y Scholes (1973); Merton (1973) | Precio y griegas de una opción europea. | `analytics.bs_price`, `tools.qf_function` | quantfin |
| 1963 | Mandelbrot (1963); Cont (2001); Gabaix et al. (2003, Nature); Peters (2019) | Simula tus supuestos, no los verifica: colas pesadas, memoria de volatilidad y la diferencia entre la media del conjunto y una trayectoria típica | — | quant-finance-research · [video](https://www.tiktok.com/@vince.quant/video/7650575304817118497) |

## 2. Funciones de quantfin

Todas se pueden ejecutar con `qf_function(function=..., args={...})`; sin `args` corre el ejemplo.

### Acciones

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.momentum_seccion_cruzada` | Pesos long/short por momentum 12-1 (quintiles). | precios, lookback, skip | pesos | Jegadeesh y Titman (1993) | `agents._strat_momentum (misma idea, serie temporal)`, `tools.qf_function` |
| `quantfin.mercados.regresion_factores` | Alfa y betas de un activo contra factores (tipo Fama-French). | r_activo, factores | alfa_y_betas | Fama y French (1993); Jensen, Kelly y Pedersen (2023) | `tools.qf_function` |
### Burbujas, regímenes y riesgo sistémico

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.avanzados.absorption_ratio` | Varianza absorbida por los primeros componentes principales. | retornos, frac | absorption_ratio | Kritzman, Li, Page y Rigobon (2011) | `agents.systemic_fragility`, `agents.macro_regime`, `tools.qf_systemic_fragility`, `tools.qf_function` |
| `quantfin.avanzados.adf_t` | Estadístico t de Dickey-Fuller aumentado. | y | t | Dickey y Fuller (1979) | `quantfin.sadf`, `tools.qf_function` |
| `quantfin.avanzados.sadf` | Sup-ADF: detecta un régimen explosivo. | y, r0 | sadf | Phillips, Shi y Yu (2015) | `agents.asset_signals`, `agents.apply_risk`, `tools.qf_bubble_test`, `tools.qf_function` |
### Cripto y DeFi

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.impermanent_loss` | Pérdida impermanente para un cambio de precio ρ. | ratio_precio | perdida | Uniswap v2 (Adams et al. 2020) | `tools.qf_function` |
| `quantfin.mercados.lvr_producto_constante` | Loss-versus-rebalancing anual de un pool x·y = k. | valor_pool, sigma_anual | lvr_anual | Milionis, Moallemi, Roughgarden y Zhang (2022) | `tools.qf_function` |
### Divisas

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.carry_trade` | Cartera carry: compra las monedas de tipo alto y vende las de tipo bajo. | tasas_extranjeras, tasa_local, n_long, n_short | pesos, carry_esperado | Lustig, Roussanov y Verdelhan (2011); Menkhoff et al. (2012) | `tools.qf_function` |
### Ejecución y microestructura

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.almgren_chriss` | Trayectoria óptima para liquidar X acciones en N pasos. | X, T, N, sigma, eta, lam | trayectoria | Almgren y Chriss (2001) | `tools.qf_execution_plan`, `tools.qf_function` |
| `quantfin.mercados.avellaneda_stoikov` | Bid y ask óptimos de un creador de mercado. | mid, inventario, gamma, sigma, T_rest, k | bid, ask | Avellaneda y Stoikov (2008) | `tools.qf_market_making`, `tools.qf_function` |
| `quantfin.avanzados.impacto_raiz` | Impacto de mercado ∝ σ·√(Q/V). | sigma_diaria, Q, V, Y | impacto | Bonart (2026); ley de la raíz cuadrada (Tóth et al. 2011) | `agents.plan_orders`, `tools.qf_execution_plan`, `tools.qf_function` |
### Materias primas

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.basis_momentum` | Momentum del 1.er vencimiento menos el del 2.º. | f1, f2, ventana | basis_momentum | Boons y Porras Prado (2019) | `tools.qf_function` |
| `quantfin.mercados.roll_yield` | Roll yield anualizado (> 0 = backwardation). | f1, f2, dias_entre_vencimientos | roll_yield | Erb y Harvey (2006); Koijen et al. (2018) | `tools.qf_function` |
### Mercados de predicción

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.brier` | Brier score de unas probabilidades frente al resultado. | prob, resultado | brier | Brier (1950) | `tools.qf_function` |
| `quantfin.mercados.kelly_binario` | Fracción de Kelly para un contrato binario. | p_propia, precio | fraccion | Kelly (1956) | `tools.qf_kelly_binary`, `tools.qf_function` |
| `quantfin.mercados.lmsr_precio` | Precios del market maker LMSR de Hanson. | q, b | precios | Hanson (2003) | `tools.qf_function` |
### Multi-activo

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.tsmom` | Time-series momentum con objetivo de volatilidad. | retornos, vol_obj, lookback | pesos | Moskowitz, Ooi y Pedersen (2012) | `agents._strat_tsmom12`, `tools.qf_function` |
### Portafolios y limpieza de covarianza

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.avanzados.diversity_weighted` | Cartera ponderada por diversidad. | pesos_mercado, p | pesos | Fernholz, Karatzas y Kardaras (2005) | `tools.qf_function` |
| `quantfin.avanzados.mejora_sharpe` | ¿Una estrategia nueva sube el Sharpe de la tuya? (S_nueva > ρ·S_tuya). | sharpe_nueva, sharpe_tuya, rho | mejora | Markowitz (1952) | `tools.qf_function` |
| `quantfin.avanzados.nearest_correlation` | Matriz de correlación válida más cercana (Higham). | A, iters | matriz | Higham (2002) | `agents.covariance`, `tools.qf_function` |
| `quantfin.avanzados.sesgo_optimizador` | Factor (1 − n/T): riesgo predicho frente al real. | n, T | factor | Pafka y Kondor (2003) | `agents.portfolio_vol`, `tools.qf_function` |
### Renta fija

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.ajustar_ns` | Ajusta Nelson-Siegel a una curva observada. | plazos, tasas | nivel, pendiente, curvatura, lambda | Nelson y Siegel (1987) | `tools.qf_yield_curve`, `tools.qf_function` |
| `quantfin.mercados.duracion_convexidad` | Precio, duración modificada y convexidad de un bono. | cupon, ytm, n_anios, freq | precio, duracion_modificada, convexidad | Macaulay (1938); Fabozzi | `tools.qf_bond`, `tools.qf_function` |
| `quantfin.mercados.nelson_siegel` | Curva Nelson-Siegel para unos plazos dados. | tau, b0, b1, b2, lam | tasas | Nelson y Siegel (1987); Diebold y Li (2006) | `tools.qf_yield_curve`, `tools.qf_function` |
### Riesgo y portafolio

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.min_varianza` | Cartera de mínima varianza (Markowitz). | cov | pesos | Markowitz (1952) | `tools.qf_function` |
| `quantfin.mercados.risk_parity` | Pesos de paridad de riesgo (contribuciones iguales). | cov, iters | pesos | Maillard, Roncalli y Teïletche (2010) | `agents.risk_budget`, `tools.qf_risk_parity`, `tools.qf_function` |
| `quantfin.mercados.sharpe` | Sharpe anualizado. | r, freq | sharpe | Sharpe (1966) | `backtest.perf_metrics (equivalente)`, `tools.qf_function` |
| `quantfin.mercados.var_es` | VaR y Expected Shortfall históricos. | retornos, alfa | var, es | Artzner et al. (1999); Basilea FRTB | `analytics.risk_metrics (equivalente)`, `tools.qf_function` |
### Tendencia y señales

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.avanzados.ajustar_ou` | Ajuste Ornstein-Uhlenbeck (θ, μ, σ, vida media). | x, dt | theta, mu, sigma, vida_media | Uhlenbeck y Ornstein (1930) | `tools.qf_pairs_ou`, `tools.qf_function` |
| `quantfin.avanzados.ema` | Media móvil exponencial. | x, span | ema | Brock et al. (1992) | `quantfin.senal_ema`, `tools.qf_function` |
| `quantfin.avanzados.senal_donchian` | Señal de ruptura del canal de Donchian. | precios, n | senal | Brock et al. (1992); historia de Dennis y Eckhardt | `agents._strat_donchian`, `tools.qf_function` |
| `quantfin.avanzados.senal_ema` | Señal de cruce de EMAs (+1/−1). | precios, rapida, lenta | senal | Brock, Lakonishok y LeBaron (1992); Levine y Pedersen (2016) | `agents._strat_ema`, `tools.qf_function` |
| `quantfin.avanzados.vol_target` | Apalancamiento diario para una volatilidad objetivo. | retornos, vol_obj, halflife | apalancamiento | Harvey et al. (2018) | `agents.apply_risk (techo de volatilidad)`, `tools.qf_function` |
| `quantfin.avanzados.zscore_pairs` | Z-score del spread y señal de pairs trading. | spread, mu, sigma, theta, entrada | z, senal | Uhlenbeck y Ornstein (1930); Gatev, Goetzmann y Rouwenhorst (2006) | `tools.qf_pairs_ou`, `tools.qf_function` |
### Validación de backtests y machine learning

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.avanzados.deflated_sharpe` | Probabilidad de que un Sharpe sea real tras probar n estrategias. | r, n_pruebas, var_sharpes | probabilidad | Bailey y López de Prado (2014) | `agents.deflated_sharpe`, `agents.select_strategy`, `tools.qf_function` |
### Volatilidad, derivados y crédito

| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |
|---|---|---|---|---|---|
| `quantfin.mercados.black_scholes` | Precio y griegas de una opción europea. | S, K, T, r, sigma, tipo | precio, delta, gamma, vega | Black y Scholes (1973); Merton (1973) | `analytics.bs_price (misma fórmula)`, `tools.qf_function` |
| `quantfin.mercados.garch11` | Volatilidad condicional GARCH(1,1) de una serie de rendimientos. | r, omega, alpha, beta | volatilidad | Bollerslev (1986) | `tools.qf_function` |
| `quantfin.mercados.monte_carlo_call` | Call europea por Monte Carlo (semilla fija). | S, K, T, r, sigma, n | precio | Boyle (1977) | `tools.qf_function` |
| `quantfin.avanzados.pnl_cobertura` | P&L de cubrir una call con una volatilidad equivocada. | S0, K, T, sig_cob, sig_real, n, sims | pnl_medio, prob_perdida | El Karoui, Jeanblanc-Picqué y Shreve (1998) | `tools.qf_function` |

## 3. Cómo encaja todo

- **Fondo (pantalla FUND):** SADF limita activos en burbuja, el absorption ratio vuelve el régimen defensivo, la paridad de riesgo usa la covarianza (reparada con Higham), la volatilidad se corrige con Pafka-Kondor, las estrategias EMA y Donchian compiten en el playbook y cada orden lleva su impacto estimado con la ley de la raíz cuadrada.
- **Tools:** `qf_bubble_test`, `qf_systemic_fragility`, `qf_pairs_ou`, `qf_risk_parity`, `qf_execution_plan`, `qf_yield_curve`, `qf_bond`, `qf_kelly_binary`, `qf_market_making`, más `qf_catalog` y `qf_function` para las 39 funciones.
- **Investigación completa:** `docs/quantfin/investigacion.md` (mercado por mercado, cursos, librerías y código).

## 4. Cómo se entrenan los agentes

`POST /fund/train`, el botón ENTRENAR AGENTES o la tool `fund_train` (el comité también entrena solo si no hay libro o tiene más de 30 días). Por activo: 60% de 5 años para entrenar, 20% para validar y 20% de prueba final; ejecución en la apertura siguiente y 10 pb por cambio de posición; la mejor configuración de cada familia se elige solo con el tramo de entrenamiento y el Deflated Sharpe penaliza el número de pruebas; las familias que también ganan en validación forman un conjunto (hasta 3).

### Familias de estrategias

| Familia | Estilo | Configuraciones | Papers | Funciones quantfin |
|---|---|---|---|---|
| Precio sobre su media móvil (`trend_sma`) | tendencia | n=100; n=200 (cada una con y sin objetivo de volatilidad) | A Quantitative Approach to Tactical Asset Allocation (2007), A Century of Evidence on Trend-Following Investing (2017) | — |
| Cruce de medias simples (`sma_cross`) | tendencia | fast=20,slow=100; fast=50,slow=200 (cada una con y sin objetivo de volatilidad) | Simple Technical Trading Rules and the Stochastic Properties (1992), A Quantitative Approach to Tactical Asset Allocation (2007) | — |
| Cruce de EMAs (`ema_cross`) | tendencia | fast=10,slow=50; fast=20,slow=100; fast=50,slow=200 (cada una con y sin objetivo de volatilidad) | Simple Technical Trading Rules and the Stochastic Properties (1992), Which Trend Is Your Friend? (2016) | `senal_ema`, `ema` |
| Ruptura del canal de Donchian (`donchian`) | tendencia | n=20; n=55 (cada una con y sin objetivo de volatilidad) | Simple Technical Trading Rules and the Stochastic Properties (1992), Las mismas referencias + historia de Dennis y Eckhardt | `senal_donchian` |
| Time-series momentum (`tsmom`) | tendencia | lookback=63; lookback=126; lookback=252 (cada una con y sin objetivo de volatilidad) | Time Series Momentum (2012), A Century of Evidence on Trend-Following Investing (2017) | `tsmom` |
| Reversión por RSI (regla clásica, sin paper propio en la base) (`rsi_reversion`) | reversión | buy=30,sell=55; buy=25,sell=50 (cada una con y sin objetivo de volatilidad) | — | — |
| Reversión Ornstein-Uhlenbeck (`ou_reversion`) | reversión | entry=1.0; entry=2.0 (cada una con y sin objetivo de volatilidad) | On the Theory of the Brownian Motion (1930) | `ajustar_ou`, `zscore_pairs` |

Objetivo de volatilidad (solo techo, nunca apalanca): The Impact of Volatility Targeting (2018), Volatility-Managed Portfolios (2017), A Multifactor Perspective on Volatility-Managed Po (2024).

### Qué sabe cada agente

| Agente | Skills | Papers | Funciones quantfin | Código |
|---|---|---|---|---|
| Estratega macro | macro-rates-monitor, economic-calendar-fetcher | 8 | absorption_ratio, adf_t, duracion_convexidad, sadf | `agents.macro_regime`, `agents.systemic_fragility` |
| Analista de sentimiento | llm-trading-agent-security | 12 | — | `agents.news_sentiment`, `agents.sanitize_headline` |
| Analistas por mesa | equity-research, yfinance-data, option-vol-analysis | 20 | basis_momentum, black_scholes, brier, carry_trade, garch11, impermanent_loss, lmsr_precio, lvr_producto_constante, momentum_seccion_cruzada, monte_carlo_call, pnl_cobertura, regresion_factores, roll_yield, sadf | `agents.asset_signals`, `agents.debate` |
| Investigador cuant | backtesting-frameworks | 21 | ajustar_ns, ajustar_ou, avellaneda_stoikov, deflated_sharpe, ema, kelly_binario, nelson_siegel, senal_donchian, senal_ema, tsmom, vol_target, zscore_pairs | `training.train_asset`, `training.apply_book`, `agents.deflated_sharpe` |
| CIO | — | 7 | risk_parity | `agents.build_portfolio`, `agents.risk_budget`, `engine._llm_memo` |
| Gestor de riesgos | backtesting-frameworks, option-vol-analysis, llm-trading-agent-security | 21 | absorption_ratio, adf_t, diversity_weighted, mejora_sharpe, min_varianza, nearest_correlation, sadf, sesgo_optimizador, sharpe, var_es, vol_target | `agents.apply_risk`, `agents.covariance`, `agents.portfolio_vol`, `agents.circuit_breaker` |
| Trader | llm-trading-agent-security | 2 | almgren_chriss, impacto_raiz | `agents.plan_orders` |

Skills de plataforma (construyen la terminal, no deciden inversiones): fastapi, mcp-builder.
