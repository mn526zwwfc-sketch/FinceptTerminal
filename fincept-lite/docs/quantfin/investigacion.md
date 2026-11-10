# Finanzas cuantitativas por mercado: papers, cursos, modelos y código

Nov 10, 2026 · @Agustin

## 1. Resumen

Este documento junta lo más actual (2025-2026) de la investigación en finanzas cuantitativas, organizado por mercado: acciones, renta fija, divisas, materias primas, derivados, microestructura, cripto/DeFi y mercados de predicción, más riesgo y portafolio. Para cada mercado hay papers clave, la estrategia que proponen, la fórmula central y la función de Python que la implementa (sección 6, código probado).

**Las 5 ideas que más se repiten en la investigación reciente:**

1. **El machine learning gana a los modelos simples** para predecir rendimientos, siempre que se use con regularización (Kelly, Malamud y Zhou, 2024).
2. **Los agentes con LLM son el tema de moda**, pero casi ninguno le gana a estrategias sencillas fuera de la muestra (StockBench, 2026).
3. **Los factores clásicos sí se replican:** valor, momentum, calidad y baja volatilidad siguen siendo la base (Jensen, Kelly y Pedersen, 2023).
4. **El "carry" funciona en todos los mercados:** divisas, bonos y materias primas, con riesgo de caídas bruscas.
5. **Los mercados nuevos (DeFi y predicción) ya tienen su propia teoría matemática:** LVR para AMMs y calibración para Kalshi y Polymarket.

**Cómo usarlo:** lee la sección 3 del mercado que te interese, abre el paper principal y corre la función correspondiente del código. Para aprender la base matemática, empieza por los cursos gratis de la sección 4.

## 2. Tendencias de investigación 2025-2026

### 2.1 IA y "virtud de la complejidad"

- **The Virtue of Complexity in Return Prediction** — Kelly, Malamud y Zhou, *Journal of Finance* 79(1), 2024. Demuestran en teoría y con datos de EE. UU. que los modelos con más parámetros que observaciones predicen mejor el rendimiento del mercado que los modelos de pocas variables. Clave: la regularización (shrinkage) y que el R² fuera de muestra es una mala medida del valor económico. [Paper](https://doi.org/10.1111/jofi.13298)
- **Machine learning for stock return prediction: Transformers or simple neural networks** — Wang, *Finance Research Letters*, 2025. Compara transformers contra redes simples para predecir acciones.
- **Estimating profitability decomposition frameworks via machine learning** — Binz, Schipper y Standridge, *Journal of Accounting and Economics*, 2025 (uno de los más citados del año). ML aplicado a análisis de estados financieros y pronóstico de utilidades.

### 2.2 Agentes de trading con LLM (el tema más caliente)

- **Agentic Trading: When LLM Agents Meet Financial Markets** — Xia et al., arXiv 2605.19337 (mayo 2026). Revisión de 77 estudios; trata a los agentes como sistemas con ciclo percepción → memoria → razonamiento → ejecución. Buen punto de entrada.
- **StockBench: Can LLM Agents Trade Stocks Profitably?** — arXiv 2510.02209 (v2 marzo 2026). Resultado incómodo: la mayoría de los agentes no le gana a una estrategia base simple, aunque saquen buenas notas en preguntas de finanzas. Código abierto.
- **Toward Expert Investment Teams: A Multi-Agent LLM System** — Miyazaki, Kawahara, Roberts y Zohren (Oxford), arXiv 2602.23330 (feb 2026). Dividir el análisis en tareas finas mejora el desempeño.
- **Fin-Analyst (CLEF 2026 FinMMEval)** — arXiv 2607.12233. Agente híbrido con 8 especialistas LLM (noticias, reportes SEC, fundamentales, técnicos, sentimiento); quedó primero en TSLA con +13.51% en la competencia en vivo.
- **Autonomous LLM Agents Trading in Prediction Markets** — Wan Chu Cheong (LSE), 2026. En Polymarket, las billeteras de agentes LLM terminaron 12.1 puntos porcentuales más seguido del lado correcto que las humanas.
- **Machine Spirits: Speculation and Adaptation of LLM Agents in Asset Markets** — Saxena, Pangallo, Caccioli y del Rio-Chanona, 2026. Mercados simulados con agentes LLM: los mercados mixtos producen resultados muy variables.
- **The Memorization Problem: Can We Trust LLMs' Economic Forecasts?** — Lopez-Lira, Tang y Zhu, arXiv 2504.14765. Advertencia: los LLM "recuerdan" el pasado, así que sus backtests pueden estar inflados.

### 2.3 Replicación y el "zoológico de factores"

- **Is There a Replication Crisis in Finance?** — Jensen, Kelly y Pedersen, *Journal of Finance*, 2023. Con 153 factores en 93 países y un modelo bayesiano, encuentran que la mayoría de los factores sí se replica (82.4% vs. 35% del estudio de Hou, Xue y Zhang). Datos y código gratis en jkpfactors.com y GitHub.

## 3. Mercado por mercado

Cada mercado tiene: papers clave, la estrategia, la fórmula central y la función del código (sección 6) que la implementa.

### 3.1 Acciones (renta variable)

**Papers:** Jensen-Kelly-Pedersen (2023, replicación de factores); Kelly-Malamud-Zhou (2024, complejidad); *The Role of Intangible Investment in Predicting Stock Returns* (Li, *Financial Management*, 2025: seis décadas de evidencia de que la inversión en intangibles predice rendimientos); *Machine learning approach to stock price crash risk* (*Annals of Operations Research*, 2025).

**Estrategias:** modelos de factores (mercado, tamaño, valor, rentabilidad, momentum, baja volatilidad); momentum de sección cruzada 12-1 meses; ML con muchas variables y regularización.

**Fórmulas:**

- Modelo de factores: `r_i - r_f = α + β_MKT·MKT + β_SMB·SMB + β_HML·HML + ε`
- Momentum: `señal = P(t-21) / P(t-252) - 1` (se salta el último mes por la reversión de corto plazo)

**Código:** `regresion_factores()`, `momentum_seccion_cruzada()`

### 3.2 Renta fija (bonos y tasas)

**Papers:** *Predicting Individual Corporate Bond Returns* (Feng, He et al., *Journal of Banking & Finance*, feb 2025: con ML, R² fuera de muestra de 4.48% y Sharpe anual de 3.27); *Harness Machine Learning with Carry* (Qiao, Shi y Zhu, 2025: el carry, medible directo de la curva, compite muy bien contra el ML); *Forecasting the U.S. Treasury Yield Curve: A Distributionally Robust ML Approach* (Liu y Cheng, arXiv 2601.04608, 2026); *Bond Risk Premia with Machine Learning* (Bianchi, Büchner y Tamoni, *Review of Financial Studies*, base del tema).

**Estrategias:** carry y roll-down de bonos; predicción de primas por plazo con la forma de la curva + variables macro; inmunización por duración.

**Fórmulas:**

- Nelson-Siegel (curva de tasas): `y(τ) = β₀ + β₁·(1-e^(-τ/λ))/(τ/λ) + β₂·[(1-e^(-τ/λ))/(τ/λ) - e^(-τ/λ)]` (nivel, pendiente, curvatura; versión dinámica de Diebold y Li 2006)
- Duración modificada y convexidad: `ΔP/P ≈ -D_mod·Δy + ½·C·(Δy)²`
- Carry de un bono: rendimiento esperado si la curva no se mueve

**Código:** `nelson_siegel()`, `ajustar_ns()`, `duracion_convexidad()`

### 3.3 Divisas (FX)

**Contexto 2025:** el carry trade de divisas emergentes tuvo uno de sus mejores años desde 2009, con el dólar debilitándose; el peso mexicano, el real brasileño y el rand fueron monedas de destino populares, y el yen y el franco suizo las de fondeo.

**Papers:** la base sigue siendo Lustig, Roussanov y Verdelhan (factor carry y factor dólar) y Menkhoff et al. (momentum en divisas); en 2025 aparecen modelos con sentimiento macro de noticias (GDELT + FinBERT) aplicados a FX y futuros del Tesoro (arXiv mayo 2025).

**Estrategias:** carry (comprar monedas de tasa alta, vender las de tasa baja); momentum de divisas; value por paridad de poder de compra; diversificar la moneda de fondeo para bajar el riesgo de desplome.

**Fórmulas:**

- Paridad cubierta de tasas: `F = S·(1+i_local)/(1+i_extranjera)`
- Rendimiento del carry: `r ≈ (i_extranjera - i_local) + ΔS/S` (el riesgo está en ΔS: puede borrar meses de ganancia en días)

**Código:** `carry_trade()`

### 3.4 Materias primas (commodities)

**Papers:** *Basis-Momentum* (Boons y Porras Prado, *Journal of Finance*, 2019: la diferencia de momentum entre el 1er y 2do vencimiento del futuro es el mejor predictor de rendimientos en commodities; Sharpe cercano a 0.9); *Short-Term Basis Reversal* (Rossi, Zhang y Zhu, mayo 2025: 22 futuros de energía, metales, ganado y agricultura, 1980-2022); *An Anatomy of Commodity Futures Risk Premia* (Szymanowska et al., base teórica de primas spot y por plazo).

**Estrategias:** carry/roll yield (comprar commodities en backwardation, vender en contango); basis-momentum; time-series momentum.

**Fórmulas:**

- Costo de acarreo: `F = S·e^((r + u - y)·T)` (u = almacenaje, y = convenience yield)
- Roll yield anualizado: `(F₁/F₂ - 1)·365/días`
- Basis-momentum: `momentum(F₁) - momentum(F₂)` en 12 meses

**Código:** `basis_momentum()`, `roll_yield()`

### 3.5 Derivados y volatilidad

**Papers:** *Pricing American options under rough volatility using deep-signatures and signature-kernels* (Bayer, Pelizzari y Zhu, 2025); *A time-stepping deep gradient flow method for option pricing in (rough) diffusion models* (Papapantoleon y Rou, *Quantitative Finance*, nov 2025); *On options-driven realized volatility forecasting via rough volatility* (Fan, Wang y Ye, arXiv 2604.02743, abril 2026); *Model-Free Deep Hedging with Transaction Costs* (Brugière y Turinici, 2025); *Volatility Calibration via Automatic Local Regression* (arXiv sept 2025).

**Tendencia:** volatilidad "rugosa" (rough volatility, exponente de Hurst H ≈ 0.1) + redes neuronales como sustituto rápido del pricing; deep hedging (cubrir con redes en lugar de la delta teórica, con costos de transacción).

**Fórmulas:**

- Black-Scholes: `C = S·N(d₁) - K·e^(-rT)·N(d₂)`, `d₁ = [ln(S/K) + (r + σ²/2)T]/(σ√T)`, `d₂ = d₁ - σ√T`
- Heston: `dv = κ(θ - v)dt + ξ√v dW`; rough Bergomi usa movimiento browniano fraccional
- Griegas: delta `N(d₁)`, gamma `N'(d₁)/(Sσ√T)`, vega `S·N'(d₁)√T`

**Código:** `black_scholes()`, `monte_carlo_call()`, `garch11()`

### 3.6 Microestructura y trading de alta frecuencia

**Papers:** *Zero-shot adaptation to order book dynamics* (arXiv 2605.21707, mayo 2026: mantiene la estructura de Avellaneda-Stoikov y la adapta a regímenes con RL; probado en el libro de órdenes de BTCUSDT); *Multi-Level Market Making with Reinforcement Learning* (arXiv 2608.18195, 2026); *Deep Reinforcement Learning in Non-Markov Market-Making* (Lalor y Swishchuk, *Risks*, 2025, con procesos de Hawkes); *Shortermism and excessive risk taking in optimal execution* (Barucci y Lan, 2025).

**Estrategias:** market making con control de inventario; ejecución óptima de órdenes grandes; señales de desequilibrio del libro de órdenes (OFI).

**Fórmulas:**

- Avellaneda-Stoikov: precio de reserva `r = s - q·γ·σ²·(T-t)`; spread óptimo `δ = γσ²(T-t) + (2/γ)·ln(1 + γ/k)`
- Almgren-Chriss: inventario óptimo `x(t) = X·sinh(κ(T-t))/sinh(κT)`

**Código:** `avellaneda_stoikov()`, `almgren_chriss()`

### 3.7 Cripto y finanzas descentralizadas (DeFi)

**Papers:** *Automated Market Making and Loss-Versus-Rebalancing* (Milionis, Moallemi, Roughgarden y Zhang: el "Black-Scholes de los AMMs"; un LP cubierto en Uniswap v2 ETH-USDC llegó a Sharpe de hasta 18.2 según la frecuencia de rebalanceo); *Modeling LVR via Continuous-Installment Options* (arXiv 2508.02971, ago 2025); *Liquidity provision of utility indifference type in DEXs* (Fukasawa, Maire y Wunsch, 2025); *A multi-layer ML approach for cryptocurrency trading* (2025, indicadores técnicos + sentimiento).

**Estrategias:** proveer liquidez cubierta (LP + short del activo); arbitraje CEX-DEX; funding rate de perpetuos.

**Fórmulas:**

- AMM de producto constante: `x·y = k`
- LVR (Uniswap v2): `LVR ≈ (σ²/8)·V` por unidad de tiempo, V = valor del pool
- Pérdida impermanente: `IL = 2√ρ/(1+ρ) - 1`, ρ = cambio de precio

**Código:** `lvr_producto_constante()`, `impermanent_loss()`

### 3.8 Mercados de predicción (Kalshi, Polymarket)

**Papers:** *Prediction market efficiency: evidence from Kalshi* (Subramanian, *Int. J. of Financial Markets and Derivatives*, oct 2026: 103,003 mercados resueltos en 16 categorías); *Decomposing Crowd Wisdom* (Le, arXiv 2602.19520, 2026: 292 millones de operaciones en 327,000 contratos; a un mes del cierre, un contrato a 70 centavos acierta cerca de 75% de las veces); *The Accuracy and Efficiency of $2.4 Billion in the 2024 Presidential Election* (Clinton y Huang, Vanderbilt: acierto de 93% en PredictIt, 78% en Kalshi y 67% en Polymarket); *Capital Lock-Up and Settlement Discounting in Prediction Markets* (Gebele, TUM, 2026); *Uniform-Loss Automated Market Making for Prediction Markets* (Moallemi, AFT 2026); *The Anatomy of Polymarket* (arXiv 2603.03136, 2026).

**Estrategias:** calibración (comprar favoritos a largo plazo, que suelen estar subvaluados); arbitraje entre plataformas; dimensionar apuestas con Kelly.

**Fórmulas:**

- Kelly para contrato binario: `f* = (p - precio)/(1 - precio)`
- LMSR (Hanson): `precio_i = e^(q_i/b) / Σ e^(q_j/b)`
- Brier score: `(1/N)·Σ(p - resultado)²`

**Código:** `kelly_binario()`, `lmsr_precio()`, `brier()`

### 3.9 Transversal: riesgo y construcción de portafolios

**Papers:** *CVaR-based risk parity model with machine learning* (Sheng et al., *Pacific-Basin Finance Journal*, 2025); *Adaptive and Regime-Aware RL for Portfolio Optimization* (arXiv 2509.14385); *Neural Functionally Generated Portfolios* (Monoyios y Pricilia, 2025); *Time Series Momentum* (Moskowitz, Ooi y Pedersen, 2012, base del momentum multi-activo).

**Fórmulas:**

- Markowitz mínima varianza: `w = Σ⁻¹1 / (1'Σ⁻¹1)`
- Risk parity: cada activo aporta el mismo riesgo, `w_i·(Σw)_i` igual para todos
- VaR y Expected Shortfall al 99%; Sharpe = `media/desv · √252`
- GARCH(1,1): `σ²_t = ω + α·r²_(t-1) + β·σ²_(t-1)`
- Time-series momentum con objetivo de volatilidad: `w = signo(r_12m)·σ_objetivo/σ_activo`

**Código:** `min_varianza()`, `risk_parity()`, `var_es()`, `garch11()`, `tsmom()`, `sharpe()`

## 4. Cursos recomendados

Solo se incluyen programas de universidades líderes en investigación financiera, con profesores que publican en la frontera del tema (IA, trading algorítmico, ingeniería financiera). Todos fueron verificados como vigentes en 2026.

| Curso | Institución | Por qué destaca | Costo | Nivel |
| --- | --- | --- | --- | --- |
| Financial Markets | **Yale** (Coursera) | Lo imparte Robert Shiller, Premio Nobel de Economía; panorama de todos los mercados | Gratis (auditar) | Principiante |
| Finance & Quantitative Modeling for Analysts | **Wharton, UPenn** (Coursera) | La escuela de negocios de referencia en finanzas | Gratis (auditar) | Principiante |
| Mathematical Methods for Quantitative Finance | **MIT** (MITx en edX) | La base matemática de todo lo cuantitativo | Gratis (auditar) | Intermedio |
| Foundations of Modern Finance I y II | **MIT Sloan** (MITx en edX) | Valuación, riesgo, bonos y CAPM con rigor de posgrado | Gratis (auditar) | Intermedio |
| 18.S096 Topics in Mathematics with Applications in Finance | **MIT** (OpenCourseWare) | Curso real del MIT con ponentes de la industria: series de tiempo, cálculo estocástico, portafolios | Gratis | Avanzado |
| Financial Engineering and Risk Management (5 cursos) | **Columbia, IEOR** (Coursera) | Derivados, tasas y crédito, optimización de portafolios, derivados de energía y trading algorítmico; Python y Excel | Gratis (auditar) | Intermedio-avanzado |
| Machine Learning and Reinforcement Learning in Finance (4 cursos) | **NYU Tandon** (Coursera) | De los pocos cursos con aprendizaje por refuerzo aplicado a finanzas (Igor Halperin) | Gratis (auditar) | Avanzado |
| Oxford Algorithmic Trading Programme | **Oxford, Saïd Business School** | Pionero en trading algorítmico con IA; participa el director del Oxford-Man Institute of Quantitative Finance | De pago (\~£2,100, 6 semanas) | Profesional |
| Artificial Intelligence for Financial Services | **MIT Sloan** Executive Education | Nuevo en 2026; lo dirige Andrew Lo, director del Laboratorio de Ingeniería Financiera del MIT | De pago | Profesional |

**Ruta sugerida (si estás en prepa):** Yale (Shiller) → Wharton → Mathematical Methods del MIT → Foundations of Modern Finance del MIT. Con cálculo y probabilidad universitarios ya puedes seguir con Columbia (ingeniería financiera) y NYU (machine learning en finanzas), y después con 18.S096 del MIT. Los programas de Oxford y MIT Sloan Executive Education están pensados para profesionales; son una buena meta a futuro. En los cursos de Coursera y edX, "auditar" significa ver todo el contenido gratis; solo pagas si quieres el certificado.

**Fuentes de los cursos:** [Oxford Algorithmic Trading Programme](https://www.sbs.ox.ac.uk/programmes/executive-education/online-learning/oxford-algorithmic-trading-programme) · [MIT Sloan, AI for Financial Services](https://executive.mit.edu/course/artificial-intelligence-for-financial-services/a05U100000BIm1RIAT.html) · [Columbia, Financial Engineering and Risk Management](https://cvn.columbia.edu/content/financial-engineering-and-risk-management-specialization) · [NYU, ML and RL in Finance](https://www.coursera.org/specializations/machine-learning-reinforcement-finance)

## 5. Librerías y datos abiertos

| Herramienta | Para qué | Mercado |
| --- | --- | --- |
| QuantLib (C++ con Python: `pip install QuantLib`) | Valuar derivados, curvas de tasas, riesgo | Derivados, renta fija |
| vectorbt | Backtesting vectorizado muy rápido | Todos |
| Backtrader / Zipline | Backtesting por eventos | Acciones, futuros |
| Qlib (Microsoft) | Plataforma de investigación cuantitativa con IA | Acciones |
| FinRL | Aprendizaje por refuerzo para trading | Todos |
| freqtrade | Bot de trading de cripto con backtesting | Cripto |
| gs-quant (Goldman Sachs) | Herramientas de valuación y riesgo | Multi-activo |
| arch | Modelos GARCH y volatilidad | Todos |
| StockBench | Benchmark abierto de agentes LLM | Acciones |
| JKP Factors (jkpfactors.com) | 153 factores en 93 países, gratis | Acciones |
| awesome-quant (GitHub wilsonfreitas) | Lista curada de cientos de librerías | Todos |

Para seguir papers nuevos: arXiv q-fin (unos 160-200 papers al mes), SSRN, NBER y el boletín semanal NEP-FMK de RePEc.

## 6. Código completo (probado)

Un solo archivo con todos los modelos de la sección 3. Solo necesita `numpy` y `scipy` (`pip install numpy scipy`). Usa datos sintéticos para correr sin internet; para datos reales puedes cambiar las entradas por precios de `yfinance` u otra fuente.

Se corrió y validó: el call de Black-Scholes (S=K=100, T=1, r=5%, σ=20%) da 10.4506, el valor de referencia de los libros, y la simulación Monte Carlo da 10.46; la regresión de factores recupera las betas con las que se generaron los datos (1.09, 0.40, -0.29 vs. 1.1, 0.4, -0.3).

```python
"""Modelos cuantitativos por mercado. Solo numpy/scipy. Datos sintéticos para que corra sin internet."""
import numpy as np
from scipy.stats import norm
from scipy.optimize import least_squares

rng = np.random.default_rng(42)

# ---------- 1. DERIVADOS: Black-Scholes + griegas ----------
def black_scholes(S, K, T, r, sigma, tipo="call"):
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if tipo == "call":
        precio = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        delta = norm.cdf(d1)
    else:
        precio = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
        delta = norm.cdf(d1) - 1
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    vega = S * norm.pdf(d1) * np.sqrt(T)
    return precio, delta, gamma, vega

def monte_carlo_call(S, K, T, r, sigma, n=200_000):
    Z = rng.standard_normal(n)
    ST = S * np.exp((r - 0.5 * sigma**2) * T + sigma * np.sqrt(T) * Z)
    return np.exp(-r * T) * np.maximum(ST - K, 0).mean()

# ---------- 2. ACCIONES: factores y momentum ----------
def regresion_factores(r_activo, factores):
    X = np.column_stack([np.ones(len(factores)), factores])
    beta, *_ = np.linalg.lstsq(X, r_activo, rcond=None)
    return beta  # [alfa, beta_mercado, beta_SMB, beta_HML]

def momentum_seccion_cruzada(precios, lookback=252, skip=21):
    """Rendimiento 12-1 meses; compra el quintil alto, vende el bajo."""
    ret = precios[-skip - 1] / precios[-lookback - 1] - 1
    q = np.quantile(ret, [0.2, 0.8])
    pesos = np.where(ret >= q[1], 1.0, np.where(ret <= q[0], -1.0, 0.0))
    return pesos / np.abs(pesos).sum()

# ---------- 3. RENTA FIJA: Nelson-Siegel, duración, convexidad ----------
def nelson_siegel(tau, b0, b1, b2, lam):
    x = tau / lam
    f = (1 - np.exp(-x)) / x
    return b0 + b1 * f + b2 * (f - np.exp(-x))

def ajustar_ns(plazos, tasas):
    res = least_squares(lambda p: nelson_siegel(plazos, *p) - tasas,
                        x0=[tasas[-1], tasas[0] - tasas[-1], 0.0, 2.0],
                        bounds=([-1, -1, -1, 0.05], [1, 1, 1, 30]))
    return res.x  # nivel, pendiente, curvatura, lambda

def duracion_convexidad(cupon, ytm, n_anios, freq=2):
    t = np.arange(1, n_anios * freq + 1) / freq
    cf = np.full_like(t, cupon / freq * 100); cf[-1] += 100
    df = (1 + ytm / freq) ** (-t * freq)
    precio = (cf * df).sum()
    mac = (t * cf * df).sum() / precio
    mod = mac / (1 + ytm / freq)
    conv = (cf * df * t * (t + 1 / freq)).sum() / (precio * (1 + ytm / freq) ** 2)
    return precio, mod, conv

# ---------- 4. DIVISAS: carry trade ----------
def carry_trade(tasas_extranjeras, tasa_local, n_long=3, n_short=3):
    carry = tasas_extranjeras - tasa_local
    orden = np.argsort(carry)
    pesos = np.zeros_like(carry)
    pesos[orden[-n_long:]] = 1 / n_long
    pesos[orden[:n_short]] = -1 / n_short
    return pesos, carry @ pesos  # carry esperado si el tipo de cambio no se mueve

# ---------- 5. MATERIAS PRIMAS: basis-momentum y roll yield ----------
def basis_momentum(f1, f2, ventana=252):
    """Boons y Porras Prado (2019)."""
    m1 = f1[-1] / f1[-ventana - 1] - 1
    m2 = f2[-1] / f2[-ventana - 1] - 1
    return m1 - m2

def roll_yield(f1, f2, dias_entre_vencimientos=30):
    return (f1 / f2 - 1) * 365 / dias_entre_vencimientos  # >0 = backwardation

# ---------- 6. MULTI-ACTIVO: time-series momentum ----------
def tsmom(retornos, vol_obj=0.40, lookback=252):
    """Moskowitz, Ooi y Pedersen (2012)."""
    senal = np.sign(retornos[-lookback:].sum(axis=0))
    vol = retornos[-63:].std(axis=0) * np.sqrt(252)
    return senal * vol_obj / vol / retornos.shape[1]

# ---------- 7. MICROESTRUCTURA: Avellaneda-Stoikov y Almgren-Chriss ----------
def avellaneda_stoikov(mid, inventario, gamma, sigma, T_rest, k):
    r = mid - inventario * gamma * sigma**2 * T_rest
    spread = gamma * sigma**2 * T_rest + (2 / gamma) * np.log(1 + gamma / k)
    return r - spread / 2, r + spread / 2  # bid, ask

def almgren_chriss(X, T, N, sigma, eta, lam):
    tau = T / N
    kappa = np.arccosh(1 + lam * sigma**2 * tau**2 / (2 * eta)) / tau
    t = np.linspace(0, T, N + 1)
    return X * np.sinh(kappa * (T - t)) / np.sinh(kappa * T)

# ---------- 8. CRIPTO / DeFi: LVR y pérdida impermanente ----------
def lvr_producto_constante(valor_pool, sigma_anual):
    return sigma_anual**2 / 8 * valor_pool  # costo anual esperado para LPs

def impermanent_loss(ratio_precio):
    return 2 * np.sqrt(ratio_precio) / (1 + ratio_precio) - 1

# ---------- 9. MERCADOS DE PREDICCIÓN: Kelly, LMSR, Brier ----------
def kelly_binario(p_propia, precio):
    return max((p_propia - precio) / (1 - precio), 0.0)

def lmsr_precio(q, b):
    e = np.exp(q / b)
    return e / e.sum()

def brier(prob, resultado):
    return np.mean((prob - resultado) ** 2)

# ---------- 10. RIESGO Y PORTAFOLIO ----------
def var_es(retornos, alfa=0.99):
    var = -np.quantile(retornos, 1 - alfa)
    es = -retornos[retornos <= -var].mean()
    return var, es

def min_varianza(cov):
    inv = np.linalg.inv(cov); uno = np.ones(len(cov))
    return inv @ uno / (uno @ inv @ uno)

def risk_parity(cov, iters=500):
    w = np.ones(len(cov)) / len(cov)
    for _ in range(iters):
        rc = w * (cov @ w)
        w *= (rc.mean() / rc) ** 0.5
        w /= w.sum()
    return w

def garch11(r, omega, alpha, beta):
    s2 = np.empty_like(r); s2[0] = r.var()
    for t in range(1, len(r)):
        s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
    return np.sqrt(s2)

def sharpe(r, freq=252):
    return r.mean() / r.std() * np.sqrt(freq)


if __name__ == "__main__":
    print("Black-Scholes:", black_scholes(100, 100, 1, 0.05, 0.2))
    print("Monte Carlo:", monte_carlo_call(100, 100, 1, 0.05, 0.2))
    print("Bono 10a (precio, dur. mod., convexidad):", duracion_convexidad(0.05, 0.04, 10))
    print("Avellaneda-Stoikov (bid, ask):", avellaneda_stoikov(100, 5, 0.1, 2, 0.5, 1.5))
    print("LVR anual, pool de $1M con vol 80%:", lvr_producto_constante(1e6, 0.8))
    print("Kelly p=0.60, precio=0.50:", kelly_binario(0.6, 0.5))
```

**Resultados de la prueba:** bono a 10 años con cupón 5% y rendimiento 4%: precio 108.18, duración modificada 7.92; Avellaneda-Stoikov con inventario de 5 unidades: bid 98.26 y ask 99.75 (las cotizaciones bajan para deshacerse del inventario); LVR de un pool de $1M con 80% de volatilidad: $80,000 al año; Kelly con 60% de probabilidad propia y precio 0.50: apostar 20% del capital.

## 7. Papers de los videos de @vince.quant (TikTok)

[@vince.quant](https://www.tiktok.com/@vince.quant) es una cuenta de finanzas cuantitativas (11.5K seguidores) que explica en cada video un paper con sus límites y referencias. Se revisaron sus **47 videos** y se escogieron **43** que citan un paper o modelo concreto. Antes de incluirlos, se verificaron sus referencias en OpenAlex y arXiv.

**Descartados (4):** el anuncio de su newsletter; el video sobre el Information Coefficient, que no cita ninguna fuente; el de Soros contra el Banco de Inglaterra en 1992, que es una historia de mercado sin paper y que el propio autor reconoce con cifras disputadas; y el de cobertura delta básica, que ya cubre la sección 3.5.

**Errores y conflictos encontrados:** en el video "overnight vs. intraday", el DOI de Lou, Polk y Skouras lleva a otro paper; el correcto es 10.1016/j.jfineco.2019.03.011. Además, el autor es coautor del MinervaScore y dueño de la plataforma Minerva (su enlace en la bio), así que ese video tiene conflicto de interés. Aun así, lo incluimos porque publica su propio resultado negativo.

### 7.1 Volatilidad, derivados y crédito (5)

| Video | Paper | Idea clave | Código |
| --- | --- | --- | --- |
| [¿La volatilidad la mueven las noticias?](https://www.tiktok.com/@vince.quant/video/7638026616345529622) | Guyon y Lekeufack (2023), *Quantitative Finance* | Con solo rendimientos pasados se explica cerca de 90% de la volatilidad implícita del S&P 500 (dentro de muestra); la volatilidad depende sobre todo de la trayectoria | — |
| [¿Y si la volatilidad nunca fue suave?](https://www.tiktok.com/@vince.quant/video/7641646346843245857) | Gatheral, Jaisson y Rosenbaum (2018); Hager, Horst, Wagenhofer y Xu (arXiv 2603.13170, 2026) | Volatilidad "rugosa" con Hurst ≈ 0.1; el preprint de 2026 la deriva del flujo de órdenes | — |
| [¿Cubrir una opción sin saber su volatilidad?](https://www.tiktok.com/@vince.quant/video/7691461932414487841) | El Karoui, Jeanblanc-Picqué y Shreve (1998), *Mathematical Finance* | Si cubres con una volatilidad siempre mayor a la real, la cobertura no pierde en ninguna trayectoria | `pnl_cobertura()` |
| [Por qué desconfiar de Monte Carlo](https://www.tiktok.com/@vince.quant/video/7650575304817118497) | Mandelbrot (1963); Cont (2001); Gabaix et al. (2003, *Nature*); Peters (2019) | Simula tus supuestos, no los verifica: colas pesadas, memoria de volatilidad y la diferencia entre la media del conjunto y una trayectoria típica | — |
| [La ecuación detrás de 2008](https://www.tiktok.com/@vince.quant/video/7646112181519404320) | Li (2000), *Journal of Fixed Income* | Cópula gaussiana para CDOs: un solo parámetro de correlación que falló cuando los incumplimientos se agruparon | — |

### 7.2 Burbujas, regímenes y riesgo sistémico (5)

| Video | Paper | Idea clave | Código |
| --- | --- | --- | --- |
| [¿Cómo predicen una burbuja?](https://www.tiktok.com/@vince.quant/video/7648366968596122912) | Phillips, Shi y Yu (2015), *International Economic Review* | Prueba recursiva (SADF/GSADF) que detecta un régimen explosivo mientras ocurre, pero no predice cuándo revienta | `sadf()` |
| [NLP para detectar burbujas](https://www.tiktok.com/@vince.quant/video/7638388467214339331) | Cao, Shao, Yan y Geman (2025), Johns Hopkins, preprint | Combina LPPL de Sornette, sentimiento con FinBERT y un índice de atención mediática en un Transformer; probado solo en 32 acciones | — |
| [Detectar cambios de régimen en tiempo real](https://www.tiktok.com/@vince.quant/video/7665436911741177121) | Shu, Yu y Mulvey (2024, Princeton), *J. of Asset Management*; Bemporad et al. (2018) | "Statistical jump model": clustering con penalización por cambiar de estado; cambia de señal menos que un HMM y redujo caídas en S&P, DAX y Nikkei | — |
| [¿Cuándo vender una acción que sigue subiendo?](https://www.tiktok.com/@vince.quant/video/7652814545672539425) | Dai, Zhang y Zhu (2010), *SIAM J. Financial Math* | Con regímenes alcista y bajista ocultos, la regla óptima vende cuando la probabilidad de régimen alcista cae bajo un umbral, no según el precio | — |
| [Detectar un mercado frágil](https://www.tiktok.com/@vince.quant/video/7657337921137020193) | Kritzman, Li, Page y Rigobon (2011, MIT), *J. Portfolio Management* | "Absorption ratio": cuánta varianza absorben los primeros componentes principales; sube antes de las crisis | `absorption_ratio()` |

### 7.3 Eficiencia y estructura del mercado (9)

| Video | Paper | Idea clave |
| --- | --- | --- |
| [¿Son eficientes los mercados?](https://www.tiktok.com/@vince.quant/video/7638708965861231894) | Grossman y Stiglitz (1980), *AER* | Si la información cuesta, un mercado perfectamente eficiente no puede existir: siempre queda algo de alfa |
| [Hipótesis de mercados inelásticos](https://www.tiktok.com/@vince.quant/video/7639108958111681825) | Gabaix y Koijen (2021), NBER WP 28967 | Multiplicador ≈ 5: un dólar que entra a acciones sube la capitalización total unos 5 dólares (working paper, sin revisión por pares) |
| [¿Por qué el mercado se mueve cada día?](https://www.tiktok.com/@vince.quant/video/7658724052189629729) | Shiller (1981), *AER* | Los precios son mucho más volátiles que los dividendos que descuentan; citado por el Nobel 2013 |
| [¿Si todos usan la misma estrategia?](https://www.tiktok.com/@vince.quant/video/7678851890184047905) | Hanson y Sunderam (2014), *RFS* | El alfa que queda = desajuste × (1 − fracción de inversionistas que usan la señal); se mide con interés en corto |
| [Trading depredador](https://www.tiktok.com/@vince.quant/video/7671454876953562400) | Brunnermeier y Pedersen (2005), *Journal of Finance* | Si todos saben que un fondo tiene que vender, los demás venden con él y recompran en el fondo |
| [El "quant quake" de agosto 2007](https://www.tiktok.com/@vince.quant/video/7685159240763264289) | Khandani y Lo (2007, MIT), *J. Investment Management* | Estrategias de reversión muy apalancadas y concentradas perdieron cerca de 27% en tres días por una liquidación forzada |
| [Crowding y crashes de momentum](https://www.tiktok.com/@vince.quant/video/7655445298029825312) | Lou y Polk (2022, LSE), *RFS* | "Comomentum": la correlación anormal entre ganadores y perdedores mide qué tan saturado está el trade y anticipa rendimientos bajos |
| [¿Los fondos compran su propio rendimiento?](https://www.tiktok.com/@vince.quant/video/7683309762619985185) | van der Beck, Bouchaud y Villamaina (2024), Harvard WP | En ETFs concentrados, los flujos inflan precios por impacto, y los inversionistas persiguen ese rendimiento inflado |
| [Sentimiento: ¿ruido o señal?](https://www.tiktok.com/@vince.quant/video/7647602360021273889) | De Long et al. (1990); Shleifer y Vishny (1997); Baker y Wurgler (2006) | El sentimiento es ruido, riesgo y señal a la vez; si está alto, se esperan rendimientos bajos en acciones difíciles de valuar |

### 7.4 Anomalías y sesgos de backtest (4)

| Video | Paper | Idea clave |
| --- | --- | --- |
| [¿Las acciones suben mientras duermes?](https://www.tiktok.com/@vince.quant/video/7648745291696327969) | Lou, Polk y Skouras (2019), *JFE* (DOI correcto: 10.1016/j.jfineco.2019.03.011) | El momentum gana casi todo de noche; valor y baja volatilidad, de día |
| [¿Las acciones más volátiles rinden más?](https://www.tiktok.com/@vince.quant/video/7667342646741847329) | Ang, Hodrick, Xing y Zhang (2006, Columbia), *Journal of Finance* | No: las de mayor volatilidad idiosincrática rinden mucho menos, un rompecabezas que sigue sin explicación de consenso |
| [Nvidia 60 días después de resultados](https://www.tiktok.com/@vince.quant/video/7678127234648902944) | Bernard y Thomas (1989); Martineau (2022), *Critical Finance Review* | El "drift" posterior a resultados ya casi desapareció en acciones grandes desde 2006 |
| [Sesgo de supervivencia](https://www.tiktok.com/@vince.quant/video/7654760641697271072) | Shumway y Warther (1999), *Journal of Finance* | Al corregir los rendimientos de empresas deslistadas, el "efecto tamaño" en Nasdaq desaparece; usa datos point-in-time |

### 7.5 Tendencia y señales (5)

| Video | Paper | Idea clave | Código |
| --- | --- | --- | --- |
| [Cruce de medias exponenciales](https://www.tiktok.com/@vince.quant/video/7662892707567652129) | Brock, Lakonishok y LeBaron (1992); Sullivan, Timmermann y White (1999); Hurst, Ooi y Pedersen (2017); Levine y Pedersen (2016) | El cruce de EMAs es una medida de momentum; la ventaja en un solo activo desapareció, pero el time-series momentum diversificado sigue funcionando | `senal_ema()` |
| [Canal de Donchian (las "Tortugas")](https://www.tiktok.com/@vince.quant/video/7663589331436719393) | Las mismas referencias + historia de Dennis y Eckhardt | Ruptura del máximo o mínimo de 20 días; las ganancias de los Turtles son historia sin auditar | `senal_donchian()` |
| [Dividir la posición entre la volatilidad](https://www.tiktok.com/@vince.quant/video/7683702624553536801) | Harvey et al. (2018, Man Group), *J. Portfolio Management* | El volatility targeting mejora el Sharpe en activos de riesgo y siempre reduce la volatilidad de la volatilidad | `vol_target()` |
| [Ornstein-Uhlenbeck y pairs trading](https://www.tiktok.com/@vince.quant/video/7641379783162596640) | Uhlenbeck y Ornstein (1930) | `dX = θ(μ − X)dt + σdW`: modelo clásico de reversión a la media para spreads | `ajustar_ou()`, `zscore_pairs()` |
| [Signature trading](https://www.tiktok.com/@vince.quant/video/7685492396775197984) | Futter, Horvath (Oxford) y Wiese (2025), *Quantitative Finance* | Cualquier indicador se aproxima con la "firma" de la trayectoria; extiende Markowitz a estrategias que dependen del camino. Librerías: signatory, iisignature | — |

### 7.6 Ejecución y microestructura (2)

| Video | Paper | Idea clave | Código |
| --- | --- | --- | --- |
| [Vender un millón de acciones sin hundir el precio](https://www.tiktok.com/@vince.quant/video/7652137153161415969) | Almgren y Chriss (2000), *Journal of Risk* | Calendario óptimo de liquidación: TWAP si no hay aversión al riesgo, más cargado al inicio si la hay | `almgren_chriss()` (sección 6) |
| [Ley de la raíz cuadrada del impacto](https://www.tiktok.com/@vince.quant/video/7650178525793635616) | Bonart (2026, UCL), arXiv 2606.07059 | Explica por qué el impacto ∝ σ√(Q/V) y da una prueba de consistencia para modelos de impacto | `impacto_raiz()` |

### 7.7 Portafolios y limpieza de covarianza (10)

| Video | Paper | Idea clave | Código |
| --- | --- | --- | --- |
| [Frontera eficiente](https://www.tiktok.com/@vince.quant/video/7698826024460504352) | Markowitz (1952); Tobin (1958); Merton (1972); Broadie (1993) | El portafolio tangente maximiza el Sharpe; el error de estimación aleja la frontera calculada de la real | `min_varianza()` (sección 6) |
| [Una estrategia perdedora que te hace ganar](https://www.tiktok.com/@vince.quant/video/7691789099467935009) | Markowitz (1952) | Agregar una estrategia sube tu Sharpe si Sharpe\_nueva > ρ × Sharpe\_tuya; con ρ negativo, incluso una perdedora ayuda | `mejora_sharpe()` |
| [Penalizaciones = robustez](https://www.tiktok.com/@vince.quant/video/7687299730002529569) | Blanchet (Stanford), Chen y Zhou (Columbia) (2022), *Management Science* | Ridge o Lasso sobre los pesos equivale exactamente a protegerse del peor caso dentro de una bola de Wasserstein | — |
| [¿Por qué desconfiar de los optimizadores?](https://www.tiktok.com/@vince.quant/video/7668319896933109024) | Pafka y Kondor (2003), *Physica A* | El riesgo que reporta el optimizador es (1 − n/T) del real; con 500 activos y 750 días el real es 3 veces el predicho | `sesgo_optimizador()` |
| [Limpiar la covarianza de abajo hacia arriba](https://www.tiktok.com/@vince.quant/video/7655807373725945121) | Bongiorno y Challet (2022), *European J. of Finance* | k-BAHC: limpia las direcciones (eigenvectores) con clustering jerárquico; necesita unas 4 veces menos datos | — |
| [¿Y si nunca limpias la covarianza?](https://www.tiktok.com/@vince.quant/video/7673941163413343521) | Bongiorno y Challet (2024), *Quantitative Finance* | 10,000 backtests: el "Average Oracle" gana a la contracción no lineal con 19 veces menos rotación | — |
| [Un limpiador entrenado con el riesgo del portafolio](https://www.tiktok.com/@vince.quant/video/7684830015623531809) | Bongiorno, Manolakis y Mantegna (2026), *J. of Finance and Data Science* | RIEnet: red neuronal entrenada de punta a punta para minimizar la varianza; `pip install rienet` | — |
| [El error real dentro de los modelos de riesgo](https://www.tiktok.com/@vince.quant/video/7663208250577390880) | Goldberg, Papanicolaou y Shkolnik (2022, Berkeley), *SIAM JFM*; Goldberg y Kercheval (2023), *PNAS* | El error grande está en el eigenvector principal; se corrige con contracción tipo James-Stein | — |
| [Reparar la matriz de correlación](https://www.tiktok.com/@vince.quant/video/7684019834069257504) | Higham (2002), *IMA J. Numerical Analysis* | La matriz de correlación válida más cercana se obtiene con proyecciones alternadas y la corrección de Dykstra | `nearest_correlation()` |
| [Ganarle al mercado sin predecir](https://www.tiktok.com/@vince.quant/video/7654358350649478432) | Fernholz, Karatzas y Kardaras (2005, Columbia), *Finance and Stochastics* | Teoría estocástica de portafolios: el portafolio ponderado por diversidad le gana al mercado si éste se mantiene diverso | `diversity_weighted()` |

### 7.8 Validación de backtests y machine learning (3)

| Video | Paper | Idea clave | Código |
| --- | --- | --- | --- |
| [¿Qué es CPCV?](https://www.tiktok.com/@vince.quant/video/7649873862196301089) | López de Prado (2018), *Advances in Financial ML*; Bailey et al. (2017) | Validación cruzada combinatoria con purga y embargo: da una distribución de Sharpes y la probabilidad de sobreajuste (PBO) | — |
| [¿Ventaja real o suerte?](https://www.tiktok.com/@vince.quant/video/7680314011191201056) | Bailey y López de Prado (2014), Deflated Sharpe Ratio; Santoni, Jouanne y Scullin (2026, preprint, conflicto de interés) | El mejor Sharpe de miles de pruebas es casi siempre suerte; el DSR lo corrige. El MinervaScore no mostró poder predictivo en datos reales y los autores lo publicaron | `deflated_sharpe()` |
| [¿Qué tan complejo debe ser tu modelo?](https://www.tiktok.com/@vince.quant/video/7658455214260817184) | Kelly, Malamud y Zhou (2024); críticas de Nagel (2025) y Buncic (2025) | Actualiza la sección 2.1: hay debate abierto sobre si la "virtud de la complejidad" es en realidad un efecto de volatility timing | — |

### 7.9 Código de los modelos nuevos (probado)

Archivo aparte, `modelos_vince_quant.py`, con 14 funciones (solo numpy y scipy). Resultados de la prueba: el ajuste OU recupera la volatilidad real (0.298 vs. 0.30); SADF da −0.02 para una caminata aleatoria y 54.8 con una burbuja simulada; el absorption ratio sube de 0.33 en un mercado calmo a 0.85 en uno frágil; el Deflated Sharpe de la misma estrategia cae de 0.75 a 0.02 si se eligió entre 1,000 pruebas; Higham repara una matriz con un eigenvalor negativo (−0.354 → 0); y Pafka-Kondor da exactamente 3.00×, como en el video.

```python
def ajustar_ou(x, dt=1/252):
    b, a = np.polyfit(x[:-1], x[1:], 1)          # x_t = a + b x_{t-1}
    theta = -np.log(b) / dt
    mu = a / (1 - b)
    resid = x[1:] - (a + b * x[:-1])
    sigma = resid.std() * np.sqrt(2 * theta / (1 - b**2))
    return theta, mu, sigma, np.log(2) / theta   # vida media

def sadf(y, r0=0.2):                              # Phillips-Shi-Yu
    n0 = int(len(y) * r0)
    return max(adf_t(y[:k]) for k in range(n0, len(y) + 1))

def absorption_ratio(retornos, frac=0.2):          # Kritzman et al.
    eig = np.sort(np.linalg.eigvalsh(np.cov(retornos.T)))[::-1]
    k = max(1, int(len(eig) * frac))
    return eig[:k].sum() / eig.sum()

def deflated_sharpe(r, n_pruebas, var_sharpes):   # Bailey y Lopez de Prado
    T, sr = len(r), r.mean() / r.std()
    g = 0.5772156649
    sr0 = np.sqrt(var_sharpes) * ((1 - g) * norm.ppf(1 - 1/n_pruebas) + g * norm.ppf(1 - 1/(n_pruebas*np.e)))
    den = np.sqrt(1 - skew(r)*sr + (kurtosis(r, fisher=False) - 1)/4 * sr**2)
    return norm.cdf((sr - sr0) * np.sqrt(T - 1) / den)

def nearest_correlation(A, iters=200):            # Higham (2002)
    Y, dS = A.copy(), np.zeros_like(A)
    for _ in range(iters):
        R = Y - dS
        w, V = np.linalg.eigh(R)
        X = V @ np.diag(np.maximum(w, 0)) @ V.T
        dS = X - R
        Y = X.copy(); np.fill_diagonal(Y, 1.0)
    return Y

def diversity_weighted(pesos_mercado, p=0.5):      # Fernholz-Karatzas-Kardaras
    w = pesos_mercado**p
    return w / w.sum()

def impacto_raiz(sigma_diaria, Q, V, Y=0.7):       # ley de la raíz cuadrada
    return Y * sigma_diaria * np.sqrt(Q / V)
```

El archivo completo incluye también `adf_t`, `zscore_pairs`, `senal_ema`, `senal_donchian`, `vol_target`, `sesgo_optimizador`, `mejora_sharpe` y `pnl_cobertura`.

## 8. Advertencias y fuentes

**Antes de usar dinero real:** esto es material de estudio, no asesoría financiera. Los backtests sobreestiman casi siempre (sesgo de selección, costos de transacción, fugas de información del futuro y, con LLMs, memorización). El carry y el market making ganan poco a poco y pueden perder mucho de golpe. Practica primero con cuentas de papel.

### Fuentes principales

- [Kelly, Malamud y Zhou (2024), The Virtue of Complexity in Return Prediction](https://doi.org/10.1111/jofi.13298)
- [Jensen, Kelly y Pedersen (2023), Is There a Replication Crisis in Finance?](https://doi.org/10.1111/jofi.13249)
- [Xia et al. (2026), Agentic Trading: When LLM Agents Meet Financial Markets](https://arxiv.org/abs/2605.19337)
- [StockBench (2026)](https://arxiv.org/html/2510.02209v2)
- [Miyazaki et al. (2026), Multi-Agent LLM System with Fine-Grained Trading Tasks](https://arxiv.org/abs/2602.23330v1)
- [Fin-Analyst, CLEF 2026 FinMMEval](https://arxiv.org/abs/2607.12233)
- [Cheong (2026), Autonomous LLM Agents Trading on Polymarket](https://www.bayes.citystgeorges.ac.uk/__data/assets/pdf_file/0003/1013997/Wan-hu-Cheong-JMP-July-2026.pdf)
- [NEP-FMK, abril 2026 (Machine Spirits y otros)](https://nep.repec.org/nep-fmk/2026-04-27)
- [Predicting Individual Corporate Bond Returns (2025)](https://researchconnect.buffalo.edu/en/publications/predicting-individual-corporate-bond-returns/)
- [Qiao, Shi y Zhu (2025), Harness Machine Learning with Carry](https://www.pbcsf.tsinghua.edu.cn/__local/D/08/E0/762FDAFBA6C0E31DD3F3E0C0696_EE0D73B6_8D450E.pdf)
- [Liu y Cheng (2026), Forecasting the U.S. Treasury Yield Curve](https://www.arxiv.org/pdf/2601.04608)
- [Boons y Porras Prado, Basis-Momentum](https://4nations.albertjmenkveld.com/papers/boonsprado17.pdf)
- [Rossi, Zhang y Zhu (2025), Short-Term Basis Reversal (resumen)](https://www.cxoadvisory.com/commodity-futures/commodity-futures-term-structure-reversals)
- [Bayer, Pelizzari y Zhu (2025), American options under rough volatility](https://arxiv.org/abs/2501.06758v2)
- [Papapantoleon y Rou (2025), Deep gradient flow for rough diffusion models](https://repository.tudelft.nl/file/File_48be07b9-5750-44a3-a468-47befae2bb97)
- [Fan, Wang y Ye (2026), Options-driven realized volatility forecasting](https://arxiv.org/abs/2604.02743)
- [Brugière y Turinici (2025), Model-Free Deep Hedging](https://econpapers.repec.org/paper/arxpapers/2505.22836.htm)
- [Milionis et al., Automated Market Making and LVR](https://arxiv.org/abs/2208.06046v4)
- [LVR via Continuous-Installment Options (2025)](https://www.emergentmind.com/papers/2508.02971)
- [Zero-shot adaptation to order book dynamics (2026)](https://www.emergentmind.com/papers/2605.21707)
- [Multi-Level Market Making with RL (2026)](https://arxiv.org/pdf/2608.18195)
- [Lalor y Swishchuk (2025), Deep RL in Non-Markov Market-Making](https://mdpi.com/2227-9091/13/3/40)
- [Subramanian (2026), Prediction market efficiency: Kalshi](https://www.inderscience.com/info/inarticle.php?artid=157002)
- [Le (2026), Decomposing Crowd Wisdom](https://arxiv.org/html/2602.19520v1)
- [Clinton y Huang, $2.4 Billion in the 2024 Election](https://econpapers.repec.org/RePEc:osf:socarx:d5yx2_v1)
- [Gebele (2026), Capital Lock-Up in Prediction Markets](https://arxiv.org/html/2605.31431v1)
- [Moallemi (AFT 2026), Uniform-Loss AMM for Prediction Markets](https://drops.dagstuhl.de/storage/00lipics/lipics-vol395-aft2026/LIPIcs.AFT.2026.14/LIPIcs.AFT.2026.14.pdf)
- [Carry trade de emergentes en 2025 (Citi, Bloomberg)](https://www.investmentnews.com/emerging-markets/citi-says-biggest-carry-trade-rally-in-years-has-longer-to-run/261790)
- [Expansión: carry trade y el peso mexicano](https://expansion.mx/mercados/2025/05/14/factor-que-mantendra-fuerte-al-peso-mexicano-en-2025)
- [Cursos de finanzas cuantitativas 2026 (reseña)](https://www.quantt.co.uk/resources/best-online-quant-finance-courses-2026)
- [awesome-quant](https://github.com/wilsonfreitas/awesome-quant)

**Metodología:** 16 búsquedas web y en OpenAlex (base de datos académica), priorizando papers de 2025-2026 y revistas arbitradas. Algunos papers de 2026 son preprints de arXiv sin revisión por pares todavía; tómalos como resultados preliminares.
