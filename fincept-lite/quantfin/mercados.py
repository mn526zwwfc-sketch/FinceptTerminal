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

# ---------- 2. ACCIONES: factores (regresión tipo Fama-French) y momentum ----------
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

# ---------- 3. RENTA FIJA: Nelson-Siegel ----------
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
    """Compra monedas de tasa alta, vende las de tasa baja (diferencial vs. tasa local)."""
    carry = tasas_extranjeras - tasa_local
    orden = np.argsort(carry)
    pesos = np.zeros_like(carry)
    pesos[orden[-n_long:]] = 1 / n_long
    pesos[orden[:n_short]] = -1 / n_short
    return pesos, carry @ pesos  # carry esperado del portafolio (si FX no se mueve)

# ---------- 5. MATERIAS PRIMAS: basis y basis-momentum ----------
def basis_momentum(f1, f2, ventana=252):
    """Boons y Porras Prado (2019): momentum del 1er vencimiento menos el del 2do."""
    m1 = f1[-1] / f1[-ventana - 1] - 1
    m2 = f2[-1] / f2[-ventana - 1] - 1
    return m1 - m2

def roll_yield(f1, f2, dias_entre_vencimientos=30):
    return (f1 / f2 - 1) * 365 / dias_entre_vencimientos  # >0 = backwardation

# ---------- 6. MULTI-ACTIVO: time-series momentum con volatility targeting ----------
def tsmom(retornos, vol_obj=0.40, lookback=252):
    """Moskowitz, Ooi y Pedersen (2012): signo del rendimiento de 12m escalado por volatilidad."""
    señal = np.sign(retornos[-lookback:].sum(axis=0))
    vol = retornos[-63:].std(axis=0) * np.sqrt(252)
    return señal * vol_obj / vol / retornos.shape[1]

# ---------- 7. MICROESTRUCTURA: Avellaneda-Stoikov ----------
def avellaneda_stoikov(mid, inventario, gamma, sigma, T_rest, k):
    r = mid - inventario * gamma * sigma**2 * T_rest           # precio de reserva
    spread = gamma * sigma**2 * T_rest + (2 / gamma) * np.log(1 + gamma / k)
    return r - spread / 2, r + spread / 2                     # bid, ask

def almgren_chriss(X, T, N, sigma, eta, lam):
    """Trayectoria óptima de liquidación de X acciones en N pasos."""
    tau = T / N
    kappa = np.arccosh(1 + lam * sigma**2 * tau**2 / (2 * eta)) / tau
    t = np.linspace(0, T, N + 1)
    return X * np.sinh(kappa * (T - t)) / np.sinh(kappa * T)

# ---------- 8. CRIPTO / DeFi: AMM de producto constante y LVR ----------
def lvr_producto_constante(valor_pool, sigma_anual):
    """Milionis et al.: para x*y=k, LVR instantáneo = sigma^2/8 * valor del pool (por año)."""
    return sigma_anual**2 / 8 * valor_pool

def impermanent_loss(ratio_precio):
    return 2 * np.sqrt(ratio_precio) / (1 + ratio_precio) - 1

# ---------- 9. MERCADOS DE PREDICCIÓN: Kelly y LMSR ----------
def kelly_binario(p_propia, precio):
    """Fracción de capital a apostar al SÍ en un contrato que paga 1."""
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
    p, d, g, v = black_scholes(100, 100, 1, 0.05, 0.2)
    print(f"1) BS call={p:.4f} delta={d:.4f} gamma={g:.4f} vega={v:.4f} | MC={monte_carlo_call(100,100,1,0.05,0.2):.4f}")

    f = rng.normal(0, 0.01, (1000, 3))
    ra = 0.0002 + f @ np.array([1.1, 0.4, -0.3]) + rng.normal(0, 0.005, 1000)
    print("2) alfa/betas:", np.round(regresion_factores(ra, f), 4))
    precios = np.cumprod(1 + rng.normal(0.0003, 0.02, (300, 50)), axis=0)
    print("   momentum: largos", (momentum_seccion_cruzada(precios) > 0).sum(), "cortos", (momentum_seccion_cruzada(precios) < 0).sum())

    plazos = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30])
    tasas = nelson_siegel(plazos, 0.045, -0.01, 0.01, 1.8) + rng.normal(0, 0.0005, 10)
    print("3) NS (nivel, pendiente, curvatura, lambda):", np.round(ajustar_ns(plazos, tasas), 4))
    print("   bono 10a cupón 5% ytm 4%: precio, dur. mod., convexidad:", np.round(duracion_convexidad(0.05, 0.04, 10), 3))

    w, c = carry_trade(np.array([0.105, 0.0075, 0.045, 0.15, 0.0, 0.035, 0.07, 0.025]), 0.04)
    print("4) carry pesos:", np.round(w, 2), "carry esperado:", round(c, 4))

    f1 = np.cumprod(1 + rng.normal(0.0004, 0.015, 300)) * 70
    f2 = f1 * (1 + rng.normal(-0.005, 0.002, 300))
    print(f"5) basis-momentum={basis_momentum(f1, f2):.4f} roll yield={roll_yield(f1[-1], f2[-1]):.4f}")

    print("6) TSMOM pesos:", np.round(tsmom(rng.normal(0.0002, 0.01, (300, 5))), 3))

    print("7) A-S bid/ask:", np.round(avellaneda_stoikov(100, 5, 0.1, 2, 0.5, 1.5), 3))
    print("   Almgren-Chriss inventario:", np.round(almgren_chriss(1e5, 1, 5, 0.3, 2.5e-6, 1e-6), 0))

    print(f"8) LVR anual pool $1M vol 80%: ${lvr_producto_constante(1e6, 0.8):,.0f} | IL si precio x2: {impermanent_loss(2):.4f}")

    print(f"9) Kelly p=0.60 precio=0.50: {kelly_binario(0.6, 0.5):.2f} | LMSR:", np.round(lmsr_precio(np.array([30., 10.]), 20), 3),
          "| Brier:", round(brier(np.array([0.7, 0.2, 0.9]), np.array([1, 0, 1])), 4))

    r = rng.standard_t(4, 2000) * 0.01
    print("10) VaR/ES 99%:", np.round(var_es(r), 4), "Sharpe:", round(sharpe(r + 0.0003), 2))
    cov = np.array([[0.04, 0.006, 0.002], [0.006, 0.01, 0.001], [0.002, 0.001, 0.0025]])
    print("    min-var:", np.round(min_varianza(cov), 3), "risk parity:", np.round(risk_parity(cov), 3))
    print("    GARCH vol última:", round(garch11(r, 1e-6, 0.08, 0.9)[-1], 4))
