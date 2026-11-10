"""Pruebas contra valores de referencia conocidos (libros y papers)."""
import numpy as np
import pytest

from quantfin import mercados as m
from quantfin import avanzados as a


# ---------- mercados.py ----------
def test_black_scholes_valor_de_libro():
    precio, delta, gamma, vega = m.black_scholes(100, 100, 1, 0.05, 0.2)
    assert precio == pytest.approx(10.4506, abs=1e-4)
    assert delta == pytest.approx(0.6368, abs=1e-4)


def test_paridad_put_call():
    c = m.black_scholes(100, 95, 0.5, 0.03, 0.25, "call")[0]
    p = m.black_scholes(100, 95, 0.5, 0.03, 0.25, "put")[0]
    assert c - p == pytest.approx(100 - 95 * np.exp(-0.03 * 0.5), abs=1e-8)


def test_monte_carlo_converge_a_black_scholes():
    assert m.monte_carlo_call(100, 100, 1, 0.05, 0.2) == pytest.approx(10.4506, abs=0.15)


def test_regresion_factores_recupera_betas():
    rng = np.random.default_rng(0)
    f = rng.normal(0, 0.01, (5000, 3))
    r = 0.0002 + f @ np.array([1.1, 0.4, -0.3]) + rng.normal(0, 0.002, 5000)
    beta = m.regresion_factores(r, f)
    assert np.allclose(beta[1:], [1.1, 0.4, -0.3], atol=0.03)


def test_nelson_siegel_ajuste():
    plazos = np.array([0.25, 0.5, 1, 2, 3, 5, 7, 10, 20, 30])
    tasas = m.nelson_siegel(plazos, 0.045, -0.01, 0.01, 1.8)
    p = m.ajustar_ns(plazos, tasas)
    assert np.allclose(m.nelson_siegel(plazos, *p), tasas, atol=1e-6)


def test_bono_a_la_par():
    precio, dur, conv = m.duracion_convexidad(0.05, 0.05, 10)
    assert precio == pytest.approx(100, abs=1e-8)
    assert 7 < dur < 8.5 and conv > 0


def test_carry_trade_neutral():
    w, c = m.carry_trade(np.array([0.10, 0.01, 0.05, 0.15, 0.0, 0.03]), 0.04, 2, 2)
    assert w.sum() == pytest.approx(0) and c > 0


def test_avellaneda_stoikov_inventario_baja_cotizaciones():
    bid0, ask0 = m.avellaneda_stoikov(100, 0, 0.1, 2, 0.5, 1.5)
    bid5, ask5 = m.avellaneda_stoikov(100, 5, 0.1, 2, 0.5, 1.5)
    assert bid5 < bid0 and ask5 < ask0 and ask0 - bid0 == pytest.approx(ask5 - bid5)


def test_almgren_chriss_extremos():
    x = m.almgren_chriss(1e5, 1, 10, 0.3, 2.5e-6, 1e-6)
    assert x[0] == pytest.approx(1e5) and x[-1] == pytest.approx(0, abs=1e-6)
    assert np.all(np.diff(x) <= 0)


def test_lvr_e_impermanent_loss():
    assert m.lvr_producto_constante(1e6, 0.8) == pytest.approx(80_000)
    assert m.impermanent_loss(1) == pytest.approx(0)
    assert m.impermanent_loss(2) == pytest.approx(-0.0572, abs=1e-4)


def test_kelly_y_lmsr():
    assert m.kelly_binario(0.6, 0.5) == pytest.approx(0.2)
    assert m.kelly_binario(0.4, 0.5) == 0
    assert m.lmsr_precio(np.array([5.0, 5.0]), 10).sum() == pytest.approx(1)


def test_risk_parity_contribuciones_iguales():
    cov = np.array([[0.04, 0.006, 0.002], [0.006, 0.01, 0.001], [0.002, 0.001, 0.0025]])
    w = m.risk_parity(cov)
    rc = w * (cov @ w)
    assert np.allclose(rc, rc.mean(), rtol=1e-4) and w.sum() == pytest.approx(1)


# ---------- avanzados.py ----------
def test_pafka_kondor_valor_del_paper():
    assert 1 / a.sesgo_optimizador(500, 750) == pytest.approx(3.0)


def test_nearest_correlation_es_valida():
    A = np.array([[1, .9, .7], [.9, 1, -.4], [.7, -.4, 1]])
    C = a.nearest_correlation(A)
    assert np.linalg.eigvalsh(C).min() > -1e-6
    assert np.allclose(np.diag(C), 1)


def test_sadf_detecta_burbuja():
    rng = np.random.default_rng(1)
    rw = np.cumsum(rng.standard_normal(300)) + 100
    burbuja = rw.copy()
    burbuja[200:] = burbuja[199] * 1.02 ** np.arange(1, 101)
    assert a.sadf(burbuja) > 5 > a.sadf(rw)


def test_absorption_ratio_sube_con_fragilidad():
    rng = np.random.default_rng(2)
    f = rng.standard_normal((500, 1))
    calmo = rng.standard_normal((500, 30)) * 0.01 + f * 0.003
    fragil = rng.standard_normal((500, 30)) * 0.01 + f * 0.02
    assert a.absorption_ratio(fragil) > a.absorption_ratio(calmo)


def test_deflated_sharpe_baja_con_mas_pruebas():
    r = np.random.default_rng(3).normal(0.0006, 0.01, 1000)
    assert a.deflated_sharpe(r, 1000, 0.001) < a.deflated_sharpe(r, 2, 0.001)


def test_ou_recupera_parametros():
    rng = np.random.default_rng(4)
    x = np.zeros(20000)
    for t in range(1, len(x)):
        x[t] = x[t - 1] + 5 * (0 - x[t - 1]) / 252 + 0.3 * np.sqrt(1 / 252) * rng.standard_normal()
    theta, mu, sigma, _ = a.ajustar_ou(x)
    assert theta == pytest.approx(5, rel=0.25) and sigma == pytest.approx(0.3, rel=0.05)


def test_diversity_weighted_reduce_gigantes():
    w = a.diversity_weighted(np.array([0.5, 0.3, 0.15, 0.05]))
    assert w.sum() == pytest.approx(1) and w[0] < 0.5 and w[-1] > 0.05


def test_mejora_sharpe_regla():
    assert a.mejora_sharpe(-0.3, 1, -0.8)
    assert not a.mejora_sharpe(0.5, 1, 0.8)


def test_superhedge_con_vol_mayor_no_pierde():
    media, prob_perdida = a.pnl_cobertura(sims=500)
    assert media > 0 and prob_perdida < 0.02
