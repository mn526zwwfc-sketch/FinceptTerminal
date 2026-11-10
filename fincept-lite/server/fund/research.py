"""Base de conocimiento del fondo: papers, investigación y código en un solo sitio.

Junta tres fuentes:
* `REFERENCES`: los papers que respaldan cada regla del fondo (qué agente la usa y dónde).
* `docs/quantfin/vince_quant_videos.csv`: los 43 papers de quant-finance-research.
* `server/quantfin_catalog.py`: las 39 funciones de quantfin y sus papers.

`knowledge_base()` las fusiona (un paper que aparece en varias fuentes queda una sola
vez) y `applied_in` apunta a funciones reales del código; un test comprueba que existen.
`python -m server.fund.research` regenera docs/BASE_DE_CONOCIMIENTO.md.
"""

from __future__ import annotations

QF = "quantfin (quant-finance-research, A. Ortega)"  # origen de las referencias integradas desde ella

REFERENCES: list[dict] = [
    # ── Momentum y tendencia (investigador cuant / analistas) ──────────────
    {"id": "moskowitz2012", "title": "Time Series Momentum", "authors": "Moskowitz, Ooi, Pedersen", "year": 2012,
     "venue": "Journal of Financial Economics", "doi": "10.1016/j.jfineco.2011.11.003", "cited_by": 1484, "agent": "Investigador cuant",
     "finding": "El rendimiento pasado de 12 meses de un activo predice su rendimiento futuro en renta variable, bonos, "
                "divisas y materias primas (58 futuros).",
     "applied": "Estrategia tsmom_12m del playbook y componente de momentum 12-1 de los analistas.",
     "applied_in": ["agents._strat_tsmom12", "agents.asset_signals"]},
    {"id": "hurst2017", "title": "A Century of Evidence on Trend-Following Investing", "authors": "Hurst, Ooi, Pedersen",
     "year": 2017, "venue": "Journal of Portfolio Management", "doi": "10.3905/jpm.2017.44.1.015",
     "cited_by": 226, "agent": "Investigador cuant",
     "finding": "El seguimiento de tendencia multiactivo fue rentable en cada década desde 1880, también en crisis.",
     "applied": "Universo multiactivo global y estrategias de tendencia (trend_200d, sma_50_200, tsmom_12m).",
     "applied_in": ["agents._strat_trend", "agents._strat_tsmom12"]},
    {"id": "faber2007", "title": "A Quantitative Approach to Tactical Asset Allocation", "authors": "Faber",
     "year": 2007, "venue": "Journal of Wealth Management", "doi": "10.3905/jwm.2007.674809",
     "cited_by": 162, "agent": "Investigador cuant",
     "finding": "Estar largo solo cuando el precio supera su media de 10 meses reduce el drawdown sin sacrificar "
                "mucha rentabilidad.",
     "applied": "Estrategia trend_200d (≈ media de 10 meses en sesiones).", "applied_in": ["agents._strat_trend"]},
    {"id": "jegadeesh1993", "title": "Returns to Buying Winners and Selling Losers", "authors": "Jegadeesh, Titman",
     "year": 1993, "venue": "Journal of Finance", "doi": "10.1111/j.1540-6261.1993.tb04702.x",
     "cited_by": 11519, "agent": "Analistas por mesa",
     "finding": "Los ganadores de 3-12 meses siguen ganando a corto plazo; se omite el último mes por reversión.",
     "applied": "Momentum 12-1 (excluye el último mes) en asset_signals.", "applied_in": ["agents.asset_signals"]},
    {"id": "asness2013", "title": "Value and Momentum Everywhere", "authors": "Asness, Moskowitz, Pedersen",
     "year": 2013, "venue": "Journal of Finance", "doi": "10.1111/jofi.12021", "cited_by": 2212, "agent": "Analistas por mesa",
     "finding": "El momentum aparece en todas las clases de activos y países, con correlación entre ellas.",
     "applied": "Mismo motor de señales para las cinco mesas.", "applied_in": ["agents.asset_signals"]},
    {"id": "daniel2016", "title": "Momentum crashes", "authors": "Daniel, Moskowitz", "year": 2016,
     "venue": "Journal of Financial Economics", "doi": "10.1016/j.jfineco.2015.12.002", "cited_by": 911, "agent": "Analistas por mesa",
     "finding": "El momentum sufre caídas bruscas en 'estados de pánico': tras fuertes descensos y con volatilidad alta.",
     "applied": "Detector de estado de pánico que reduce a la mitad el componente de momentum.",
     "applied_in": ["agents.asset_signals"]},
    # ── Sobreajuste y validación (investigador cuant) ──────────────────────
    {"id": "bailey2014", "title": "The Deflated Sharpe Ratio", "authors": "Bailey, López de Prado", "year": 2014,
     "venue": "Journal of Portfolio Management", "doi": "10.3905/jpm.2014.40.5.094", "cited_by": 178, "agent": "Investigador cuant",
     "finding": "Elegir la mejor de N estrategias infla su Sharpe; el DSR corrige por número de pruebas, asimetría "
                "y curtosis.",
     "applied": "deflated_sharpe() en la selección: una estrategia solo se valida con DSR ≥ 0,5 y Sharpe OOS > 0.",
     "applied_in": ["agents.deflated_sharpe", "agents.select_strategy"]},
    {"id": "bailey2016", "title": "The probability of backtest overfitting", "authors": "Bailey, Borwein, López de "
     "Prado, Zhu", "year": 2016, "venue": "Journal of Computational Finance", "doi": "10.21314/jcf.2016.322",
     "cited_by": 176, "agent": "Investigador cuant",
     "finding": "La probabilidad de que la mejor estrategia in-sample rinda por debajo de la mediana fuera de muestra "
                "puede ser alta.",
     "applied": "Selección in-sample + validación en el 30 % reservado (y walk-forward en el backtester).",
     "applied_in": ["agents.select_strategy"]},
    {"id": "harvey2016", "title": "… and the Cross-Section of Expected Returns", "authors": "Harvey, Liu, Zhu",
     "year": 2016, "venue": "Review of Financial Studies", "doi": "10.1093/rfs/hhv059", "cited_by": 2139, "agent": "Investigador cuant",
     "finding": "Con cientos de factores probados, el umbral de significación debe subir (t > 3).",
     "applied": "El playbook se limita a 5 estrategias con base académica y se penaliza el número de pruebas.",
     "applied_in": ["agents.PLAYBOOK", "agents.deflated_sharpe"]},
    # ── Riesgo y construcción de cartera ───────────────────────────────────
    {"id": "moreira2017", "title": "Volatility-Managed Portfolios", "authors": "Moreira, Muir", "year": 2017,
     "venue": "Journal of Finance", "doi": "10.1111/jofi.12513", "cited_by": 572,
     "agent": "Gestor de riesgos",
     "finding": "Reducir exposición cuando la volatilidad es alta mejora el Sharpe de muchos factores.",
     "applied": "Objetivo de volatilidad de la cartera (10 %).", "applied_in": ["agents.apply_risk"]},
    {"id": "demiguel2024", "title": "A Multifactor Perspective on Volatility-Managed Portfolios",
     "authors": "DeMiguel, Martín-Utrera, Uppal", "year": 2024, "venue": "Journal of Finance",
     "doi": "10.1111/jofi.13395", "cited_by": 68, "agent": "Gestor de riesgos",
     "finding": "Las versiones de un solo factor fallan fuera de muestra y no sobreviven a costes; solo la versión "
                "condicional multifactor lo hace.",
     "applied": "El objetivo de volatilidad es solo un TECHO (nunca apalanca para alcanzarlo).",
     "applied_in": ["agents.apply_risk"]},
    {"id": "maillard2010", "title": "The Properties of Equally Weighted Risk Contribution Portfolios",
     "authors": "Maillard, Roncalli, Teïletche", "year": 2010, "venue": "Journal of Portfolio Management",
     "doi": "10.3905/jpm.2010.36.4.060", "cited_by": 744, "agent": "CIO", "finding": "Igualar contribuciones al riesgo da carteras más diversificadas que pesos iguales.",
     "applied": "Pesos ∝ 1/volatilidad (aproximación de paridad de riesgo).", "applied_in": ["agents.build_portfolio"]},
    # ── Macro y sentimiento ────────────────────────────────────────────────
    {"id": "sahm2019", "title": "Direct Stimulus Payments to Individuals (regla de Sahm)", "authors": "Sahm",
     "year": 2019, "venue": "The Hamilton Project (Brookings), informe de política", "doi": None, "cited_by": None, "agent": "Estratega macro",
     "finding": "Si la media de 3 meses del paro sube ≥ 0,5 pp sobre su mínimo de 12 meses, la economía suele "
                "estar entrando en recesión.",
     "applied": "Regla de Sahm en macro_regime.",
     "applied_in": ["agents.macro_regime"]},
    {"id": "tetlock2007", "title": "Giving Content to Investor Sentiment: The Role of Media in the Stock Market",
     "authors": "Tetlock", "year": 2007, "venue": "Journal of Finance", "doi": "10.1111/j.1540-6261.2007.01232.x",
     "cited_by": 4972, "agent": "Analista de sentimiento",
     "finding": "El pesimismo de los medios predice presión bajista temporal sobre los precios.",
     "applied": "Inclinación por sentimiento, acotada a ±0,1 por su carácter transitorio.",
     "applied_in": ["agents.news_sentiment"]},
    {"id": "kirtac2024", "title": "Sentiment trading with large language models", "authors": "Kirtac, Germano",
     "year": 2024, "venue": "Finance Research Letters", "doi": "10.1016/j.frl.2024.105227", "cited_by": 159, "agent": "Analista de sentimiento",
     "finding": "El sentimiento extraído con LLM de 965.375 noticias predice rendimientos mejor que diccionarios.",
     "applied": "Mejora futura identificada: hoy el sentimiento usa un léxico; un LLM podría puntuar titulares.",
     "applied_in": ["agents.news_sentiment"]},
    {"id": "glasserman2023", "title": "Assessing Look-Ahead Bias in Stock Return Predictions Generated by GPT "
     "Sentiment Analysis", "authors": "Glasserman, Lin", "year": 2023, "venue": "Journal of Financial Data Science",
     "doi": "10.3905/jfds.2023.1.143", "cited_by": 36, "agent": "CIO / diseño",
     "finding": "Backtestear señales de un LLM sobre periodos que el modelo vio en su entrenamiento produce "
                "sesgo de anticipación.",
     "applied": "Ninguna decisión ni backtest depende del LLM: solo redacta el acta.", "applied_in": ["engine._llm_memo"]},
    # ── Sistemas multi-agente con LLM (2024-2026) ──────────────────────────
    {"id": "xiao2024", "title": "TradingAgents: Multi-Agents LLM Financial Trading Framework",
     "authors": "Xiao, Sun, Luo, Wang", "year": 2024, "venue": "arXiv", "doi": "10.48550/arxiv.2412.20138",
     "cited_by": 277, "agent": "Arquitectura",
     "finding": "Analistas especializados, investigadores alcistas/bajistas que debaten, trader y equipo de riesgo.",
     "applied": "Estructura del comité y debate alcista/bajista por activo.", "applied_in": ["agents.debate"]},
    {"id": "huang2026", "title": "Multi-Agent Debate for Explainable Trading", "authors": "Huang et al.",
     "year": 2026, "venue": "arXiv", "doi": "10.48550/arxiv.2609.29701", "cited_by": 1, "agent": "Arquitectura",
     "finding": "Fallo principal: 'convergencia complaciente'. Preservar el desacuerdo mejoró el Sharpe en +0,14; "
                "mejorar el razonamiento medido no mejoró resultados.",
     "applied": "Los agentes no ven las opiniones de los demás; el desacuerdo entre señales se mide y se reporta.",
     "applied_in": ["agents.debate"]},
    {"id": "miyazaki2026", "title": "Toward Expert Investment Teams: A Multi-Agent LLM System with Fine-Grained "
     "Trading Tasks", "authors": "Miyazaki, Kawahara, Roberts, Zohren", "year": 2026,
     "venue": "Journal of Financial Data Science", "doi": "10.3905/jfds.2026.008", "cited_by": 10, "agent": "Arquitectura",
     "finding": "Descomponer el análisis en tareas finas y concretas mejora el rendimiento ajustado al riesgo "
                "frente a roles genéricos.",
     "applied": "Cada analista calcula métricas concretas (tendencia, momentum 12-1, RSI, vol 20/60, drawdown).",
     "applied_in": ["agents.asset_signals"]},
    {"id": "li2025", "title": "HedgeAgents: A Balanced-aware Multi-agent Financial Trading System",
     "authors": "Li, Zeng, Xing, Xu, Xu", "year": 2025, "venue": "WWW 2025 (ACM)", "doi": "10.1145/3701716.3715232",
     "cited_by": 33, "agent": "Gestor de riesgos",
     "finding": "Los agentes LLM sufren pérdidas de ~20 % en caídas rápidas; expertos de cobertura por clase de "
                "activo y un gestor central mejoran la robustez.",
     "applied": "Mesas por clase de activo con límites propios + cortacircuitos de drawdown.",
     "applied_in": ["agents.apply_risk", "agents.circuit_breaker"]},
    {"id": "yu2024", "title": "FinCon: A Synthesized LLM Multi-Agent System with Conceptual Verbal Reinforcement",
     "authors": "Yu et al.", "year": 2024, "venue": "NeurIPS 2024", "doi": "10.52202/079017-4354",
     "cited_by": 123, "agent": "Memoria",
     "finding": "Un gestor que actualiza sus creencias con la experiencia de episodios previos mejora las decisiones.",
     "applied": "Confianza por mesa actualizada con el acierto de los ciclos anteriores.",
     "applied_in": ["agents.update_desk_trust"]},
    {"id": "saha2025", "title": "Large Language Model Agents for Investment Management: Foundations, Benchmarks, "
     "and Research Frontiers", "authors": "Saha, Lyu, Saxena, Zhao, Mehta (BlackRock)", "year": 2025,
     "venue": "ICAIF 2025 (ACM)", "doi": "10.1145/3768292.3770387", "cited_by": 12,
     "agent": "Arquitectura",
     "finding": "Revisión del estado del arte de agentes LLM en inversión: cartera, riesgo y generación de estrategias.",
     "applied": "Marco general del diseño.", "applied_in": ["engine._run_cycle"]},
    # ── Integrados desde la librería quantfin (quant-finance-research, A. Ortega) ──
    {"id": "phillips2015", "title": "Testing for Multiple Bubbles: Historical Episodes of Exuberance and Collapse in "
     "the S&P 500", "authors": "Phillips, Shi, Yu", "year": 2015, "venue": "International Economic Review",
     "doi": "10.1111/iere.12132", "cited_by": 1182, "agent": "Analistas / gestor de riesgos", "source": QF,
     "finding": "La prueba recursiva SADF detecta un régimen explosivo mientras ocurre (no predice cuándo revienta).",
     "applied": "quantfin.sadf sobre el último año de log-precios; si supera 1,5 el peso máximo del activo se reduce "
                "a la mitad y entra como argumento bajista.",
     "applied_in": ["agents.asset_signals", "agents.apply_risk", "tools._qf_bubble"]},
    {"id": "kritzman2011", "title": "Principal Components as a Measure of Systemic Risk",
     "authors": "Kritzman, Li, Page, Rigobon", "year": 2011, "venue": "Journal of Portfolio Management",
     "doi": "10.3905/jpm.2011.37.4.112", "cited_by": 359, "agent": "Estratega macro", "source": QF,
     "finding": "El 'absorption ratio' (varianza que absorben los primeros componentes principales) sube antes de "
                "las crisis.",
     "applied": "quantfin.absorption_ratio en ventanas de 63 sesiones sobre el universo; z ≥ 1 resta puntos al "
                "régimen (mercado frágil).",
     "applied_in": ["agents.systemic_fragility", "agents.macro_regime", "tools._qf_fragility"]},
    {"id": "pafka2003", "title": "Noisy covariance matrices and portfolio optimization II", "authors": "Pafka, Kondor",
     "year": 2003, "venue": "Physica A", "doi": "10.1016/s0378-4371(02)01499-1", "cited_by": 121, "agent": "Gestor de riesgos", "source": QF,
     "finding": "El riesgo estimado con una covarianza de muestra es (1 − n/T) del real (en desviación típica).",
     "applied": "La volatilidad de la cartera se calcula con covarianza real y se corrige con "
                "quantfin.sesgo_optimizador antes de compararla con el objetivo del 10 %.",
     "applied_in": ["agents.portfolio_vol"]},
    {"id": "higham2002", "title": "Computing the nearest correlation matrix — a problem from finance",
     "authors": "Higham", "year": 2002, "venue": "IMA Journal of Numerical Analysis", "doi": "10.1093/imanum/22.3.329",
     "cited_by": 919, "agent": "Gestor de riesgos", "source": QF,
     "finding": "La correlación válida más cercana se obtiene con proyecciones alternadas y corrección de Dykstra.",
     "applied": "Si la matriz de correlación no es semidefinida positiva se repara con quantfin.nearest_correlation.",
     "applied_in": ["agents.covariance"]},
    {"id": "brock1992", "title": "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns",
     "authors": "Brock, Lakonishok, LeBaron", "year": 1992, "venue": "Journal of Finance",
     "doi": "10.1111/j.1540-6261.1992.tb04681.x", "cited_by": 2321, "agent": "Investigador cuant", "source": QF,
     "finding": "Medias móviles y rupturas de rango tuvieron poder predictivo en el Dow Jones (1897-1986); la ventaja "
                "en un solo activo se ha erosionado con el tiempo.",
     "applied": "Estrategias ema_20_100 (quantfin.senal_ema) y donchian_20 (quantfin.senal_donchian); el Deflated "
                "Sharpe penaliza haber añadido más pruebas.",
     "applied_in": ["agents._strat_ema", "agents._strat_donchian"]},
    {"id": "levine2016", "title": "Which Trend Is Your Friend?", "authors": "Levine, Pedersen", "year": 2016,
     "venue": "Financial Analysts Journal", "doi": "10.2469/faj.v72.n3.3", "cited_by": 60,
     "agent": "Investigador cuant", "source": QF,
     "finding": "Cruces de medias móviles y time-series momentum son casi la misma señal con distintos filtros.",
     "applied": "Por eso las variantes de tendencia compiten entre sí y solo se elige una por activo.",
     "applied_in": ["agents._strat_ema", "agents.select_strategy"]},
    {"id": "harvey2018", "title": "The Impact of Volatility Targeting", "authors": "Harvey, Hoyle, Korgaonkar, "
     "Rattray, Sargaison, Van Hemert", "year": 2018, "venue": "Journal of Portfolio Management",
     "doi": "10.3905/jpm.2018.45.1.014", "cited_by": 94, "agent": "Gestor de riesgos", "source": QF,
     "finding": "El objetivo de volatilidad mejora el Sharpe en activos de riesgo y siempre reduce la volatilidad de "
                "la volatilidad.",
     "applied": "Complementa a DeMiguel et al. (2024): se usa como techo de riesgo de la cartera.",
     "applied_in": ["agents.apply_risk"]},
    {"id": "bonart2026", "title": "Ley de la raíz cuadrada del impacto de mercado (arXiv 2606.07059)",
     "authors": "Bonart", "year": 2026, "venue": "arXiv (preprint, sin revisión por pares)", "doi": None,
     "cited_by": None, "agent": "Trader", "source": QF,
     "finding": "El impacto de una orden es ∝ σ·√(Q/V) (volatilidad diaria, tamaño, volumen diario).",
     "applied": "quantfin.impacto_raiz estima el coste de cada orden; se recorta si supera 50 pb.",
     "applied_in": ["agents.plan_orders", "tools._qf_impact"]},
    {"id": "almgren2001", "title": "Optimal execution of portfolio transactions", "authors": "Almgren, Chriss",
     "year": 2001, "venue": "Journal of Risk", "doi": "10.21314/jor.2001.041", "cited_by": 1573, "agent": "Trader", "source": QF,
     "finding": "Calendario óptimo de liquidación: equilibra impacto y riesgo de precio (TWAP si no hay aversión).",
     "applied": "Tool qf_execution_plan (quantfin.almgren_chriss) para planificar órdenes grandes.",
     "applied_in": ["tools._qf_impact"]},
    {"id": "avellaneda2008", "title": "High-frequency trading in a limit order book", "authors": "Avellaneda, Stoikov",
     "year": 2008, "venue": "Quantitative Finance", "doi": "10.1080/14697680701381228", "cited_by": 504, "agent": "Laboratorio quant", "source": QF,
     "finding": "Un creador de mercado ajusta su precio de reserva según su inventario y la volatilidad.",
     "applied": "Tool qf_market_making (quantfin.avellaneda_stoikov).", "applied_in": ["tools._qf_mm"]},
    {"id": "nelson1987", "title": "Parsimonious Modeling of Yield Curves", "authors": "Nelson, Siegel", "year": 1987,
     "venue": "Journal of Business", "doi": "10.1086/296409", "cited_by": 2855,
     "agent": "Laboratorio quant", "source": QF,
     "finding": "Tres factores (nivel, pendiente, curvatura) describen la curva de tipos.",
     "applied": "Tool qf_yield_curve (quantfin.ajustar_ns) y qf_bond (duración y convexidad).",
     "applied_in": ["tools._qf_curve", "tools._qf_bond"]},
    {"id": "uhlenbeck1930", "title": "On the Theory of the Brownian Motion", "authors": "Uhlenbeck, Ornstein",
     "year": 1930, "venue": "Physical Review", "doi": "10.1103/physrev.36.823", "cited_by": 4713, "agent": "Laboratorio quant", "source": QF,
     "finding": "Proceso de reversión a la media dX = θ(μ − X)dt + σdW, base del pairs trading.",
     "applied": "Tool qf_pairs_ou (quantfin.ajustar_ou + zscore_pairs) sobre el spread logarítmico de dos activos.",
     "applied_in": ["tools._qf_pairs"]},
    {"id": "kelly1956", "title": "A New Interpretation of Information Rate", "authors": "Kelly", "year": 1956,
     "venue": "Bell System Technical Journal", "doi": "10.1002/j.1538-7305.1956.tb03809.x", "cited_by": 1634, "agent": "Laboratorio quant", "source": QF,
     "finding": "La fracción óptima a apostar maximiza el crecimiento logarítmico del capital.",
     "applied": "Tool qf_kelly_binary (quantfin.kelly_binario) para mercados de predicción.",
     "applied_in": ["tools._qf_kelly"]},
    # ── Seguridad ──────────────────────────────────────────────────────────
    {"id": "greshake2023", "title": "Not What You've Signed Up For: Compromising Real-World LLM-Integrated "
     "Applications with Indirect Prompt Injection", "authors": "Greshake et al.", "year": 2023,
     "venue": "ACM AISec 2023", "doi": "10.1145/3605764.3623985", "cited_by": 1853,
     "agent": "Seguridad",
     "finding": "El contenido externo que lee un LLM (webs, noticias) puede contener instrucciones que lo secuestren.",
     "applied": "Titulares saneados y descartados si parecen órdenes; el LLM no tiene herramientas ni recibe titulares.",
     "applied_in": ["agents.sanitize_headline", "engine._llm_memo"]},
]

BY_ID = {r["id"]: r for r in REFERENCES}


def cite(*ids: str) -> list[dict]:
    """Referencias compactas para adjuntar a una decisión del informe."""
    return [{"id": i, "short": f"{BY_ID[i]['authors'].split(',')[0].split(' et')[0]} ({BY_ID[i]['year']})",
             "doi": BY_ID[i]["doi"]} for i in ids if i in BY_ID]


# ── Base de conocimiento unificada ──────────────────────────────────────────
import csv  # noqa: E402
import re  # noqa: E402
from functools import lru_cache  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LIBRARY_CSV = ROOT / "docs" / "quantfin" / "vince_quant_videos.csv"
RESEARCH_DOC = "docs/quantfin/investigacion.md"
KB_DOC = ROOT / "docs" / "BASE_DE_CONOCIMIENTO.md"


def _first_year(text: str) -> int | None:
    m = re.search(r"(1[89]\d\d|20\d\d)", text or "")
    return int(m.group(1)) if m else None


def _surname(authors: str) -> str:
    return re.split(r"[ ,;(]", (authors or "").strip(), maxsplit=1)[0].lower()


def _funcs(text: str) -> list[str]:
    from server.quantfin_catalog import FUNCS
    return [f for f in re.findall(r"([a-z_0-9]+)\(\)", text or "") if f in FUNCS]


def _library_rows() -> list[dict]:
    with LIBRARY_CSV.open(encoding="utf-8") as fh:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(fh)]


@lru_cache(maxsize=1)
def knowledge_base() -> list[dict]:
    """Todos los papers (fondo + quant-finance-research + catálogo quantfin), sin duplicados."""
    from server.quantfin_catalog import FUNCS
    kb: list[dict] = []
    for r in REFERENCES:
        sur = r["authors"].split(",")[0].split(" ")[0]
        fns = sorted({n for n in re.findall(r"quantfin\.([a-z_0-9]+)", r["applied"]) if n in FUNCS}
                     | {n for n, f in FUNCS.items()
                        if any(sur in seg and str(r["year"]) in seg for seg in f.papers.split(";"))})
        kb.append({"id": r["id"], "year": r["year"], "authors": r["authors"], "title": r["title"],
                   "venue": r["venue"], "doi": r["doi"], "url": f"https://doi.org/{r['doi']}" if r["doi"] else None,
                   "topic": f"Fondo · {r['agent']}", "agent": r["agent"], "finding": r["finding"], "applied": r["applied"],
                   "applied_in": list(r["applied_in"]), "functions": fns, "videos": [],
                   "sources": ["fondo"]})

    def match(surname: str, year: int | None) -> dict | None:
        for e in kb:
            if surname and _surname(e["authors"]) == surname and year and e["year"] and abs(e["year"] - year) <= 1:
                return e
        return None

    for i, row in enumerate(_library_rows(), 1):
        paper = row["paper"].replace("*", "")
        year, fns = _first_year(paper), _funcs(row["funcion"])
        e = match(_surname(paper), year)
        if e is None:
            authors = paper.split(" (")[0]
            venue = re.search(r"\*([^*]+)\*", row["paper"])
            e = {"id": f"qfr{i:02d}", "year": year, "authors": authors, "title": paper,
                 "venue": venue.group(1) if venue else "", "doi": None, "url": None, "topic": row["tema"],
                 "agent": None, "finding": row["idea_clave"], "applied": "", "applied_in": [], "functions": [],
                 "videos": [], "sources": []}
            kb.append(e)
        e["topic"] = row["tema"]
        e["videos"].append({"title": row["video"], "url": row["url"] or None, "idea": row["idea_clave"]})
        e["functions"] = sorted(set(e["functions"]) | set(fns))
        if "quant-finance-research" not in e["sources"]:
            e["sources"].append("quant-finance-research")

    covered = {f for e in kb for f in e["functions"]}
    for name, f in FUNCS.items():  # funciones de quantfin cuyo paper aún no estaba en la base
        if name in covered:
            continue
        kb.append({"id": f"qf_{name}", "year": _first_year(f.papers), "authors": f.papers.split(" (")[0],
                   "title": f.papers, "venue": f"quantfin.{f.module} · {f.market}", "doi": None, "url": None,
                   "topic": f.market, "agent": None, "finding": f.summary, "applied": "", "applied_in": [],
                   "functions": [name], "videos": [], "sources": ["quantfin"]})

    for e in kb:  # dónde vive cada función en la terminal
        paths = list(e["applied_in"])
        for fn in e["functions"]:
            paths += [u.split(" ")[0] for u in FUNCS[fn].used_in if not u.startswith("quantfin.")]
        e["applied_in"] = list(dict.fromkeys(paths + ["tools.qf_function"] * bool(e["functions"])))
        if not e["applied"]:
            e["applied"] = ("Código: " + ", ".join(f"quantfin.{FUNCS[f].module}.{f}()" for f in e["functions"])
                            if e["functions"] else "Referencia de la investigación (sin función propia en quantfin).")
    kb.sort(key=lambda e: (-(e["year"] or 0), e["authors"]))
    return kb


def knowledge_markdown() -> str:
    """Documento único: papers + funciones + dónde se usa cada cosa en la terminal."""
    from server.quantfin_catalog import catalog
    kb = knowledge_base()
    esc = lambda t: str(t or "").replace("|", "\\|").replace("\n", " ")  # noqa: E731
    out = ["# Base de conocimiento de Fincept Lite", "",
           "Generado con `python -m server.fund.research`. Junta en un solo documento:", "",
           f"- **{len(REFERENCES)} papers del fondo multi-agente** (`server/fund/research.py`).",
           f"- **{len(_library_rows())} papers de quant-finance-research** (`docs/quantfin/vince_quant_videos.csv`; "
           f"el texto completo está en `{RESEARCH_DOC}`).",
           f"- **{len(catalog())} funciones de la librería `quantfin`** (`quantfin/`, catálogo en "
           "`server/quantfin_catalog.py`).", "",
           f"En total, **{len(kb)} entradas** sin duplicados. En la terminal: pantalla FUND (panel *Base de "
           "conocimiento*), `GET /fund/research`, y las tools `qf_catalog` y `qf_function` (MCP, chat y "
           "Laboratorio quantfin en QUANTLIB).", "", "## 1. Papers por tema", ""]
    topics: dict[str, list[dict]] = {}
    for e in kb:
        topics.setdefault(e["topic"] or "Otros", []).append(e)
    for topic in sorted(topics):
        out += [f"### {topic}", "", "| Año | Paper | Idea clave | Código | Fuente |", "|---|---|---|---|---|"]
        for e in topics[topic]:
            link = f"[{esc(e['title'])}]({e['url']})" if e["url"] else esc(e["title"])
            if e["authors"] and e["authors"] not in e["title"]:
                link = f"{esc(e['authors'])}: {link}"
            code = ", ".join(f"`{p}`" for p in e["applied_in"]) or "—"
            src = ", ".join(e["sources"]) + "".join(f" · [video]({v['url']})" for v in e["videos"] if v["url"])
            ideas = [e["finding"]] + [v["idea"] for v in e["videos"] if v["idea"] != e["finding"]]
            out.append(f"| {e['year'] or ''} | {link} | {esc(' / '.join(ideas))} | {code} | {src} |")
        out.append("")
    out += ["## 2. Funciones de quantfin", "",
            "Todas se pueden ejecutar con `qf_function(function=..., args={...})`; sin `args` corre el ejemplo.", ""]
    market = None
    for d in sorted(catalog(), key=lambda d: (d["market"], d["name"])):
        if d["market"] != market:
            market = d["market"]
            out += [f"### {market}", "", "| Función | Qué hace | Parámetros | Salidas | Papers | Dónde se usa |",
                    "|---|---|---|---|---|---|"]
        params = ", ".join(p["name"] for p in d["params"])
        out.append(f"| `{d['module']}.{d['name']}` | {esc(d['summary'])} | {params} | {', '.join(d['outputs'])} | "
                   f"{esc(d['papers'])} | {', '.join(f'`{u}`' for u in d['used_in'])} |")
    out += ["", "## 3. Cómo encaja todo", "",
            "- **Fondo (pantalla FUND):** SADF limita activos en burbuja, el absorption ratio vuelve el régimen "
            "defensivo, la paridad de riesgo usa la covarianza (reparada con Higham), la volatilidad se corrige con "
            "Pafka-Kondor, las estrategias EMA y Donchian compiten en el playbook y cada orden lleva su impacto "
            "estimado con la ley de la raíz cuadrada.",
            "- **Tools:** `qf_bubble_test`, `qf_systemic_fragility`, `qf_pairs_ou`, `qf_risk_parity`, "
            "`qf_execution_plan`, `qf_yield_curve`, `qf_bond`, `qf_kelly_binary`, `qf_market_making`, más "
            "`qf_catalog` y `qf_function` para las 39 funciones.",
            f"- **Investigación completa:** `{RESEARCH_DOC}` (mercado por mercado, cursos, librerías y código).", ""]
    return "\n".join(out)


if __name__ == "__main__":
    KB_DOC.write_text(knowledge_markdown(), encoding="utf-8")
    print(f"{KB_DOC.relative_to(ROOT)}: {len(knowledge_base())} entradas")
