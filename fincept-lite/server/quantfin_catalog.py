"""Catálogo de la librería quantfin: las 39 funciones, sus parámetros, papers y dónde se usan.

Une el código (`quantfin/mercados.py`, `quantfin/avanzados.py`), la investigación
(`docs/quantfin/investigacion.md`) y el resto de la terminal. Lo usan la tool
`qf_function` (llamar a cualquier función), `qf_catalog` y la base de conocimiento.

Cada parámetro declara tipo y límites: los vectores y matrices tienen tamaño máximo
y los bucles (Monte Carlo, SADF, Higham, cobertura) un tope de iteraciones, para que
una llamada no pueda bloquear el servidor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

MAX_VEC = 5000
MAX_MAT = 50_000


@dataclass(frozen=True)
class P:
    name: str
    kind: str  # num | int | vec | mat | choice
    desc: str
    default: object = None
    lo: float | None = None
    hi: float | None = None
    choices: tuple = ()
    max_len: int = MAX_VEC


@dataclass(frozen=True)
class F:
    module: str  # mercados | avanzados
    market: str
    summary: str
    params: tuple
    outputs: tuple
    papers: str
    used_in: tuple = field(default_factory=tuple)
    example: dict = field(default_factory=dict)


_S = (P("S", "num", "Precio del subyacente.", lo=1e-9), P("K", "num", "Strike.", lo=1e-9),
      P("T", "num", "Años al vencimiento.", lo=1e-6, hi=50), P("r", "num", "Tipo libre de riesgo (0.05 = 5 %).", lo=-1, hi=1),
      P("sigma", "num", "Volatilidad anual (0.2 = 20 %).", lo=1e-6, hi=5))

FUNCS: dict[str, F] = {
    # ── mercados.py ───────────────────────────────────────────────────────────
    "black_scholes": F("mercados", "Volatilidad, derivados y crédito", "Precio y griegas de una opción europea.",
                       _S + (P("tipo", "choice", "call o put.", "call", choices=("call", "put")),),
                       ("precio", "delta", "gamma", "vega"), "Black y Scholes (1973); Merton (1973)",
                       ("analytics.bs_price (misma fórmula)",), {"S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": 0.2}),
    "monte_carlo_call": F("mercados", "Volatilidad, derivados y crédito", "Call europea por Monte Carlo (semilla fija).",
                          _S + (P("n", "int", "Simulaciones.", 200_000, 1000, 1_000_000),), ("precio",),
                          "Boyle (1977)", (), {"S": 100, "K": 100, "T": 1, "r": 0.05, "sigma": 0.2, "n": 100000}),
    "garch11": F("mercados", "Volatilidad, derivados y crédito", "Volatilidad condicional GARCH(1,1) de una serie de rendimientos.",
                 (P("r", "vec", "Rendimientos."), P("omega", "num", "ω.", lo=0), P("alpha", "num", "α.", lo=0, hi=1),
                  P("beta", "num", "β.", lo=0, hi=1)), ("volatilidad",), "Bollerslev (1986)", (),
                 {"r": [0.01, -0.02, 0.015, -0.005, 0.03, -0.01], "omega": 0.000002, "alpha": 0.08, "beta": 0.9}),
    "regresion_factores": F("mercados", "Acciones", "Alfa y betas de un activo contra factores (tipo Fama-French).",
                            (P("r_activo", "vec", "Rendimientos del activo."),
                             P("factores", "mat", "Matriz T×k de rendimientos de los factores.")),
                            ("alfa_y_betas",), "Fama y French (1993); Jensen, Kelly y Pedersen (2023)", (),
                            {"r_activo": [0.01, 0.02, -0.01, 0.005], "factores": [[0.01], [0.015], [-0.012], [0.004]]}),
    "momentum_seccion_cruzada": F("mercados", "Acciones", "Pesos long/short por momentum 12-1 (quintiles).",
                                  (P("precios", "mat", "Matriz T×n de precios (T > lookback)."),
                                   P("lookback", "int", "Ventana.", 252, 2, 2520), P("skip", "int", "Mes saltado.", 21, 0, 252)),
                                  ("pesos",), "Jegadeesh y Titman (1993)", ("agents._strat_momentum (misma idea, serie temporal)",), {}),
    "nelson_siegel": F("mercados", "Renta fija", "Curva Nelson-Siegel para unos plazos dados.",
                       (P("tau", "vec", "Plazos en años.", lo=1e-6), P("b0", "num", "Nivel."), P("b1", "num", "Pendiente."),
                        P("b2", "num", "Curvatura."), P("lam", "num", "λ.", lo=1e-3, hi=100)), ("tasas",),
                       "Nelson y Siegel (1987); Diebold y Li (2006)", ("tools.qf_yield_curve",),
                       {"tau": [1, 2, 5, 10], "b0": 0.045, "b1": -0.01, "b2": 0.005, "lam": 2}),
    "ajustar_ns": F("mercados", "Renta fija", "Ajusta Nelson-Siegel a una curva observada.",
                    (P("plazos", "vec", "Plazos en años.", lo=1e-6), P("tasas", "vec", "Rendimientos (0.04 = 4 %).")),
                    ("nivel", "pendiente", "curvatura", "lambda"), "Nelson y Siegel (1987)", ("tools.qf_yield_curve",),
                    {"plazos": [0.25, 1, 2, 5, 10, 30], "tasas": [0.045, 0.043, 0.041, 0.04, 0.042, 0.046]}),
    "duracion_convexidad": F("mercados", "Renta fija", "Precio, duración modificada y convexidad de un bono.",
                             (P("cupon", "num", "Cupón anual (0.05).", lo=0, hi=1), P("ytm", "num", "TIR.", lo=-0.5, hi=1),
                              P("n_anios", "int", "Años.", lo=1, hi=100), P("freq", "int", "Pagos al año.", 2, 1, 12)),
                             ("precio", "duracion_modificada", "convexidad"), "Macaulay (1938); Fabozzi", ("tools.qf_bond",),
                             {"cupon": 0.05, "ytm": 0.04, "n_anios": 10}),
    "carry_trade": F("mercados", "Divisas", "Cartera carry: compra las monedas de tipo alto y vende las de tipo bajo.",
                     (P("tasas_extranjeras", "vec", "Tipos de interés de cada moneda."), P("tasa_local", "num", "Tipo local."),
                      P("n_long", "int", "Monedas compradas.", 3, 1, 50), P("n_short", "int", "Monedas vendidas.", 3, 1, 50)),
                     ("pesos", "carry_esperado"), "Lustig, Roussanov y Verdelhan (2011); Menkhoff et al. (2012)", (),
                     {"tasas_extranjeras": [0.11, 0.105, 0.08, 0.04, 0.005, 0.01, 0.03], "tasa_local": 0.045,
                      "n_long": 2, "n_short": 2}),
    "basis_momentum": F("mercados", "Materias primas", "Momentum del 1.er vencimiento menos el del 2.º.",
                        (P("f1", "vec", "Precios del primer futuro."), P("f2", "vec", "Precios del segundo futuro."),
                         P("ventana", "int", "Ventana.", 252, 1, 2520)), ("basis_momentum",),
                        "Boons y Porras Prado (2019)", (), {}),
    "roll_yield": F("mercados", "Materias primas", "Roll yield anualizado (> 0 = backwardation).",
                    (P("f1", "num", "Precio del primer futuro.", lo=1e-9), P("f2", "num", "Precio del segundo.", lo=1e-9),
                     P("dias_entre_vencimientos", "int", "Días entre vencimientos.", 30, 1, 3650)), ("roll_yield",),
                    "Erb y Harvey (2006); Koijen et al. (2018)", (), {"f1": 80, "f2": 78}),
    "tsmom": F("mercados", "Multi-activo", "Time-series momentum con objetivo de volatilidad.",
               (P("retornos", "mat", "Matriz T×n de rendimientos diarios (T ≥ lookback)."),
                P("vol_obj", "num", "Volatilidad objetivo.", 0.40, 0.01, 2), P("lookback", "int", "Ventana.", 252, 63, 2520)),
               ("pesos",), "Moskowitz, Ooi y Pedersen (2012)", ("agents._strat_tsmom12",), {}),
    "avellaneda_stoikov": F("mercados", "Ejecución y microestructura", "Bid y ask óptimos de un creador de mercado.",
                            (P("mid", "num", "Precio medio.", lo=1e-9), P("inventario", "num", "Inventario."),
                             P("gamma", "num", "Aversión al riesgo.", lo=1e-9), P("sigma", "num", "Volatilidad.", lo=0),
                             P("T_rest", "num", "Tiempo restante.", lo=0), P("k", "num", "Intensidad de órdenes.", lo=1e-9)),
                            ("bid", "ask"), "Avellaneda y Stoikov (2008)", ("tools.qf_market_making",),
                            {"mid": 100, "inventario": 5, "gamma": 0.1, "sigma": 2, "T_rest": 1, "k": 1.5}),
    "almgren_chriss": F("mercados", "Ejecución y microestructura", "Trayectoria óptima para liquidar X acciones en N pasos.",
                        (P("X", "num", "Acciones a liquidar."), P("T", "num", "Horizonte.", lo=1e-9),
                         P("N", "int", "Pasos.", lo=1, hi=1000), P("sigma", "num", "Volatilidad.", lo=0),
                         P("eta", "num", "Impacto temporal.", lo=1e-12), P("lam", "num", "Aversión al riesgo.", lo=1e-12)),
                        ("trayectoria",), "Almgren y Chriss (2001)", ("tools.qf_execution_plan",),
                        {"X": 100000, "T": 1, "N": 10, "sigma": 0.3, "eta": 0.01, "lam": 0.000001}),
    "lvr_producto_constante": F("mercados", "Cripto y DeFi", "Loss-versus-rebalancing anual de un pool x·y = k.",
                                (P("valor_pool", "num", "Valor del pool.", lo=0), P("sigma_anual", "num", "Volatilidad.", lo=0)),
                                ("lvr_anual",), "Milionis, Moallemi, Roughgarden y Zhang (2022)", (),
                                {"valor_pool": 1_000_000, "sigma_anual": 0.8}),
    "impermanent_loss": F("mercados", "Cripto y DeFi", "Pérdida impermanente para un cambio de precio ρ.",
                          (P("ratio_precio", "num", "Precio final / inicial.", lo=1e-9),), ("perdida",),
                          "Uniswap v2 (Adams et al. 2020)", (), {"ratio_precio": 2}),
    "kelly_binario": F("mercados", "Mercados de predicción", "Fracción de Kelly para un contrato binario.",
                       (P("p_propia", "num", "Tu probabilidad.", lo=0, hi=1), P("precio", "num", "Precio del SÍ.", lo=0, hi=0.9999)),
                       ("fraccion",), "Kelly (1956)", ("tools.qf_kelly_binary",), {"p_propia": 0.6, "precio": 0.5}),
    "lmsr_precio": F("mercados", "Mercados de predicción", "Precios del market maker LMSR de Hanson.",
                     (P("q", "vec", "Acciones emitidas de cada resultado."), P("b", "num", "Liquidez.", lo=1e-9)),
                     ("precios",), "Hanson (2003)", (), {"q": [100, 50, 0], "b": 100}),
    "brier": F("mercados", "Mercados de predicción", "Brier score de unas probabilidades frente al resultado.",
               (P("prob", "vec", "Probabilidades.", lo=0, hi=1), P("resultado", "vec", "Resultados 0/1.", lo=0, hi=1)),
               ("brier",), "Brier (1950)", (), {"prob": [0.7, 0.2, 0.9], "resultado": [1, 0, 1]}),
    "var_es": F("mercados", "Riesgo y portafolio", "VaR y Expected Shortfall históricos.",
                (P("retornos", "vec", "Rendimientos."), P("alfa", "num", "Confianza.", 0.99, 0.5, 0.9999)),
                ("var", "es"), "Artzner et al. (1999); Basilea FRTB", ("analytics.risk_metrics (equivalente)",),
                {"retornos": [-0.03, 0.01, 0.02, -0.01, 0.005, -0.02, 0.015, -0.04, 0.01, 0.0], "alfa": 0.9}),
    "min_varianza": F("mercados", "Riesgo y portafolio", "Cartera de mínima varianza (Markowitz).",
                      (P("cov", "mat", "Matriz de covarianza n×n."),), ("pesos",), "Markowitz (1952)", (),
                      {"cov": [[0.04, 0.006], [0.006, 0.01]]}),
    "risk_parity": F("mercados", "Riesgo y portafolio", "Pesos de paridad de riesgo (contribuciones iguales).",
                     (P("cov", "mat", "Matriz de covarianza n×n."), P("iters", "int", "Iteraciones.", 500, 1, 5000)),
                     ("pesos",), "Maillard, Roncalli y Teïletche (2010)",
                     ("agents.risk_budget", "tools.qf_risk_parity"), {"cov": [[0.04, 0.006], [0.006, 0.01]]}),
    "sharpe": F("mercados", "Riesgo y portafolio", "Sharpe anualizado.",
                (P("r", "vec", "Rendimientos."), P("freq", "int", "Periodos por año.", 252, 1, 100_000)), ("sharpe",),
                "Sharpe (1966)", ("backtest.perf_metrics (equivalente)",), {"r": [0.01, -0.005, 0.007, 0.002, -0.001]}),
    # ── avanzados.py ──────────────────────────────────────────────────────────
    "ajustar_ou": F("avanzados", "Tendencia y señales", "Ajuste Ornstein-Uhlenbeck (θ, μ, σ, vida media).",
                    (P("x", "vec", "Serie (p. ej. spread)."), P("dt", "num", "Paso.", 1 / 252, 1e-6, 1)),
                    ("theta", "mu", "sigma", "vida_media"), "Uhlenbeck y Ornstein (1930)", ("tools.qf_pairs_ou",), {}),
    "zscore_pairs": F("avanzados", "Tendencia y señales", "Z-score del spread y señal de pairs trading.",
                      (P("spread", "vec", "Spread."), P("mu", "num", "μ."), P("sigma", "num", "σ.", lo=1e-12),
                       P("theta", "num", "θ.", lo=1e-12), P("entrada", "num", "Umbral |z|.", 2.0, 0.1, 10)),
                      ("z", "senal"), "Uhlenbeck y Ornstein (1930); Gatev, Goetzmann y Rouwenhorst (2006)",
                      ("tools.qf_pairs_ou",), {"spread": [0.1, -0.2, 0.5, 0.05], "mu": 0, "sigma": 0.3, "theta": 5}),
    "adf_t": F("avanzados", "Burbujas, regímenes y riesgo sistémico", "Estadístico t de Dickey-Fuller aumentado.",
               (P("y", "vec", "Serie (log-precios)."),), ("t",), "Dickey y Fuller (1979)", ("quantfin.sadf",), {}),
    "sadf": F("avanzados", "Burbujas, regímenes y riesgo sistémico", "Sup-ADF: detecta un régimen explosivo.",
              (P("y", "vec", "Log-precios.", max_len=1500), P("r0", "num", "Ventana mínima.", 0.2, 0.05, 0.9)), ("sadf",),
              "Phillips, Shi y Yu (2015)", ("agents.asset_signals", "agents.apply_risk", "tools.qf_bubble_test"), {}),
    "absorption_ratio": F("avanzados", "Burbujas, regímenes y riesgo sistémico",
                          "Varianza absorbida por los primeros componentes principales.",
                          (P("retornos", "mat", "Matriz T×n de rendimientos."), P("frac", "num", "Fracción de CP.", 0.2, 0.01, 1)),
                          ("absorption_ratio",), "Kritzman, Li, Page y Rigobon (2011)",
                          ("agents.systemic_fragility", "agents.macro_regime", "tools.qf_systemic_fragility"), {}),
    "deflated_sharpe": F("avanzados", "Validación de backtests y machine learning",
                         "Probabilidad de que un Sharpe sea real tras probar n estrategias.",
                         (P("r", "vec", "Rendimientos de la estrategia elegida."),
                          P("n_pruebas", "int", "Estrategias probadas.", lo=2, hi=1_000_000),
                          P("var_sharpes", "num", "Varianza de los Sharpe probados.", lo=0)), ("probabilidad",),
                         "Bailey y López de Prado (2014)", ("agents.deflated_sharpe", "agents.select_strategy"), {}),
    "nearest_correlation": F("avanzados", "Portafolios y limpieza de covarianza",
                             "Matriz de correlación válida más cercana (Higham).",
                             (P("A", "mat", "Matriz simétrica n×n.", max_len=40_000),
                              P("iters", "int", "Iteraciones.", 200, 1, 1000)), ("matriz",), "Higham (2002)",
                             ("agents.covariance",), {"A": [[1, 0.9, 0.7], [0.9, 1, -0.9], [0.7, -0.9, 1]]}),
    "sesgo_optimizador": F("avanzados", "Portafolios y limpieza de covarianza",
                           "Factor (1 − n/T): riesgo predicho frente al real.",
                           (P("n", "int", "Activos.", lo=1, hi=100_000), P("T", "int", "Observaciones.", lo=1, hi=10_000_000)),
                           ("factor",), "Pafka y Kondor (2003)", ("agents.portfolio_vol",), {"n": 50, "T": 750}),
    "diversity_weighted": F("avanzados", "Portafolios y limpieza de covarianza", "Cartera ponderada por diversidad.",
                            (P("pesos_mercado", "vec", "Pesos de mercado.", lo=0), P("p", "num", "Exponente.", 0.5, 0, 1)),
                            ("pesos",), "Fernholz, Karatzas y Kardaras (2005)", (),
                            {"pesos_mercado": [0.5, 0.3, 0.15, 0.05]}),
    "ema": F("avanzados", "Tendencia y señales", "Media móvil exponencial.",
             (P("x", "vec", "Serie."), P("span", "int", "Span.", lo=1, hi=5000)), ("ema",), "Brock et al. (1992)",
             ("quantfin.senal_ema",), {"x": [1, 2, 3, 4, 5], "span": 3}),
    "senal_ema": F("avanzados", "Tendencia y señales", "Señal de cruce de EMAs (+1/−1).",
                   (P("precios", "vec", "Precios."), P("rapida", "int", "EMA rápida.", 20, 1, 1000),
                    P("lenta", "int", "EMA lenta.", 100, 2, 2000)), ("senal",),
                   "Brock, Lakonishok y LeBaron (1992); Levine y Pedersen (2016)", ("agents._strat_ema",), {}),
    "senal_donchian": F("avanzados", "Tendencia y señales", "Señal de ruptura del canal de Donchian.",
                        (P("precios", "vec", "Precios."), P("n", "int", "Ventana.", 20, 2, 1000)), ("senal",),
                        "Brock et al. (1992); historia de Dennis y Eckhardt", ("agents._strat_donchian",), {}),
    "vol_target": F("avanzados", "Tendencia y señales", "Apalancamiento diario para una volatilidad objetivo.",
                    (P("retornos", "vec", "Rendimientos (≥ 20)."), P("vol_obj", "num", "Objetivo.", 0.10, 0.001, 2),
                     P("halflife", "int", "Vida media EWMA.", 20, 1, 1000)), ("apalancamiento",),
                    "Harvey et al. (2018)", ("agents.apply_risk (techo de volatilidad)",), {}),
    "impacto_raiz": F("avanzados", "Ejecución y microestructura", "Impacto de mercado ∝ σ·√(Q/V).",
                      (P("sigma_diaria", "num", "Volatilidad diaria.", lo=0), P("Q", "num", "Tamaño.", lo=0),
                       P("V", "num", "Volumen diario.", lo=1e-9), P("Y", "num", "Constante.", 0.7, 0, 10)), ("impacto",),
                      "Bonart (2026); ley de la raíz cuadrada (Tóth et al. 2011)",
                      ("agents.plan_orders", "tools.qf_execution_plan"),
                      {"sigma_diaria": 0.02, "Q": 10000, "V": 1000000}),
    "mejora_sharpe": F("avanzados", "Portafolios y limpieza de covarianza",
                       "¿Una estrategia nueva sube el Sharpe de la tuya? (S_nueva > ρ·S_tuya).",
                       (P("sharpe_nueva", "num", "Sharpe nueva."), P("sharpe_tuya", "num", "Sharpe actual."),
                        P("rho", "num", "Correlación.", lo=-1, hi=1)), ("mejora",), "Markowitz (1952)", (),
                       {"sharpe_nueva": 0.5, "sharpe_tuya": 1.0, "rho": 0.3}),
    "pnl_cobertura": F("avanzados", "Volatilidad, derivados y crédito",
                       "P&L de cubrir una call con una volatilidad equivocada.",
                       (P("S0", "num", "Precio inicial.", 100, 1e-6), P("K", "num", "Strike.", 100, 1e-6),
                        P("T", "num", "Años.", 0.25, 1e-3, 5), P("sig_cob", "num", "Vol de cobertura.", 0.25, 1e-3, 5),
                        P("sig_real", "num", "Vol real.", 0.20, 1e-3, 5), P("n", "int", "Pasos.", 252, 2, 504),
                        P("sims", "int", "Simulaciones.", 4000, 10, 5000)), ("pnl_medio", "prob_perdida"),
                       "El Karoui, Jeanblanc-Picqué y Shreve (1998)", (), {"sims": 1000}),
}


class QfArgError(ValueError):
    pass


def _num(p: P, v, integer=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not math.isfinite(v)):
        raise QfArgError(f"'{p.name}' must be a finite number.")
    if integer:
        if float(v) != int(v):
            raise QfArgError(f"'{p.name}' must be an integer.")
        v = int(v)
    if p.lo is not None and v < p.lo:
        raise QfArgError(f"'{p.name}' must be ≥ {p.lo}.")
    if p.hi is not None and v > p.hi:
        raise QfArgError(f"'{p.name}' must be ≤ {p.hi}.")
    return v


def _coerce(p: P, v):
    import numpy as np
    if p.kind == "num":
        return float(_num(p, v))
    if p.kind == "int":
        return _num(p, v, integer=True)
    if p.kind == "choice":
        if v not in p.choices:
            raise QfArgError(f"'{p.name}' must be one of {list(p.choices)}.")
        return v
    if not isinstance(v, list) or not v:
        raise QfArgError(f"'{p.name}' must be a non-empty array.")
    if p.kind == "vec":
        if len(v) > p.max_len:
            raise QfArgError(f"'{p.name}' has {len(v)} values; max {p.max_len}.")
        return np.array([_num(p, x) for x in v], dtype=float)
    rows = v
    if not all(isinstance(r, list) and r for r in rows) or len({len(r) for r in rows}) != 1:
        raise QfArgError(f"'{p.name}' must be a rectangular matrix (list of equal-length rows).")
    cap = MAX_MAT if p.max_len == MAX_VEC else p.max_len
    if len(rows) * len(rows[0]) > cap:
        raise QfArgError(f"'{p.name}' is too large (max {cap} cells).")
    return np.array([[_num(p, x) for x in r] for r in rows], dtype=float)


def _py(v):
    import numpy as np
    if isinstance(v, np.ndarray):
        return [_py(x) for x in v.tolist()] if v.ndim else _py(v.item())
    if isinstance(v, (list, tuple)):
        return [_py(x) for x in v]
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return f if math.isfinite(f) else None
    return v


def call(name: str, args: dict) -> dict:
    """Valida los argumentos y ejecuta la función de quantfin. Devuelve sus salidas con nombre."""
    if name not in FUNCS:
        raise QfArgError(f"Unknown function {name!r}. Call qf_catalog to list the {len(FUNCS)} functions.")
    spec = FUNCS[name]
    known = {p.name for p in spec.params}
    extra = set(args) - known
    if extra:
        raise QfArgError(f"Unknown argument(s) {sorted(extra)} for {name}; expected {sorted(known)}.")
    kwargs = {}
    for p in spec.params:
        if p.name in args:
            kwargs[p.name] = _coerce(p, args[p.name])
        elif p.default is None:
            raise QfArgError(f"Missing argument '{p.name}' for {name}: {p.desc}")
    import importlib

    import numpy as np
    fn = getattr(importlib.import_module(f"quantfin.{spec.module}"), name)
    with np.errstate(all="ignore"):
        try:
            out = fn(**kwargs)
        except (ValueError, IndexError, ZeroDivisionError, np.linalg.LinAlgError, OverflowError) as e:
            raise QfArgError(f"{name} could not compute with these inputs ({type(e).__name__}: {e}). "
                             "Check array sizes against the parameter descriptions.") from e
    if isinstance(out, tuple):
        values = list(out)
    elif len(spec.outputs) > 1:  # p. ej. ajustar_ns devuelve un único array [nivel, pendiente, curvatura, λ]
        values = list(np.asarray(out))
    else:
        values = [out]
    return {"function": name, "module": f"quantfin.{spec.module}", "papers": spec.papers,
            "result": dict(zip(spec.outputs, (_py(v) for v in values)))}


def _synthetic(name: str) -> dict:
    """Ejemplo reproducible con series sintéticas para las funciones que piden datos."""
    import numpy as np
    g = np.random.default_rng(11)
    rets = g.normal(0.0004, 0.01, (300, 6))
    prices = 100 * np.cumprod(1 + rets, axis=0)
    walk, r1 = prices[:, 0], rets[:, 0]
    ou = np.zeros(300)
    for t in range(1, 300):
        ou[t] = ou[t - 1] * 0.95 + g.normal(0, 0.02)
    bubble = np.log(np.concatenate([walk[:200], walk[199] * 1.02 ** np.arange(1, 51)]))
    rnd = lambda a: np.round(a, 6).tolist()  # noqa: E731
    return {
        "momentum_seccion_cruzada": {"precios": rnd(prices), "lookback": 252, "skip": 21},
        "basis_momentum": {"f1": rnd(walk), "f2": rnd(prices[:, 1]), "ventana": 252},
        "tsmom": {"retornos": rnd(rets[:, :4]), "vol_obj": 0.4, "lookback": 252},
        "ajustar_ou": {"x": rnd(ou)},
        "adf_t": {"y": rnd(np.log(walk[:200]))},
        "sadf": {"y": rnd(bubble)},
        "absorption_ratio": {"retornos": rnd(rets)},
        "deflated_sharpe": {"r": rnd(r1 + 0.001), "n_pruebas": 10, "var_sharpes": 0.001},
        "senal_ema": {"precios": rnd(walk)},
        "senal_donchian": {"precios": rnd(walk)},
        "vol_target": {"retornos": rnd(r1)},
    }.get(name, {})


def describe(name: str) -> dict:
    s = FUNCS[name]
    return {"name": name, "module": f"quantfin.{s.module}", "market": s.market, "summary": s.summary,
            "params": [{"name": p.name, "type": p.kind, "description": p.desc,
                        **({"default": p.default} if p.default is not None else {}),
                        **({"min": p.lo} if p.lo is not None else {}), **({"max": p.hi} if p.hi is not None else {}),
                        **({"choices": list(p.choices)} if p.choices else {})} for p in s.params],
            "outputs": list(s.outputs), "papers": s.papers,
            "used_in": list(s.used_in) + ["tools.qf_function"], "example": s.example or _synthetic(name)}


def catalog() -> list[dict]:
    return [describe(n) for n in FUNCS]
