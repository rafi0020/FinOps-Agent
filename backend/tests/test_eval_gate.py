"""Regression gate: a recorded evaluation result must not fall below the baseline."""

import json
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[1] / "eval"
BASELINE = json.loads((EVAL / "baseline.json").read_text())["test"]
RESULTS = [json.loads(p.read_text()) for p in sorted((EVAL / "results").glob("test-*.json"))]


def test_a_held_out_result_has_been_recorded():
    assert RESULTS, "run: python -m eval.run_eval --split test --model <model>"


@pytest.mark.parametrize("result", RESULTS, ids=[r["name"] for r in RESULTS])
def test_recorded_result_is_within_tolerance_of_the_baseline(result):
    for metric, floor in BASELINE.items():
        assert result["metrics"][metric] >= floor - 0.05, f"{result['name']}: {metric} fell below the baseline"


def test_question_sets_do_not_overlap_and_carry_reference_answers():
    dev = json.loads((EVAL / "questions_dev.json").read_text())
    test = json.loads((EVAL / "questions_test.json").read_text())
    assert len(dev) == 40 and len(test) == 20
    assert not {q["question"] for q in dev} & {q["question"] for q in test}
    for q in dev + test:
        assert "expected" in q or "must" in q or "behaviour" in q
        assert ("reference_sql" in q) == ("expected" in q)  # every expected value was computed, none typed
