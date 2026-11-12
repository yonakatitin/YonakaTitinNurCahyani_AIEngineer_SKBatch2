import json
from pathlib import Path

from src.llm import MockLLM
from src.pipeline import grounding_check, run, sanitize
from src.schema import CandidateProfile

ROOT = Path(__file__).resolve().parent.parent
RUBRIC = json.loads((ROOT / "data" / "job_rubric.json").read_text(encoding="utf-8"))


def cv(name):
    return (ROOT / "data" / name).read_text(encoding="utf-8")


class FailingLLM:
    def extract(self, text):
        return {"extraction_notes": ["llm_call_failed"]}


def test_pii_masked_but_dates_kept():
    text, _ = sanitize(cv("sample_cv_01.txt"))
    assert "rina.fiktif@example.com" not in text
    assert "0812-3456-7890" not in text
    assert "2025-06 - 2025-12" in text


def test_injection_flagged():
    _, flags = sanitize(cv("sample_cv_injection.txt"))
    assert "possible_prompt_injection" in flags


def test_injection_does_not_raise_label():
    res = run(cv("sample_cv_injection.txt"), RUBRIC, llm=MockLLM())
    assert res["recommendation"]["label"] == "standard_review"
    assert "possible_prompt_injection" in res["recommendation"]["flags"]


def test_empty_text_needs_clarification():
    res = run("   ", RUBRIC, llm=MockLLM())
    assert res["recommendation"]["label"] == "needs_clarification"
    assert "empty_or_unreadable_text" in res["recommendation"]["flags"]


def test_hallucinated_evidence_is_downgraded():
    res = run(cv("sample_cv_01.txt"), RUBRIC, llm=MockLLM(hallucinate=True))
    fake = next(s for s in res["profile"]["skills"] if s["name"] == "kubernetes")
    assert fake["confidence"] == "low"
    assert any(f.startswith("ungrounded_evidence") for f in res["recommendation"]["flags"])
    assert res["recommendation"]["label"] != "prioritize_review"


def test_short_evidence_not_matched_inside_another_word():
    p = CandidateProfile.model_validate(
        {"skills": [{"name": "git", "evidence": "git", "confidence": "high"}]})
    grounding_check(p, "PT Contoh Digital", [])
    assert p.skills[0].confidence == "low"


def test_inverted_dates_flagged_and_label_held():
    res = run(cv("heldout_cv_02.txt"), RUBRIC, llm=MockLLM())
    assert "inconsistent_dates" in res["recommendation"]["flags"]
    assert res["recommendation"]["label"] != "prioritize_review"


def test_llm_failure_is_explicit_not_a_cv_judgement():
    res = run(cv("sample_cv_01.txt"), RUBRIC, llm=FailingLLM())
    rec = res["recommendation"]
    assert "llm_call_failed" in rec["flags"]
    assert rec["label"] == "needs_clarification"
    assert rec["missing_or_unclear"] == []


def test_matched_criteria_are_traceable():
    res = run(cv("sample_cv_01.txt"), RUBRIC, llm=MockLLM())
    matched = res["recommendation"]["matched_criteria"]
    assert matched
    for m in matched:
        assert m["matched_keyword"] and m["matched_in"] and m["snippet"]
