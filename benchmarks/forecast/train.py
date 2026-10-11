"""Backtest the rating forecast: select a model on development origins, score it on later ones."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold

from benchmarks.forecast.data import Account, load
from benchmarks.forecast.evaluate import mae_difference, summarize
from benchmarks.forecast.instances import Instances, Series, build, weekly_origins
from geostats.config import Settings
from geostats.stats.forecast_features import FEATURES, Floats
from geostats.stats.forecast_model import Model, predict

HORIZONS = (7, 30)
FIRST_ORIGIN = datetime(2026, 7, 15, tzinfo=UTC)
TEST_START = datetime(2026, 9, 9, tzinfo=UTC)
FROZEN_UNTIL = datetime(2026, 10, 12, tzinfo=UTC)
MODES: tuple[Series, ...] = ("moving", "nomove", "nmpz")
RIDGE_ALPHAS = (0.1, 1.0, 10.0, 100.0)
GBR_LOSSES = ("absolute_error", "huber")
GBR_DEPTHS = (2, 3)
GBR_TREES = (100, 300)
GBR_LEARNING_RATE = 0.05
RIDGE_TOLERANCE = 0.01
FOLDS = 5
SEED = 0
ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "src" / "geostats" / "data" / "forecast_model.json"
RESULTS_PATH = ROOT / "benchmarks" / "forecast_results.json"


def _fill(rows: Floats, medians: Floats) -> Floats:
    filled: Floats = np.where(np.isnan(rows), medians, rows)
    return filled


def fit_ridge(rows: Floats, target: Floats, alpha: float) -> Model:
    medians = np.nanmedian(rows, axis=0)
    filled = _fill(rows, medians)
    mean = filled.mean(axis=0)
    scale = filled.std(axis=0)
    scale[scale == 0] = 1.0
    ridge = Ridge(alpha=alpha).fit((filled - mean) / scale, target)
    return {
        "kind": "ridge",
        "medians": medians.tolist(),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "coef": ridge.coef_.tolist(),
        "intercept": float(ridge.intercept_),
    }


def fit_gbr(rows: Floats, target: Floats, loss: str, depth: int) -> GradientBoostingRegressor:
    booster = GradientBoostingRegressor(
        loss=loss,
        max_depth=depth,
        n_estimators=max(GBR_TREES),
        learning_rate=GBR_LEARNING_RATE,
        random_state=SEED,
    )
    return booster.fit(rows, target)


def export_gbr(booster: GradientBoostingRegressor, medians: Floats, trees: int) -> Model:
    return {
        "kind": "gbr",
        "medians": medians.tolist(),
        "init": float(booster.init_.predict(np.zeros((1, medians.size)))[0]),
        "learning_rate": booster.learning_rate,
        "trees": [
            {
                "feature": stage[0].tree_.feature.tolist(),
                "threshold": stage[0].tree_.threshold.tolist(),
                "left": stage[0].tree_.children_left.tolist(),
                "right": stage[0].tree_.children_right.tolist(),
                "value": stage[0].tree_.value[:, 0, 0].tolist(),
            }
            for stage in booster.estimators_[:trees]
        ],
    }


def gbr_name(loss: str, depth: int, trees: int) -> str:
    return f"gbr {loss} depth={depth} trees={trees}"


def ridge_name(alpha: float) -> str:
    return f"ridge alpha={alpha:g}"


def cross_validate(rows: Floats, target: Floats, groups: NDArray[np.str_]) -> dict[str, float]:
    """Mean absolute error of every candidate, pooled over account-grouped folds."""
    errors: dict[str, list[Floats]] = {}
    for train, held in GroupKFold(n_splits=FOLDS).split(rows, target, groups):
        for alpha in RIDGE_ALPHAS:
            model = fit_ridge(rows[train], target[train], alpha)
            errors.setdefault(ridge_name(alpha), []).append(
                np.abs(predict(model, rows[held]) - target[held])
            )
        medians = np.nanmedian(rows[train], axis=0)
        held_rows = _fill(rows[held], medians)
        for loss in GBR_LOSSES:
            for depth in GBR_DEPTHS:
                booster = fit_gbr(_fill(rows[train], medians), target[train], loss, depth)
                for count, staged in enumerate(booster.staged_predict(held_rows), start=1):
                    if count in GBR_TREES:
                        errors.setdefault(gbr_name(loss, depth, count), []).append(
                            np.abs(staged - target[held])
                        )
    return {name: float(np.concatenate(parts).mean()) for name, parts in errors.items()}


def select(scores: dict[str, float]) -> str:
    """Lowest error; the best ridge wins when it is within RIDGE_TOLERANCE of it."""
    best = min(scores, key=lambda name: scores[name])
    ridge = min((n for n in scores if n.startswith("ridge")), key=lambda name: scores[name])
    return ridge if scores[ridge] <= scores[best] * (1 + RIDGE_TOLERANCE) else best


def fit_named(name: str, rows: Floats, target: Floats) -> Model:
    if name.startswith("ridge"):
        return fit_ridge(rows, target, float(name.split("=")[1]))
    _, loss, depth, trees = name.split()
    medians = np.nanmedian(rows, axis=0)
    booster = fit_gbr(_fill(rows, medians), target, loss, int(depth.split("=")[1]))
    return export_gbr(booster, medians, int(trees.split("=")[1]))


def _compare(predicted: Floats, baseline: Floats, part: Instances) -> list[float]:
    return list(mae_difference(predicted, baseline, part.actual, part.accounts))


def score(model: Model, part: Instances) -> dict[str, Any]:
    predicted = predict(model, part.features)
    still = np.zeros(len(part))
    return {
        "forecasts": len(part),
        "accounts": int(np.unique(part.accounts).size),
        "no_change": summarize(still, part.actual),
        "theil_sen": summarize(part.theil_sen, part.actual),
        "model": summarize(predicted, part.actual),
        "model_vs_no_change": _compare(predicted, still, part),
        "model_vs_theil_sen": _compare(predicted, part.theil_sen, part),
        "theil_sen_vs_no_change": _compare(part.theil_sen, still, part),
    }


def run_horizon(accounts: dict[str, Account], horizon: int, origins: list[float]) -> dict[str, Any]:
    start = TEST_START.timestamp()
    overall = build(accounts, "overall", horizon, origins)
    dev = overall.where(overall.target_times <= start)
    test = overall.where(overall.origins >= start)
    scores = cross_validate(dev.features, dev.actual, dev.accounts)
    chosen = select(scores)
    model = fit_named(chosen, dev.features, dev.actual)
    families = {
        family: min((n for n in scores if n.startswith(family)), key=lambda name: scores[name])
        for family in ("ridge", "gbr")
    }
    edges = np.quantile(dev.current, [1 / 3, 2 / 3])
    tier_of = np.digitize(test.current, edges)
    modes = {}
    for series in MODES:
        instances = build(accounts, series, horizon, origins)
        modes[series] = score(model, instances.where(instances.origins >= start))
    return {
        "development": {"forecasts": len(dev), "accounts": int(np.unique(dev.accounts).size)},
        "cross_validation": scores,
        "selected": chosen,
        "test": score(model, test),
        "families": {
            family: summarize(
                predict(fit_named(name, dev.features, dev.actual), test.features), test.actual
            )
            | {"name": name}
            for family, name in families.items()
        },
        "tiers": [
            {
                "from": None if tier == 0 else float(edges[tier - 1]),
                "to": None if tier == len(edges) else float(edges[tier]),
            }
            | score(model, test.where(tier_of == tier))
            for tier in range(len(edges) + 1)
        ],
        "modes": modes,
        "model": model,
    }


def criteria(horizons: dict[str, dict[str, Any]]) -> dict[str, bool]:
    def beats(result: dict[str, Any]) -> bool:
        return bool(result["model_vs_no_change"][2] < 0)

    return {
        "beats_no_change_7d": beats(horizons["7"]["test"]),
        "beats_no_change_30d": beats(horizons["30"]["test"]),
        "no_tier_worse": all(
            tier["model_vs_no_change"][1] <= 0
            for result in horizons.values()
            for tier in result["tiers"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path)
    args = parser.parse_args()

    since = Settings.model_fields["rating_system_cutoff"].default
    accounts = load(args.export, since, FROZEN_UNTIL)
    origins = weekly_origins(FIRST_ORIGIN, FROZEN_UNTIL)
    horizons = {str(h): run_horizon(accounts, h, origins) for h in HORIZONS}
    models = {key: result.pop("model") for key, result in horizons.items()}

    MODEL_PATH.parent.mkdir(exist_ok=True)
    MODEL_PATH.write_text(json.dumps({"features": list(FEATURES), "horizons": models}))
    RESULTS_PATH.write_text(
        json.dumps(
            {
                "since": since.date().isoformat(),
                "until": FROZEN_UNTIL.date().isoformat(),
                "test_start": TEST_START.date().isoformat(),
                "accounts": len(accounts),
                "snapshots": int(sum(a.times.size for a in accounts.values())),
                "horizons": horizons,
                "criteria": criteria(horizons),
            },
            indent=1,
        )
    )
    for key, result in horizons.items():
        test = result["test"]
        print(
            f"{key} days: {result['selected']}, MAE {test['model']['mae']:.1f} "
            f"vs {test['no_change']['mae']:.1f} with no change"
        )


if __name__ == "__main__":
    main()
