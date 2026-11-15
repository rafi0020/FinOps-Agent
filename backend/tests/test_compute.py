"""Deterministic calculations, checked against numbers worked out by hand."""

import pytest

from app.finance.charts import build_chart
from app.finance.compute import ComputeError, run_compute


def tables(**named):
    return lambda handle: named.get(handle)


QUARTERS = {"columns": ["quarter", "revenue"], "rows": [["2026-Q1", 200.0], ["2026-Q2", 250.0], ["2026-Q3", 225.0]]}


def test_growth_between_periods():
    r = run_compute("growth", {"handle": "t", "value": "revenue", "order_by": "quarter"}, tables(t=QUARTERS))
    assert [row["change"] for row in r.table] == [None, 50.0, -25.0]
    assert [row["change_pct"] for row in r.table] == [None, 0.25, -0.1]
    assert r.values == {"first": 200.0, "last": 225.0, "total_change": 25.0, "total_change_pct": 0.125}


def test_growth_per_group_and_unsorted_input():
    t = {
        "columns": ["region", "q", "m"],
        "rows": [["W", "Q3", 0.2], ["E", "Q2", 0.3], ["W", "Q2", 0.31], ["E", "Q3", 0.27]],
    }
    r = run_compute("growth", {"handle": "t", "value": "m", "order_by": "q", "group_by": "region"}, tables(t=t))
    west_q3 = next(row for row in r.table if row["region"] == "W" and row["q"] == "Q3")
    assert west_q3["change"] == pytest.approx(-0.11) and west_q3["previous"] == 0.31


def test_growth_from_zero_and_null_is_noted_not_raised():
    t = {"columns": ["p", "v"], "rows": [["1", 0], ["2", 10], ["3", None], ["4", 5]]}
    r = run_compute("growth", {"handle": "t", "value": "v", "order_by": "p"}, tables(t=t))
    assert r.table[1]["change"] == 10.0 and r.table[1]["change_pct"] is None
    assert r.table[2]["change"] is None and r.table[3]["change"] is None
    assert any("zero" in n for n in r.notes) and any("missing" in n for n in r.notes)


def test_share_of_total():
    t = {"columns": ["region", "rev"], "rows": [["N", 30], ["S", 20], ["E", 50], ["W", None]]}
    r = run_compute("share", {"handle": "t", "value": "rev", "label": "region"}, tables(t=t))
    assert r.values == {"total": 100.0}
    assert {row["region"]: row["share"] for row in r.table} == {"N": 0.3, "S": 0.2, "E": 0.5}
    assert "W" in r.notes[0]


def test_margin_from_cost_and_from_profit():
    t = {
        "columns": ["region", "rev", "cogs", "gp"],
        "rows": [["N", 100, 70, 30], ["S", 300, 180, 120], ["N", 100, 60, 40]],
    }
    by_cost = run_compute(
        "margin", {"handle": "t", "revenue": "rev", "cost": "cogs", "group_by": ["region"]}, tables(t=t)
    )
    assert {row["region"]: row["margin"] for row in by_cost.table} == {"N": 0.35, "S": 0.4}
    assert by_cost.values == {"revenue": 500.0, "profit": 190.0, "margin": 0.38}
    by_profit = run_compute("margin", {"handle": "t", "revenue": "rev", "profit": "gp"}, tables(t=t))
    assert by_profit.values["margin"] == 0.38


def test_margin_with_zero_revenue_gives_none_and_a_note():
    t = {"columns": ["rev", "cogs"], "rows": [[0, 0]]}
    r = run_compute("margin", {"handle": "t", "revenue": "rev", "cost": "cogs"}, tables(t=t))
    assert r.values["margin"] is None and "undefined" in r.notes[0]


def test_variance_decomposition_matches_a_worked_example():
    # Base: A 10 units @ 10, B 10 units @ 20  -> revenue 300, average price 15
    # Compare: A 10 units @ 11, B 20 units @ 20 -> revenue 510
    # volume = (30 - 20) * 15 = 150; price = (11 - 10) * 10 = 10
    # mix = (10/30 - 10/20) * 30 * 10 + (20/30 - 10/20) * 30 * 20 = -50 + 100 = 50
    t = {
        "columns": ["product", "quarter", "units", "revenue"],
        "rows": [["A", "Q2", 10, 100], ["B", "Q2", 10, 200], ["A", "Q3", 10, 110], ["B", "Q3", 20, 400]],
    }
    args = {"handle": "t", "item": "product", "period": "quarter", "quantity": "units", "value": "revenue",
            "base_period": "Q2", "compare_period": "Q3"}  # fmt: skip
    v = run_compute("variance_decomposition", args, tables(t=t)).values
    assert (v["volume_effect"], v["price_effect"], v["mix_effect"]) == (150.0, 10.0, 50.0)
    assert v["total_change"] == 210.0
    assert v["price_effect"] + v["volume_effect"] + v["mix_effect"] == pytest.approx(v["total_change"], abs=0.01)


def test_variance_decomposition_still_adds_up_with_new_and_dropped_items():
    t = {
        "columns": ["p", "q", "u", "r"],
        "rows": [["A", "1", 5, 50], ["B", "1", 7, 91], ["B", "2", 9, 126], ["C", "2", 4, 100], ["D", "9", 1, 1]],
    }
    args = {
        "handle": "t",
        "item": "p",
        "period": "q",
        "quantity": "u",
        "value": "r",
        "base_period": "1",
        "compare_period": "2",
    }
    v = run_compute("variance_decomposition", args, tables(t=t)).values
    assert v["total_change"] == 85.0
    assert v["price_effect"] + v["volume_effect"] + v["mix_effect"] == pytest.approx(85.0, abs=0.01)


def test_variance_decomposition_with_a_period_that_has_no_rows():
    args = {"handle": "t", "item": "quarter", "period": "quarter", "quantity": "revenue", "value": "revenue",
            "base_period": "2026-Q1", "compare_period": "2031-Q1"}  # fmt: skip
    with pytest.raises(ComputeError) as info:
        run_compute("variance_decomposition", args, tables(t=QUARTERS))
    assert info.value.code == "no_data" and "2031-Q1" in info.value.message


def test_zscore_flags_the_outlier():
    t = {"columns": ["m", "v"], "rows": [[f"m{i}", 100] for i in range(9)] + [["spike", 190]]}
    r = run_compute("zscore_anomalies", {"handle": "t", "value": "v", "label": "m"}, tables(t=t))
    assert [row["m"] for row in r.table] == ["spike"] and r.table[0]["z"] == pytest.approx(2.846, abs=0.001)
    assert r.values["mean"] == 109.0
    flat = {"columns": ["v"], "rows": [[5], [5], [5]]}
    assert run_compute("zscore_anomalies", {"handle": "t", "value": "v"}, tables(t=flat)).table == []


def test_seasonal_forecast_repeats_the_season_scaled_by_growth():
    year1, year2 = [10, 20, 30, 40], [11, 22, 33, 44]  # +10% year on year
    t = {"columns": ["i", "v"], "rows": [[f"{i:02d}", v] for i, v in enumerate(year1 + year2)]}
    r = run_compute(
        "seasonal_forecast",
        {"handle": "t", "value": "v", "order_by": "i", "periods": 2, "season_length": 4},
        tables(t=t),
    )
    assert r.values == {"yoy_growth": 0.1}
    assert [row["forecast"] for row in r.table] == [12.1, 24.2]


def test_seasonal_forecast_with_short_history_falls_back_and_says_so():
    r = run_compute(
        "seasonal_forecast",
        {"handle": "t", "value": "revenue", "order_by": "quarter", "periods": 1},
        tables(t=QUARTERS),
    )
    assert r.table == [{"step": 1, "forecast": 237.5}] and "Fewer than" in r.notes[0]


@pytest.mark.parametrize(
    ("op", "args", "code"),
    [
        ("growth", {"handle": "empty", "value": "revenue", "order_by": "quarter"}, "no_data"),
        ("share", {"handle": "empty", "value": "revenue", "label": "quarter"}, "no_data"),
        ("growth", {"handle": "t", "value": "profit", "order_by": "quarter"}, "bad_column"),
        ("growth", {"handle": "nope", "value": "revenue", "order_by": "quarter"}, "bad_args"),
        ("growth", {"handle": "t", "value": "revenue"}, "bad_args"),
        ("margin", {"handle": "t", "revenue": "revenue"}, "bad_args"),
        ("integrate", {"handle": "t"}, "bad_args"),
        ("zscore_anomalies", {"handle": "t", "value": "revenue", "threshold": "high"}, "bad_args"),
        (
            "seasonal_forecast",
            {"handle": "t", "value": "revenue", "order_by": "quarter", "periods": "many"},
            "bad_args",
        ),
    ],
)
def test_bad_input_is_reported_with_a_code(op, args, code):
    empty = {"columns": ["quarter", "revenue"], "rows": []}
    with pytest.raises(ComputeError) as info:
        run_compute(op, args, tables(t=QUARTERS, empty=empty))
    assert info.value.code == code


def test_no_result_ever_contains_nan():
    t = {"columns": ["p", "v"], "rows": [["1", "NaN"], ["2", float("inf")], ["3", 4]]}
    r = run_compute("growth", {"handle": "t", "value": "v", "order_by": "p"}, tables(t=t))
    assert [row["v"] for row in r.table] == [None, None, 4.0]


def test_chart_spec_is_built_from_the_stored_rows():
    spec = build_chart("line", "t", "quarter", ["revenue"], "Revenue by quarter", tables(t=QUARTERS))
    assert spec["labels"] == ["2026-Q1", "2026-Q2", "2026-Q3"]
    assert spec["series"] == [{"name": "revenue", "data": [200.0, 250.0, 225.0]}]
    with pytest.raises(ComputeError) as info:
        build_chart("line", "t", "quarter", ["profit"], "x", tables(t=QUARTERS))
    assert info.value.code == "bad_column"
    with pytest.raises(ComputeError):
        build_chart("pie", "t", "quarter", ["revenue"], "x", tables(t=QUARTERS))


def test_growth_orders_numeric_periods_numerically():
    """Found in review: months 1, 2, 9, 10, 11 were sorted as text (1, 10, 11, 2, 9)."""
    t = {"columns": ["month", "v"], "rows": [[10, 40], [1, 10], [9, 30], [2, 20], [11, 50]]}
    r = run_compute("growth", {"handle": "t", "value": "v", "order_by": "month"}, tables(t=t))
    assert [row["month"] for row in r.table] == [1, 2, 9, 10, 11] and r.values["total_change"] == 40.0


def test_margin_with_a_missing_cost_is_unknown_not_one_hundred_percent():
    t = {"columns": ["region", "rev", "cogs"], "rows": [["N", 100, None], ["S", 200, 150]]}
    r = run_compute("margin", {"handle": "t", "revenue": "rev", "cost": "cogs", "group_by": "region"}, tables(t=t))
    by_region = {row["region"]: row["margin"] for row in r.table}
    assert by_region == {"N": None, "S": 0.25} and r.values["margin"] is None
    assert any("missing" in n for n in r.notes)


def test_forecast_does_not_invent_flat_growth_when_a_season_is_zero():
    t = {"columns": ["i", "v"], "rows": [[i, v] for i, v in enumerate([0, 0, 0, 0, 5, 6, 7, 8])]}
    r = run_compute(
        "seasonal_forecast",
        {"handle": "t", "value": "v", "order_by": "i", "periods": 1, "season_length": 4},
        tables(t=t),
    )
    assert r.values.get("yoy_growth") is None and any("undefined" in n for n in r.notes)
