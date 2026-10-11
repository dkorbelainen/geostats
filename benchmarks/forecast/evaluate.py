from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from geostats.stats.forecast_features import Floats

RESAMPLES = 2000


def summarize(predicted: Floats, actual: Floats) -> dict[str, float]:
    error = predicted - actual
    return {
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt((error**2).mean())),
        "median_ae": float(np.median(np.abs(error))),
        "direction": direction_accuracy(predicted, actual),
    }


def direction_accuracy(predicted: Floats, actual: Floats) -> float:
    """Share of correct signs where both the predicted and the actual change are non-zero."""
    moved = (predicted != 0) & (actual != 0)
    if not moved.any():
        return float("nan")
    return float((np.sign(predicted[moved]) == np.sign(actual[moved])).mean())


def mae_difference(
    predicted: Floats,
    baseline: Floats,
    actual: Floats,
    groups: NDArray[np.str_],
    seed: int = 0,
) -> tuple[float, float, float]:
    """MAE(predicted) - MAE(baseline) with a 95% cluster-bootstrap interval over groups."""
    gain = np.abs(predicted - actual) - np.abs(baseline - actual)
    _, index = np.unique(groups, return_inverse=True)
    sums = np.bincount(index, weights=gain)
    counts = np.bincount(index).astype(np.float64)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, sums.size, size=(RESAMPLES, sums.size))
    resampled = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    low, high = np.percentile(resampled, [2.5, 97.5])
    return float(gain.mean()), float(low), float(high)
