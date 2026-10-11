from typing import Any

from benchmarks.forecast.report import render


def _metrics(mae: float) -> dict[str, float]:
    return {"mae": mae, "rmse": mae * 1.4, "median_ae": mae * 0.7, "direction": 0.61}


def _part(model: float) -> dict[str, Any]:
    return {
        "forecasts": 1200,
        "accounts": 400,
        "no_change": _metrics(50.0) | {"direction": float("nan")},
        "theil_sen": _metrics(55.0),
        "model": _metrics(model),
        "model_vs_no_change": [model - 50.0, model - 51.0, model - 49.0],
        "model_vs_theil_sen": [model - 55.0, model - 56.0, model - 54.0],
        "theil_sen_vs_no_change": [5.0, 4.0, 6.0],
    }


def _horizon(model: float) -> dict[str, Any]:
    return {
        "selected": "ridge alpha=10",
        "cross_validation": {"ridge alpha=10": 44.123, "gbr huber depth=2 trees=100": 44.5},
        "test": _part(model),
        "families": {
            "ridge": _metrics(model) | {"name": "ridge alpha=10"},
            "gbr": _metrics(model + 1) | {"name": "gbr huber depth=2 trees=100"},
        },
        "tiers": [
            {"from": None, "to": 900.0} | _part(model),
            {"from": 900.0, "to": 1200.0} | _part(model),
            {"from": 1200.0, "to": None} | _part(model),
        ],
        "modes": {mode: _part(model) for mode in ("moving", "nomove", "nmpz")},
    }


RESULTS: dict[str, Any] = {
    "since": "2026-07-01",
    "until": "2026-10-12",
    "test_start": "2026-09-09",
    "accounts": 5000,
    "snapshots": 300000,
    "horizons": {"7": _horizon(46.0), "30": _horizon(68.0)},
    "criteria": {"beats_no_change_7d": True, "beats_no_change_30d": False, "no_tier_worse": True},
}


def test_report_states_the_commit_and_the_data() -> None:
    text = render(RESULTS, "abc1234")
    assert "at `abc1234`" in text
    assert "300000 snapshots of 5000 accounts, 2026-07-01 to 2026-10-12" in text


def test_report_shows_each_forecast_with_its_interval() -> None:
    text = render(RESULTS, "abc1234")
    assert "| No change | 50.0 | 70.0 | 35.0 | — |" in text
    assert "| **Selected model** | 46.0 | 64.4 | 32.2 | 61% |" in text
    assert "| Selected model − no change | -4.0 [-5.0, -3.0] |" in text
    assert "| Theil–Sen trend − no change | +5.0 [+4.0, +6.0] |" in text


def test_report_marks_criteria_and_keeps_the_blind_one_pending() -> None:
    text = render(RESULTS, "abc1234")
    assert "1. 7 days: MAE below no change, interval excludes zero: **pass**" in text
    assert "2. 30 days: MAE below no change, interval excludes zero: **fail**" in text
    assert "4. 7 days on forecasts made after 2026-10-12: **pending**" in text
    assert "one exploratory look at the test period" in text


def test_report_has_tiers_modes_and_candidates() -> None:
    text = render(RESULTS, "abc1234")
    assert "| below 900 | -4.0 [-5.0, -3.0] | +18.0 [+17.0, +19.0] |" in text
    assert "| 1200 and above |" in text
    assert "| NMPZ | 50.0 / 55.0 / 46.0, -4.0 [-5.0, -3.0] |" in text
    assert "| `ridge alpha=10` | 44.12 | 44.12 |" in text
