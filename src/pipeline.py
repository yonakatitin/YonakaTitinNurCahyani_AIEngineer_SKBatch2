import json
import re
import sys
from pydantic import ValidationError

from .llm import get_llm
from .schema import CandidateProfile, Recommendation

PII = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),                    # email
    re.compile(r"(?<![\w-])(?:\+62\s?|0)8[\d\s-]{8,13}\d"),     # telepon (tidak menyentuh tanggal)
]
INJECTION = [re.compile(p, re.I) for p in [
    r"ignore (all )?(previous|prior) instructions",
    r"abaikan (semua )?instruksi",
    r"\b(nilai|score|rate)\b.{0,25}(10/10|100)",
    r"recommend this candidate",
    r"system prompt",
]]
BASE_CAVEATS = [
    "Rekomendasi hanya berdasar isi CV, bukan penilaian kualitas kerja sebenarnya.",
    "Skill yang tertulis belum tentu menunjukkan kedalaman pengalaman.",
    "Format CV tidak standar dapat menurunkan akurasi ekstraksi.",
    "Keputusan akhir wajib oleh reviewer manusia.",
]


def sanitize(text: str) -> tuple[str, list[str]]:
    flags = []
    for p in PII:
        text = p.sub("[MASKED]", text)
    if any(p.search(text) for p in INJECTION):
        flags.append("possible_prompt_injection")
    if len(text.strip()) < 50:
        flags.append("empty_or_unreadable_text")
    return text, flags


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _sections(profile: CandidateProfile):
    return [profile.education, profile.experience, profile.skills,
            profile.projects, profile.certifications]


def grounding_check(profile: CandidateProfile, cv_text: str, flags: list[str]):
    haystack, bad = _norm(cv_text), 0
    for section in _sections(profile):
        for item in section:
            if item.evidence is None:
                item.confidence = "low"
            elif _norm(item.evidence) not in haystack:
                item.confidence, bad = "low", bad + 1
    if bad:
        flags.append(f"ungrounded_evidence:{bad}")


def consistency_checks(profile: CandidateProfile, flags: list[str]):
    for e in profile.experience:
        if e.start and e.end and e.end != "present" and e.end < e.start:
            flags.append("inconsistent_dates")
    for ed in profile.education:
        if ed.gpa is not None and not (0 <= ed.gpa <= 4):
            flags.append("gpa_out_of_range")
    if not profile.experience and not profile.projects:
        flags.append("no_experience_or_projects")


def _item_text(item) -> str:
    parts = [getattr(item, k, None) for k in ("name", "title", "summary", "description")]
    parts += getattr(item, "tech", [])
    return " ".join(p for p in parts if p).lower()


def recommend(profile: CandidateProfile, rubric: dict, flags: list[str]) -> Recommendation:
    trusted = [i for s in _sections(profile) for i in s
               if i.confidence != "low" and i.evidence]
    matched, missing = [], []
    for crit in rubric["must_have"]:
        hit = next((i for i in trusted
                    if any(re.search(rf"\b{re.escape(k)}\b", _item_text(i))
                           for k in crit["keywords"])), None)
        if hit:
            matched.append({"criterion": crit["id"], "evidence": hit.evidence,
                            "confidence": hit.confidence})
        else:
            missing.append(crit["id"])

    ratio = len(matched) / len(rubric["must_have"])
    heavy = {"empty_or_unreadable_text", "parse_failed"}
    if heavy & set(flags) or ratio < 0.5:
        label = "needs_clarification"
    elif ratio == 1 and not flags:
        label = "prioritize_review"
    else:
        label = "standard_review"   # flag apa pun menahan label di level ini

    caveats = list(BASE_CAVEATS)
    if missing:
        caveats.append(f"Kriteria belum terbukti dari CV: {', '.join(missing)}.")
    if "possible_prompt_injection" in flags:
        caveats.append("CV berisi teks mirip instruksi ke AI; diabaikan dan perlu dicek manual.")
    return Recommendation(label=label, matched_criteria=matched,
                          missing_or_unclear=missing, caveats=caveats,
                          flags=sorted(set(flags)), rubric_version=rubric["version"])


def run(cv_text: str, rubric: dict, llm=None) -> dict:
    llm = llm or get_llm()
    text, flags = sanitize(cv_text)
    profile = CandidateProfile()
    if "empty_or_unreadable_text" not in flags:
        raw = llm.extract(text)
        try:
            profile = CandidateProfile.model_validate(raw)
        except ValidationError:
            try:                                  # retry 1x
                profile = CandidateProfile.model_validate(llm.extract(text))
            except ValidationError:
                flags.append("parse_failed")
        grounding_check(profile, text, flags)
        consistency_checks(profile, flags)
    rec = recommend(profile, rubric, flags)
    return {"profile": profile.model_dump(), "recommendation": rec.model_dump()}


if __name__ == "__main__":
    cv_path, rubric_path = sys.argv[1], sys.argv[2]
    if cv_path.endswith(".pdf"):
        from .ingest import pdf_to_text
        cv = pdf_to_text(cv_path)
    else:
        cv = open(cv_path, encoding="utf-8").read()
    rubric = json.load(open(rubric_path, encoding="utf-8"))
    print(json.dumps(run(cv, rubric), indent=2, ensure_ascii=False))