"""Modelos de los videos de @vince.quant (TikTok), implementados y probados. Solo numpy/scipy."""
import numpy as np
from scipy.stats import norm, skew, kurtosis

rng = np.random.default_rng(7)

# --- Ornstein-Uhlenbeck (pairs trading): dX = theta(mu - X)dt + sigma dW ---
def ajustar_ou(x, dt=1/252):
    """Ajuste exacto por AR(1): x_t = a + b x_{t-1} + e."""
    b, a = np.polyfit(x[:-1], x[1:], 1)
    theta = -np.log(b) / dt
    mu = a / (1 - b)
    resid = x[1:] - (a + b * x[:-1])
    sigma = resid.std() * np.sqrt(2 * theta / (1 - b**2))
    vida_media = np.log(2) / theta
    return theta, mu, sigma, vida_media

def zscore_pairs(spread, mu, sigma, theta, entrada=2.0):
    sd_eq = sigma / np.sqrt(2 * theta)
    z = (spread - mu) / sd_eq
    return z, np.where(z > entrada, -1, np.where(z < -entrada, 1, 0))

# --- Phillips-Shi-Yu: estadístico SADF (detección de burbujas explosivas) ---
def adf_t(y):
    dy, ylag = np.diff(y), y[:-1]
    X = np.column_stack([np.ones_like(ylag), ylag])
    beta, *_ = np.linalg.lstsq(X, dy, rcond=None)
    res = dy - X @ beta
    s2 = res @ res / (len(dy) - 2)
    se = np.sqrt(s2 * np.linalg.inv(X.T @ X)[1, 1])
    return beta[1] / se

def sadf(y, r0=0.2):
    """Sup ADF con ventanas crecientes; valores > ~1.5 sugieren régimen explosivo (valor crítico depende de n)."""
    n0 = int(len(y) * r0)
    return max(adf_t(y[:k]) for k in range(n0, len(y) + 1))

# --- Absorption ratio (Kritzman et al. 2011): fragilidad sistémica ---
def absorption_ratio(retornos, frac=0.2):
    eig = np.sort(np.linalg.eigvalsh(np.cov(retornos.T)))[::-1]
    k = max(1, int(len(eig) * frac))
    return eig[:k].sum() / eig.sum()

# --- Deflated Sharpe Ratio (Bailey y López de Prado 2014) ---
def deflated_sharpe(r, n_pruebas, var_sharpes):
    """Probabilidad de que el Sharpe (por periodo) sea real dado que probaste n_pruebas estrategias."""
    T, sr = len(r), r.mean() / r.std()
    g = 0.5772156649
    sr0 = np.sqrt(var_sharpes) * ((1 - g) * norm.ppf(1 - 1 / n_pruebas) + g * norm.ppf(1 - 1 / (n_pruebas * np.e)))
    num = (sr - sr0) * np.sqrt(T - 1)
    den = np.sqrt(1 - skew(r) * sr + (kurtosis(r, fisher=False) - 1) / 4 * sr**2)
    return norm.cdf(num / den)

# --- Higham (2002): matriz de correlación válida más cercana ---
def nearest_correlation(A, iters=200):
    Y, dS = A.copy(), np.zeros_like(A)
    for _ in range(iters):
        R = Y - dS
        w, V = np.linalg.eigh(R)
        X = V @ np.diag(np.maximum(w, 0)) @ V.T          # proyección a semidefinida positiva
        dS = X - R                                        # corrección de Dykstra
        Y = X.copy(); np.fill_diagonal(Y, 1.0)            # proyección a diagonal unitaria
    return Y

# --- Pafka-Kondor (2003): riesgo predicho = (1 - n/T) x riesgo real (desviación estándar) ---
def sesgo_optimizador(n, T):
    return 1 - n / T

# --- Teoría estocástica de portafolios: portafolio ponderado por diversidad ---
def diversity_weighted(pesos_mercado, p=0.5):
    w = pesos_mercado**p
    return w / w.sum()

# --- Tendencia: cruce de EMAs, canal de Donchian y volatility targeting ---
def ema(x, span):
    a, out = 2 / (span + 1), np.empty_like(x)
    out[0] = x[0]
    for t in range(1, len(x)):
        out[t] = a * x[t] + (1 - a) * out[t - 1]
    return out

def senal_ema(precios, rapida=20, lenta=100):
    return np.sign(ema(precios, rapida) - ema(precios, lenta))

def senal_donchian(precios, n=20):
    s = np.zeros(len(precios))
    for t in range(n, len(precios)):
        hi, lo = precios[t - n:t].max(), precios[t - n:t].min()
        s[t] = 1 if precios[t] > hi else (0 if precios[t] < lo else s[t - 1])
    return s

def vol_target(retornos, vol_obj=0.10, halflife=20):
    lam = 0.5 ** (1 / halflife)
    var = np.empty_like(retornos); var[0] = retornos[:20].var()
    for t in range(1, len(retornos)):
        var[t] = lam * var[t - 1] + (1 - lam) * retornos[t - 1] ** 2
    return vol_obj / np.sqrt(var * 252)   # apalancamiento a usar cada día

# --- Microestructura: ley de la raíz cuadrada del impacto ---
def impacto_raiz(sigma_diaria, Q, V, Y=0.7):
    return Y * sigma_diaria * np.sqrt(Q / V)

# --- Combinar estrategias: ¿una nueva sube tu Sharpe? ---
def mejora_sharpe(sharpe_nueva, sharpe_tuya, rho):
    return sharpe_nueva > rho * sharpe_tuya

# --- Robustez de Black-Scholes (El Karoui et al. 1998): P&L de cobertura con vol equivocada ---
def pnl_cobertura(S0=100, K=100, T=0.25, sig_cob=0.25, sig_real=0.20, n=252, sims=4000):
    dt = T / n
    pnl = np.zeros(sims)
    for i in range(sims):
        S = S0 * np.exp(np.cumsum((-0.5 * sig_real**2) * dt + sig_real * np.sqrt(dt) * rng.standard_normal(n)))
        S = np.insert(S, 0, S0)
        tau = T - np.arange(n + 1) * dt
        d1 = (np.log(S[:-1] / K) + 0.5 * sig_cob**2 * tau[:-1]) / (sig_cob * np.sqrt(tau[:-1]))
        delta = norm.cdf(d1)
        prima = S0 * norm.cdf((np.log(S0/K) + 0.5*sig_cob**2*T)/(sig_cob*np.sqrt(T))) - K * norm.cdf((np.log(S0/K) - 0.5*sig_cob**2*T)/(sig_cob*np.sqrt(T)))
        pnl[i] = prima + (delta * np.diff(S)).sum() - max(S[-1] - K, 0)
    return pnl.mean(), (pnl < 0).mean()


if __name__ == "__main__":
    x = np.zeros(2000)
    for t in range(1, 2000):
        x[t] = x[t-1] + 5 * (0 - x[t-1]) / 252 + 0.3 * np.sqrt(1/252) * rng.standard_normal()
    th, mu, sg, hl = ajustar_ou(x)
    print(f"OU: theta={th:.2f} (real 5) mu={mu:.3f} sigma={sg:.3f} (real 0.3) vida media={hl*252:.0f} días")

    rw = np.cumsum(rng.standard_normal(300)) + 100
    burbuja = rw.copy(); burbuja[200:] = burbuja[199] * 1.02 ** np.arange(1, 101)
    print(f"SADF caminata aleatoria={sadf(rw):.2f} | con burbuja={sadf(burbuja):.2f}")

    f = rng.standard_normal((500, 1))
    calmo = rng.standard_normal((500, 30)) * 0.01 + f * 0.003
    fragil = rng.standard_normal((500, 30)) * 0.01 + f * 0.02
    print(f"Absorption ratio calmo={absorption_ratio(calmo):.2f} frágil={absorption_ratio(fragil):.2f}")

    r = rng.normal(0.0006, 0.01, 1000)
    print(f"DSR con 1 prueba={deflated_sharpe(r, 2, 0.001):.3f} | con 1000 pruebas={deflated_sharpe(r, 1000, 0.001):.3f}")

    A = np.array([[1, .9, .7], [.9, 1, -.4], [.7, -.4, 1]])
    C = nearest_correlation(A)
    print("Higham: eig original", np.round(np.linalg.eigvalsh(A), 3), "-> reparada", np.round(np.linalg.eigvalsh(C), 3))
    print(f"Pafka-Kondor 500 activos/750 días: riesgo real = {1/sesgo_optimizador(500,750):.2f}x el predicho")
    print("Diversity-weighted:", np.round(diversity_weighted(np.array([.5, .3, .15, .05])), 3))

    p = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, 600)))
    print("EMA señal final:", senal_ema(p)[-1], "| Donchian:", senal_donchian(p)[-1], "| lev vol-target:", round(vol_target(np.diff(np.log(p)))[-1], 2))
    print(f"Impacto raíz: vender 1% del volumen diario con vol 2% = {impacto_raiz(0.02, 1, 100)*1e4:.0f} pb")
    print("¿Estrategia Sharpe -0.3, rho -0.8 mejora tu Sharpe 1?", mejora_sharpe(-0.3, 1, -0.8))
    m, p_neg = pnl_cobertura()
    print(f"Cobertura con vol 25% > real 20%: P&L medio={m:.2f}, prob. pérdida={p_neg:.3f}")
