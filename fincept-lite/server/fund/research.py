"""Base de investigación del fondo: qué paper respalda cada regla y dónde se aplica.

Todas las referencias se verificaron en OpenAlex el 2026-11-10 (el DOI resuelve al
trabajo; citas a esa fecha). El año es el del número de la revista: OpenAlex a veces
muestra el de la versión online (p. ej. 2011 para Moskowitz et al., JFE 2012). La única que OpenAlex no indexa (la regla de Sahm, un informe
de política del Hamilton Project) va marcada con verified=False.

`applied_in` apunta a funciones reales del código; un test comprueba que existen,
para que esta tabla no se desincronice del motor.
"""

from __future__ import annotations

REFERENCES: list[dict] = [
    # ── Momentum y tendencia (investigador cuant / analistas) ──────────────
    {"id": "moskowitz2012", "title": "Time Series Momentum", "authors": "Moskowitz, Ooi, Pedersen", "year": 2012,
     "venue": "Journal of Financial Economics", "doi": "10.1016/j.jfineco.2011.11.003", "openalex": "W3124639629",
     "cited_by": 1484, "verified": True, "agent": "Investigador cuant",
     "finding": "El rendimiento pasado de 12 meses de un activo predice su rendimiento futuro en renta variable, bonos, "
                "divisas y materias primas (58 futuros).",
     "applied": "Estrategia tsmom_12m del playbook y componente de momentum 12-1 de los analistas.",
     "applied_in": ["agents._strat_tsmom12", "agents.asset_signals"]},
    {"id": "hurst2017", "title": "A Century of Evidence on Trend-Following Investing", "authors": "Hurst, Ooi, Pedersen",
     "year": 2017, "venue": "Journal of Portfolio Management", "doi": "10.3905/jpm.2017.44.1.015",
     "openalex": "W2371440349", "cited_by": 226, "verified": True, "agent": "Investigador cuant",
     "finding": "El seguimiento de tendencia multiactivo fue rentable en cada década desde 1880, también en crisis.",
     "applied": "Universo multiactivo global y estrategias de tendencia (trend_200d, sma_50_200, tsmom_12m).",
     "applied_in": ["agents._strat_trend", "agents._strat_tsmom12"]},
    {"id": "faber2007", "title": "A Quantitative Approach to Tactical Asset Allocation", "authors": "Faber",
     "year": 2007, "venue": "Journal of Wealth Management", "doi": "10.3905/jwm.2007.674809",
     "openalex": "W4214932556", "cited_by": 162, "verified": True, "agent": "Investigador cuant",
     "finding": "Estar largo solo cuando el precio supera su media de 10 meses reduce el drawdown sin sacrificar "
                "mucha rentabilidad.",
     "applied": "Estrategia trend_200d (≈ media de 10 meses en sesiones).", "applied_in": ["agents._strat_trend"]},
    {"id": "jegadeesh1993", "title": "Returns to Buying Winners and Selling Losers", "authors": "Jegadeesh, Titman",
     "year": 1993, "venue": "Journal of Finance", "doi": "10.1111/j.1540-6261.1993.tb04702.x",
     "openalex": "W2125520394", "cited_by": 11519, "verified": True, "agent": "Analistas por mesa",
     "finding": "Los ganadores de 3-12 meses siguen ganando a corto plazo; se omite el último mes por reversión.",
     "applied": "Momentum 12-1 (excluye el último mes) en asset_signals.", "applied_in": ["agents.asset_signals"]},
    {"id": "asness2013", "title": "Value and Momentum Everywhere", "authors": "Asness, Moskowitz, Pedersen",
     "year": 2013, "venue": "Journal of Finance", "doi": "10.1111/jofi.12021", "openalex": "W2320868325",
     "cited_by": 2212, "verified": True, "agent": "Analistas por mesa",
     "finding": "El momentum aparece en todas las clases de activos y países, con correlación entre ellas.",
     "applied": "Mismo motor de señales para las cinco mesas.", "applied_in": ["agents.asset_signals"]},
    {"id": "daniel2016", "title": "Momentum crashes", "authors": "Daniel, Moskowitz", "year": 2016,
     "venue": "Journal of Financial Economics", "doi": "10.1016/j.jfineco.2015.12.002", "openalex": "W4250762315",
     "cited_by": 911, "verified": True, "agent": "Analistas por mesa",
     "finding": "El momentum sufre caídas bruscas en 'estados de pánico': tras fuertes descensos y con volatilidad alta.",
     "applied": "Detector de estado de pánico que reduce a la mitad el componente de momentum.",
     "applied_in": ["agents.asset_signals"]},
    # ── Sobreajuste y validación (investigador cuant) ──────────────────────
    {"id": "bailey2014", "title": "The Deflated Sharpe Ratio", "authors": "Bailey, López de Prado", "year": 2014,
     "venue": "Journal of Portfolio Management", "doi": "10.3905/jpm.2014.40.5.094", "openalex": "W3124863268",
     "cited_by": 178, "verified": True, "agent": "Investigador cuant",
     "finding": "Elegir la mejor de N estrategias infla su Sharpe; el DSR corrige por número de pruebas, asimetría "
                "y curtosis.",
     "applied": "deflated_sharpe() en la selección: una estrategia solo se valida con DSR ≥ 0,5 y Sharpe OOS > 0.",
     "applied_in": ["agents.deflated_sharpe", "agents.select_strategy"]},
    {"id": "bailey2016", "title": "The probability of backtest overfitting", "authors": "Bailey, Borwein, López de "
     "Prado, Zhu", "year": 2016, "venue": "Journal of Computational Finance", "doi": "10.21314/jcf.2016.322",
     "openalex": "W2732395805", "cited_by": 176, "verified": True, "agent": "Investigador cuant",
     "finding": "La probabilidad de que la mejor estrategia in-sample rinda por debajo de la mediana fuera de muestra "
                "puede ser alta.",
     "applied": "Selección in-sample + validación en el 30 % reservado (y walk-forward en el backtester).",
     "applied_in": ["agents.select_strategy"]},
    {"id": "harvey2016", "title": "… and the Cross-Section of Expected Returns", "authors": "Harvey, Liu, Zhu",
     "year": 2016, "venue": "Review of Financial Studies", "doi": "10.1093/rfs/hhv059", "openalex": "W4211170237",
     "cited_by": 2139, "verified": True, "agent": "Investigador cuant",
     "finding": "Con cientos de factores probados, el umbral de significación debe subir (t > 3).",
     "applied": "El playbook se limita a 5 estrategias con base académica y se penaliza el número de pruebas.",
     "applied_in": ["agents.PLAYBOOK", "agents.deflated_sharpe"]},
    # ── Riesgo y construcción de cartera ───────────────────────────────────
    {"id": "moreira2017", "title": "Volatility-Managed Portfolios", "authors": "Moreira, Muir", "year": 2017,
     "venue": "Journal of Finance", "doi": "10.1111/jofi.12513", "openalex": "W2614466292", "cited_by": 572,
     "verified": True, "agent": "Gestor de riesgos",
     "finding": "Reducir exposición cuando la volatilidad es alta mejora el Sharpe de muchos factores.",
     "applied": "Objetivo de volatilidad de la cartera (10 %).", "applied_in": ["agents.apply_risk"]},
    {"id": "demiguel2024", "title": "A Multifactor Perspective on Volatility-Managed Portfolios",
     "authors": "DeMiguel, Martín-Utrera, Uppal", "year": 2024, "venue": "Journal of Finance",
     "doi": "10.1111/jofi.13395", "openalex": "W4403804186", "cited_by": 68, "verified": True,
     "agent": "Gestor de riesgos",
     "finding": "Las versiones de un solo factor fallan fuera de muestra y no sobreviven a costes; solo la versión "
                "condicional multifactor lo hace.",
     "applied": "El objetivo de volatilidad es solo un TECHO (nunca apalanca para alcanzarlo).",
     "applied_in": ["agents.apply_risk"]},
    {"id": "maillard2010", "title": "The Properties of Equally Weighted Risk Contribution Portfolios",
     "authors": "Maillard, Roncalli, Teïletche", "year": 2010, "venue": "Journal of Portfolio Management",
     "doi": "10.3905/jpm.2010.36.4.060", "openalex": "W3124443460", "cited_by": 744, "verified": True,
     "agent": "CIO", "finding": "Igualar contribuciones al riesgo da carteras más diversificadas que pesos iguales.",
     "applied": "Pesos ∝ 1/volatilidad (aproximación de paridad de riesgo).", "applied_in": ["agents.build_portfolio"]},
    # ── Macro y sentimiento ────────────────────────────────────────────────
    {"id": "sahm2019", "title": "Direct Stimulus Payments to Individuals (regla de Sahm)", "authors": "Sahm",
     "year": 2019, "venue": "The Hamilton Project (Brookings), informe de política", "doi": None, "openalex": None,
     "cited_by": None, "verified": False, "agent": "Estratega macro",
     "finding": "Si la media de 3 meses del paro sube ≥ 0,5 pp sobre su mínimo de 12 meses, la economía suele "
                "estar entrando en recesión.",
     "applied": "Regla de Sahm en macro_regime (no indexado en OpenAlex: informe de política, no paper).",
     "applied_in": ["agents.macro_regime"]},
    {"id": "tetlock2007", "title": "Giving Content to Investor Sentiment: The Role of Media in the Stock Market",
     "authors": "Tetlock", "year": 2007, "venue": "Journal of Finance", "doi": "10.1111/j.1540-6261.2007.01232.x",
     "openalex": "W3122944446", "cited_by": 4972, "verified": True, "agent": "Analista de sentimiento",
     "finding": "El pesimismo de los medios predice presión bajista temporal sobre los precios.",
     "applied": "Inclinación por sentimiento, acotada a ±0,1 por su carácter transitorio.",
     "applied_in": ["agents.news_sentiment"]},
    {"id": "kirtac2024", "title": "Sentiment trading with large language models", "authors": "Kirtac, Germano",
     "year": 2024, "venue": "Finance Research Letters", "doi": "10.1016/j.frl.2024.105227", "openalex": "W4392859372",
     "cited_by": 159, "verified": True, "agent": "Analista de sentimiento",
     "finding": "El sentimiento extraído con LLM de 965.375 noticias predice rendimientos mejor que diccionarios.",
     "applied": "Mejora futura identificada: hoy el sentimiento usa un léxico; un LLM podría puntuar titulares.",
     "applied_in": ["agents.news_sentiment"]},
    {"id": "glasserman2023", "title": "Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT "
     "Sentiment Analysis", "authors": "Glasserman, Lin", "year": 2023, "venue": "Journal of Financial Data Science",
     "doi": "10.3905/jfds.2023.1.143", "openalex": "W4389850936", "cited_by": 36, "verified": True,
     "agent": "CIO / diseño",
     "finding": "Backtestear señales de un LLM sobre periodos que el modelo vio en su entrenamiento produce "
                "sesgo de anticipación.",
     "applied": "Ninguna decisión ni backtest depende del LLM: solo redacta el acta.", "applied_in": ["engine._llm_memo"]},
    # ── Sistemas multi-agente con LLM (2024-2026) ──────────────────────────
    {"id": "xiao2024", "title": "TradingAgents: Multi-Agents LLM Financial Trading Framework",
     "authors": "Xiao, Sun, Luo, Wang", "year": 2024, "venue": "arXiv", "doi": "10.48550/arxiv.2412.20138",
     "openalex": "W4405955490", "cited_by": 277, "verified": True, "agent": "Arquitectura",
     "finding": "Analistas especializados, investigadores alcistas/bajistas que debaten, trader y equipo de riesgo.",
     "applied": "Estructura del comité y debate alcista/bajista por activo.", "applied_in": ["agents.debate"]},
    {"id": "huang2026", "title": "Multi-Agent Debate for Explainable Trading", "authors": "Huang et al.",
     "year": 2026, "venue": "arXiv", "doi": "10.48550/arxiv.2609.29701", "openalex": "W7214311441",
     "cited_by": 1, "verified": True, "agent": "Arquitectura",
     "finding": "Fallo principal: 'convergencia complaciente'. Preservar el desacuerdo mejoró el Sharpe en +0,14; "
                "mejorar el razonamiento medido no mejoró resultados.",
     "applied": "Los agentes no ven las opiniones de los demás; el desacuerdo entre señales se mide y se reporta.",
     "applied_in": ["agents.debate"]},
    {"id": "miyazaki2026", "title": "Toward Expert Investment Teams: A Multi-Agent LLM System with Fine-Grained "
     "Trading Tasks", "authors": "Miyazaki, Kawahara, Roberts, Zohren", "year": 2026,
     "venue": "Journal of Financial Data Science", "doi": "10.3905/jfds.2026.008", "openalex": "W7164900891",
     "cited_by": 10, "verified": True, "agent": "Arquitectura",
     "finding": "Descomponer el análisis en tareas finas y concretas mejora el rendimiento ajustado al riesgo "
                "frente a roles genéricos.",
     "applied": "Cada analista calcula métricas concretas (tendencia, momentum 12-1, RSI, vol 20/60, drawdown).",
     "applied_in": ["agents.asset_signals"]},
    {"id": "li2025", "title": "HedgeAgents: A Balanced-aware Multi-agent Financial Trading System",
     "authors": "Li, Zeng, Xing, Xu, Xu", "year": 2025, "venue": "WWW 2025 (ACM)", "doi": "10.1145/3701716.3715232",
     "openalex": "W4410636586", "cited_by": 33, "verified": True, "agent": "Gestor de riesgos",
     "finding": "Los agentes LLM sufren pérdidas de ~20 % en caídas rápidas; expertos de cobertura por clase de "
                "activo y un gestor central mejoran la robustez.",
     "applied": "Mesas por clase de activo con límites propios + cortacircuitos de drawdown.",
     "applied_in": ["agents.apply_risk", "agents.circuit_breaker"]},
    {"id": "yu2024", "title": "FinCon: A Synthesized LLM Multi-Agent System with Conceptual Verbal Reinforcement",
     "authors": "Yu et al.", "year": 2024, "venue": "NeurIPS 2024", "doi": "10.52202/079017-4354",
     "openalex": "W4415800455", "cited_by": 123, "verified": True, "agent": "Memoria",
     "finding": "Un gestor que actualiza sus creencias con la experiencia de episodios previos mejora las decisiones.",
     "applied": "Confianza por mesa actualizada con el acierto de los ciclos anteriores.",
     "applied_in": ["agents.update_desk_trust"]},
    {"id": "saha2025", "title": "Large Language Model Agents for Investment Management: Foundations, Benchmarks, "
     "and Research Frontiers", "authors": "Saha, Lyu, Saxena, Zhao, Mehta (BlackRock)", "year": 2025,
     "venue": "ICAIF 2025 (ACM)", "doi": "10.1145/3768292.3770387", "openalex": "W4416195096", "cited_by": 12,
     "verified": True, "agent": "Arquitectura",
     "finding": "Revisión del estado del arte de agentes LLM en inversión: cartera, riesgo y generación de estrategias.",
     "applied": "Marco general del diseño.", "applied_in": ["engine._run_cycle"]},
    # ── Seguridad ──────────────────────────────────────────────────────────
    {"id": "greshake2023", "title": "Not What You've Signed Up For: Compromising Real-World LLM-Integrated "
     "Applications with Indirect Prompt Injection", "authors": "Greshake et al.", "year": 2023,
     "venue": "ACM AISec 2023", "doi": "10.1145/3605764.3623985", "openalex": "W4388886073", "cited_by": 1853,
     "verified": True, "agent": "Seguridad",
     "finding": "El contenido externo que lee un LLM (webs, noticias) puede contener instrucciones que lo secuestren.",
     "applied": "Titulares saneados y descartados si parecen órdenes; el LLM no tiene herramientas ni recibe titulares.",
     "applied_in": ["agents.sanitize_headline", "engine._llm_memo"]},
]

BY_ID = {r["id"]: r for r in REFERENCES}


def cite(*ids: str) -> list[dict]:
    """Referencias compactas para adjuntar a una decisión del informe."""
    return [{"id": i, "short": f"{BY_ID[i]['authors'].split(',')[0].split(' et')[0]} ({BY_ID[i]['year']})",
             "doi": BY_ID[i]["doi"]} for i in ids if i in BY_ID]
