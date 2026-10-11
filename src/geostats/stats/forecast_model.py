from __future__ import annotations

from typing import Any

import numpy as np

from geostats.stats.forecast_features import Floats

Model = dict[str, Any]


def predict(model: Model, rows: Floats) -> Floats:
    """Predicted rating change for each feature row; missing values take the stored medians."""
    medians = np.asarray(model["medians"], dtype=np.float64)
    filled = np.where(np.isnan(rows), medians, rows)
    if model["kind"] == "ridge":
        scaled = (filled - np.asarray(model["mean"])) / np.asarray(model["scale"])
        linear: Floats = scaled @ np.asarray(model["coef"]) + model["intercept"]
        return linear
    total = np.full(filled.shape[0], model["init"], dtype=np.float64)
    every = np.arange(filled.shape[0])
    for tree in model["trees"]:
        feature = np.asarray(tree["feature"])
        threshold = np.asarray(tree["threshold"])
        left = np.asarray(tree["left"])
        right = np.asarray(tree["right"])
        node = np.zeros(filled.shape[0], dtype=np.int64)
        while True:
            inner = left[node] >= 0
            if not inner.any():
                break
            go_left = filled[every, np.maximum(feature[node], 0)] <= threshold[node]
            node = np.where(inner, np.where(go_left, left[node], right[node]), node)
        total += model["learning_rate"] * np.asarray(tree["value"])[node]
    return total
