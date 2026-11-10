"""Evaluasi sederhana. Jalankan dari root repo:
python -m eval.run_eval --mode mock
python -m eval.run_eval --mode real --repeats 1
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from statistics import mean

from src.llm import MockLLM, get_llm
from src.pipeline import run, sanitize

ROOT = Path(__file__).resolve().parent.parent
DATA, GOLD, OUT = ROOT / "data", ROOT / "data" / "golden", ROOT / "outputs"


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def grounded_rate(result: dict, masked_text: str) -> float:
    """Porsi evidence yang benar-benar ada di teks CV."""
    hay, total, ok = norm(masked_text), 0, 0
    for section in ("education", "experience", "skills", "projects", "certifications"):
        for item in result["profile"][section]:
            if item.get("evidence"):
                total += 1
                ok += re.search(r"(?<!\w)" + re.escape(norm(item["evidence"])) + r"(?!\w)", hay) is not None
    return ok / total if total else 1.0


def prf(pred: set, gold: set):
    tp = len(pred & gold)
    p = tp / len(pred) if pred else (1.0 if not gold else 0.0)
    r = tp / len(gold) if gold else 1.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def hallucination_test(rubric: dict):
    """Suntik skill palsu; sistem harus menandainya dan tidak menaikkan label."""
    cv = (DATA / "sample_cv_01.txt").read_text(encoding="utf-8")
    res = run(cv, rubric, llm=MockLLM(hallucinate=True))
    flags = {f.split(":")[0] for f in res["recommendation"]["flags"]}
    fake = next((s for s in res["profile"]["skills"] if s["name"] == "kubernetes"), None)
    caught = "ungrounded_evidence" in flags and fake is not None and fake["confidence"] == "low"
    not_promoted = res["recommendation"]["label"] != "prioritize_review"
    return caught, not_promoted


def evaluate(repeats: int):
    rubric = json.loads((DATA / "job_rubric.json").read_text(encoding="utf-8"))
    rows = []
    for cv_path in sorted(DATA.glob("sample_cv_*.txt")):
        gold_path = GOLD / f"{cv_path.stem}.json"
        if not gold_path.exists():
            continue
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        cv = cv_path.read_text(encoding="utf-8")
        masked, _ = sanitize(cv)

        results = [run(cv, rubric, llm=get_llm()) for _ in range(repeats)]
        if any("llm_call_failed" in r["recommendation"]["flags"] for r in results):
            rows.append({"cv": cv_path.stem, "failed": True})
            continue
        res = results[0]
        rec, prof = res["recommendation"], res["profile"]

        pred_skills = {s["name"].lower() for s in prof["skills"]}
        gold_skills = {s.lower() for s in gold["skills"]}
        _, _, f1 = prf(pred_skills, gold_skills)
        edu = prof["education"]
        gpa = edu[0]["gpa"] if edu else None
        gpa_ok = (gpa is None and gold["gpa"] is None) or (
            gpa is not None and gold["gpa"] is not None and abs(gpa - gold["gpa"]) < 0.01)
        base_flags = {f.split(":")[0] for f in rec["flags"]}

        rows.append({
            "cv": cv_path.stem,
            "expected": gold["expected_label"],
            "actual": rec["label"],
            "label_ok": rec["label"] == gold["expected_label"],
            "skill_f1": f1,
            "exp_ok": len(prof["experience"]) == gold["n_experience"],
            "gpa_ok": gpa_ok,
            "flags_ok": set(gold["must_flags"]) <= base_flags
                        and not (set(gold["forbidden_flags"]) & base_flags),
            "grounded": grounded_rate(res, masked),
            "consistent": len({r["recommendation"]["label"] for r in results}) == 1,
            "missing": sorted(gold_skills - pred_skills),
            "extra": sorted(pred_skills - gold_skills),
        })
    return rows, rubric


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["mock", "real"], default="mock")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    os.environ["LLM_MODE"] = args.mode

    rows, rubric = evaluate(args.repeats)
    failed = [r["cv"] for r in rows if r.get("failed")]
    rows = [r for r in rows if not r.get("failed")]
    if not rows:
        print("Semua panggilan LLM gagal; tidak ada laporan.", file=sys.stderr)
        return
    caught, not_promoted = hallucination_test(rubric)

    tick = lambda b: "ok" if b else "FAIL"
    model = os.getenv("LLM_MODEL", "-") if args.mode == "real" else "mock"
    lines = [f"# Eval report (mode={args.mode}, model={model}, repeats={args.repeats}, n={len(rows)})", "",
             "| CV | label exp/act | skill F1 | exp | gpa | flags | grounded | consistent |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['cv']} | {r['expected']} / {r['actual']} ({tick(r['label_ok'])}) "
                     f"| {r['skill_f1']:.2f} | {tick(r['exp_ok'])} | {tick(r['gpa_ok'])} "
                     f"| {tick(r['flags_ok'])} | {r['grounded']:.2f} | {tick(r['consistent'])} |")
    lines += ["", "## Summary",
              f"- Label accuracy: {mean(r['label_ok'] for r in rows):.2f}",
              f"- Mean skill F1: {mean(r['skill_f1'] for r in rows):.2f}",
              f"- Experience count accuracy: {mean(r['exp_ok'] for r in rows):.2f}",
              f"- GPA accuracy: {mean(r['gpa_ok'] for r in rows):.2f}",
              f"- Flag checks passed: {mean(r['flags_ok'] for r in rows):.2f}",
              f"- Mean evidence grounding rate: {mean(r['grounded'] for r in rows):.2f}",
              f"- Label consistency across runs: {mean(r['consistent'] for r in rows):.2f}",
              f"- Injected fake skill caught: {tick(caught)}",
              f"- Fake skill did not raise label to prioritize: {tick(not_promoted)}",
              "", "Caveat: golden set kecil (n=4); angka bukan estimasi statistik."]
    lines += ["", "## Skill diffs (missing = ada di golden tapi tidak terekstrak; extra = terekstrak tapi tidak ada di golden)"]
    for r in rows:
        lines.append(f"- {r['cv']}: missing={r['missing']} extra={r['extra']}")
    report = "\n".join(lines)
    print(report)
    OUT.mkdir(exist_ok=True)
    if failed:
        print(f"\nPERINGATAN: LLM gagal untuk {failed}; laporan TIDAK disimpan. Jalankan ulang nanti.", file=sys.stderr)
    else:
        (OUT / f"eval_report_{args.mode}.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
