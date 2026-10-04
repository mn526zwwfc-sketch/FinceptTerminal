"""
Statistical tools from the academic-quant literature, stdlib only.

Each function implements a formula quoted in the research report
"La academia quant desinfla sus propias estrategias" (summarized in data/evidence_kb.json)
and is checked in tests/test_quant_evidence.py against the worked examples
that the report cites (Bailey & Lopez de Prado DSR = 0.90, Harvey & Liu
haircut 0.75 -> ~0.32, MinBTL 45 trials / 5 years, Bodie put costs, half Kelly
keeps 75% of growth, Campbell-Thompson R2/S2).

The same formulas are ported to JavaScript in web/engine.js; the parity test
runs both on shared vectors so the artifact and the CLI never disagree.
"""

from __future__ import annotations

import math
from statistics import NormalDist

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329


def norm_cdf(x: float) -> float:
    return _N.cdf(x)


def norm_ppf(p: float) -> float:
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    return _N.inv_cdf(p)


# ── Backtest overfitting (Bailey, Borwein, Lopez de Prado & Zhu 2014) ─────────

def expected_max_sharpe_z(n_trials: int) -> float:
    """E[max_N] of N iid standard normals, in standard deviations.

    E[max_N] ~ (1 - g) * Z^-1[1 - 1/N] + g * Z^-1[1 - 1/(N e)]
    """
    n = int(n_trials)
    if n <= 1:
        return 0.0
    return ((1.0 - EULER_GAMMA) * norm_ppf(1.0 - 1.0 / n)
            + EULER_GAMMA * norm_ppf(1.0 - 1.0 / (n * math.e)))


def min_backtest_length(n_trials: int, target_sharpe: float) -> float:
    """Minimum backtest length in years so that an annual Sharpe of
    `target_sharpe` is not expected from the best of N skill-less trials.

    MinBTL ~ (E[max_N] / SR_target)^2
    """
    if target_sharpe <= 0:
        return math.inf
    return (expected_max_sharpe_z(n_trials) / target_sharpe) ** 2


def max_trials_for_length(years: float, target_sharpe: float) -> int:
    """Largest N whose MinBTL does not exceed `years` (inverse of MinBTL)."""
    if years <= 0 or target_sharpe <= 0:
        return 1
    lo, hi = 1, 2
    while min_backtest_length(hi, target_sharpe) <= years and hi < 10**9:
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if min_backtest_length(mid, target_sharpe) <= years:
            lo = mid
        else:
            hi = mid
    return lo


def probabilistic_sharpe_ratio(sr: float, sr_benchmark: float, n_obs: int,
                               skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """PSR(SR*) with per-period (non-annualized) Sharpe ratios.

    PSR = Z[(SR - SR*) sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1)/4 SR^2)]
    `kurtosis` is the raw (non-excess) kurtosis: 3 for a normal distribution.
    """
    if n_obs < 2:
        return float('nan')
    var_term = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    if var_term <= 0:
        return float('nan')
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / math.sqrt(var_term)
    return norm_cdf(z)


def deflated_sharpe_ratio(sr_annual: float, n_trials: int, years: float,
                          periods_per_year: int = 252,
                          var_trials_sr_annual: float | None = None,
                          skew: float = 0.0, kurtosis: float = 3.0) -> dict:
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado, JPM 2014).

    SR0 = sqrt(V[SR_n]) * E[max_N]   (expected best Sharpe of N skill-less trials)
    DSR = PSR(SR0)

    `var_trials_sr_annual` is the cross-trial variance of the annualized Sharpe
    ratios. If unknown, the variance that pure sampling noise would produce
    when no trial has skill (~ 1 / years) is used.
    """
    n_obs = int(round(years * periods_per_year))
    if var_trials_sr_annual is None:
        var_trials_sr_annual = 1.0 / years if years > 0 else 1.0
    sr0_annual = math.sqrt(max(var_trials_sr_annual, 0.0)) * expected_max_sharpe_z(n_trials)
    scale = math.sqrt(periods_per_year)
    dsr = probabilistic_sharpe_ratio(sr_annual / scale, sr0_annual / scale,
                                     n_obs, skew, kurtosis)
    return {
        'dsr': dsr,
        'sr0_annual': sr0_annual,
        'sr0_per_period': sr0_annual / scale,
        'n_obs': n_obs,
        'var_trials_sr_annual': var_trials_sr_annual,
        'expected_max_z': expected_max_sharpe_z(n_trials),
    }


# ── Multiple testing (Harvey, Liu & Zhu 2016; Harvey & Liu 2015) ──────────────

def sharpe_to_t(sr_annual: float, years: float) -> float:
    """t = SR x sqrt(T), with T in years for an annualized Sharpe."""
    return sr_annual * math.sqrt(max(years, 0.0))


def t_to_pvalue(t: float) -> float:
    """Two-sided p-value of a t statistic (normal approximation)."""
    return 2.0 * (1.0 - norm_cdf(abs(t)))


def pvalue_to_t(p: float) -> float:
    return norm_ppf(1.0 - min(max(p, 0.0), 1.0) / 2.0)


def adjust_pvalue(p: float, n_tests: int, method: str = 'bonferroni') -> float:
    """Adjust the p-value of the BEST of `n_tests` strategies.

    bonferroni: min(M p, 1). For the top-ranked test Holm equals Bonferroni.
    sidak:      1 - (1 - p)^M.
    """
    m = max(int(n_tests), 1)
    if method == 'sidak':
        return 1.0 - (1.0 - p) ** m
    return min(m * p, 1.0)


def haircut_sharpe(sr_annual: float, years: float, n_tests: int,
                   method: str = 'bonferroni') -> dict:
    """Harvey & Liu (2015) haircut Sharpe ratio.

    Sharpe -> t -> p -> multiple-testing adjusted p -> t -> Sharpe.
    """
    t = sharpe_to_t(sr_annual, years)
    p = t_to_pvalue(t)
    p_adj = adjust_pvalue(p, n_tests, method)
    t_adj = pvalue_to_t(p_adj) if p_adj < 1.0 else 0.0
    sr_adj = t_adj / math.sqrt(years) if years > 0 else 0.0
    if sr_annual < 0:
        sr_adj = -sr_adj
    haircut = 1.0 - sr_adj / sr_annual if sr_annual != 0 else 0.0
    return {
        't_stat': t,
        'p_value': p,
        'p_adjusted': p_adj,
        't_adjusted': t_adj,
        'sharpe_haircut': sr_adj,
        'haircut_pct': haircut,
        'passes_t3': abs(t) >= 3.0,
        'method': method,
    }


def bonferroni_t_threshold(n_tests: int, alpha: float = 0.05) -> float:
    """t threshold that the best of M tests must clear (two-sided)."""
    return pvalue_to_t(alpha / max(int(n_tests), 1))


# ── Trading costs (Novy-Marx & Velikov 2016; Chen & Velikov 2023) ─────────────

def monthly_cost_bps(turnover_monthly: float, roundtrip_cost_bps: float,
                     long_short: bool = False) -> float:
    """Monthly cost drag in bps.

    turnover_monthly: fraction of each leg replaced per month (0.5 = 50%).
    roundtrip_cost_bps: cost of selling and buying back one unit (spread +
    commissions + impact). A long-short portfolio trades two legs.
    """
    legs = 2.0 if long_short else 1.0
    return max(turnover_monthly, 0.0) * max(roundtrip_cost_bps, 0.0) * legs


def breakeven_roundtrip_cost_bps(gross_monthly_bps: float, turnover_monthly: float,
                                 long_short: bool = False) -> float:
    """Round-trip cost that would wipe out the gross monthly edge."""
    legs = 2.0 if long_short else 1.0
    if turnover_monthly <= 0:
        return math.inf
    return gross_monthly_bps / (turnover_monthly * legs)


# ── Long horizon risk (Bodie 1995/2020) ───────────────────────────────────────

def bodie_shortfall_put_cost(sigma_annual: float, years: float) -> float:
    """Cost, as a fraction of the investment, of insuring that stocks earn at
    least the risk-free rate over `years`:  P/S = 2 N(sigma sqrt(T) / 2) - 1.
    """
    return 2.0 * norm_cdf(sigma_annual * math.sqrt(max(years, 0.0)) / 2.0) - 1.0


def prob_real_loss_lognormal(mu_real_annual: float, sigma_annual: float,
                             years: float) -> float:
    """P(cumulative real return < 0) under iid lognormal returns with arithmetic
    mean `mu_real_annual`. Model-based; the report's empirical figure for 39
    developed markets at 30 years is 12% (Anarkulova, Cederburg & O'Doherty).
    """
    if years <= 0 or sigma_annual <= 0:
        return float('nan')
    m = math.log(1.0 + mu_real_annual) - 0.5 * math.log(
        1.0 + (sigma_annual / (1.0 + mu_real_annual)) ** 2)
    s = math.sqrt(math.log(1.0 + (sigma_annual / (1.0 + mu_real_annual)) ** 2))
    return norm_cdf(-(m * years) / (s * math.sqrt(years)))


# ── Bet sizing (Kelly; MacLean, Thorp & Ziemba 2010) ──────────────────────────

def kelly_fraction(mu: float, r: float, sigma: float, gamma: float = 1.0) -> float:
    """Merton fraction (mu - r) / (gamma sigma^2); Kelly is gamma = 1."""
    if sigma <= 0:
        return math.inf
    return (mu - r) / (gamma * sigma * sigma)


def growth_rate(f: float, mu: float, r: float, sigma: float) -> float:
    """Continuous-time log growth g(f) = r + f (mu - r) - f^2 sigma^2 / 2."""
    return r + f * (mu - r) - 0.5 * f * f * sigma * sigma


def kelly_growth_share(kelly_multiple: float) -> float:
    """Share of the maximal excess growth kept when betting x times Kelly:
    2x - x^2 (half Kelly keeps 75%, double Kelly keeps 0%)."""
    x = kelly_multiple
    return 2.0 * x - x * x


# ── Market timing (Campbell & Thompson 2008) ──────────────────────────────────

def campbell_thompson_gain(r2_os: float, sharpe_sq: float) -> float:
    """Proportional increase in expected portfolio return for a mean-variance
    investor who uses a predictor with out-of-sample R^2 (same frequency as
    the squared Sharpe ratio):  ~ R^2 / S^2."""
    if sharpe_sq <= 0:
        return math.inf
    return r2_os / sharpe_sq


# ── Decay of published alphas ─────────────────────────────────────────────────

MCLEAN_PONTIFF_OOS_DECAY = 0.26          # -26% out of sample
MCLEAN_PONTIFF_POST_PUB_DECAY = 0.58     # -58% after publication
JKP_OOS_SLOPE = (0.25, 0.43)             # Jensen, Kelly & Pedersen shrinkage slope


def decayed_alpha(gross_alpha: float, published: bool, out_of_sample: bool) -> float:
    """Expected alpha after McLean-Pontiff decay. If the signal is published,
    the post-publication decay (58%) applies; if it is merely untested out of
    sample, the 26% out-of-sample decay applies."""
    if published:
        return gross_alpha * (1.0 - MCLEAN_PONTIFF_POST_PUB_DECAY)
    if not out_of_sample:
        return gross_alpha * (1.0 - MCLEAN_PONTIFF_OOS_DECAY)
    return gross_alpha
