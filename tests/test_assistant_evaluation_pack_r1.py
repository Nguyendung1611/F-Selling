"""Go/no-go contracts for the local Assistant Evaluation Pack R1."""
from __future__ import annotations

from assistant_evaluation_r1 import CASES, build_scorecard
from fselling.services import assistant_service


def test_r1_has_a_small_balanced_acceptance_set():
    assert 30 <= len(CASES) <= 50
    assert len({case.question.casefold() for case in CASES}) == len(CASES)
    assert {case.expected_intent for case in CASES if case.expected_intent} == set(
        assistant_service._BANG_XU_LY
    )
    assert {case.trait for case in CASES} >= {
        "accented",
        "unaccented",
        "regional",
        "typo",
        "unclear",
        "unsafe",
    }


def test_r1_scorecard_is_provider_free_and_meets_every_gate():
    report = build_scorecard()

    assert report["version"] == "R1"
    assert report["question_count"] == len(CASES)
    assert report["external_provider_calls"] == 0
    assert report["scores"]["intent_accuracy_pct"] == 100.0
    assert report["scores"]["period_accuracy_pct"] == 100.0
    assert report["scores"]["safe_abstention_pct"] == 100.0
    assert report["scores"]["intent_coverage_pct"] == 100.0
    assert report["failed_cases"] == []
    assert report["go"] is True
    assert all(report["gates"].values())


def test_r1_provider_and_tts_runtime_flags_remain_off():
    report = build_scorecard()

    assert report["runtime"]["gemini_enabled"] is False
    assert report["runtime"]["tts_server_enabled"] is False
