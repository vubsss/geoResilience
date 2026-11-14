"""Marginal event passability: no length-dependent probabilities."""

import numpy as np
from scipy.special import ndtr


def fragility(depth, threshold=0.3, dispersion=0.35):
    values = np.asarray(depth, dtype=float)
    if np.any(~np.isfinite(values)) or np.any(values < 0):
        raise ValueError("depth must be finite and nonnegative")
    if (
        not np.isfinite(threshold)
        or threshold <= 0
        or not np.isfinite(dispersion)
        or dispersion <= 0
    ):
        raise ValueError("threshold and dispersion must be finite and positive")
    with np.errstate(divide="ignore"):
        return ndtr(np.log(values / threshold) / dispersion)


def closure_probability(
    max_depth, coverage, uniform=0.01, threshold=0.3, dispersion=0.35
):
    if (
        not np.isfinite(uniform)
        or not 0 <= uniform <= 1
        or not np.isfinite(coverage)
        or not 0 <= coverage <= 1
    ):
        raise ValueError("probability and coverage must be in [0,1]")
    if max_depth is None or coverage == 0:
        return float(uniform), "uniform_default"
    q = float(fragility(max_depth, threshold, dispersion))
    if coverage < 1 - 1e-9:
        return float(q + (1 - q) * uniform), "hybrid_uniform"
    return q, "depth_fragility"
