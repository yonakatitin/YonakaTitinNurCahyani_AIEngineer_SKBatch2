# Eval report (set=heldout, mode=real, model=gemini-3.1-flash-lite, prompt=v1, repeats=2, n=2)

| CV | label exp/act | skill F1 | exp | gpa | flags | grounded | consistent |
|---|---|---|---|---|---|---|---|
| heldout_cv_01 | standard_review / needs_clarification (FAIL) | 0.00 | FAIL | FAIL | ok | 1.00 | ok |
| heldout_cv_02 | standard_review / standard_review (ok) | 0.91 | ok | ok | ok | 1.00 | ok |

## Summary
- Label accuracy: 0.50
- Mean skill F1: 0.45
- Experience count accuracy: 0.50
- GPA accuracy: 0.50
- Flag checks passed: 1.00
- Mean evidence grounding rate: 1.00
- Label consistency across runs: 1.00
- Injected fake skill caught: ok
- Fake skill did not raise label to prioritize: ok

Caveat: golden set kecil (n=4); angka bukan estimasi statistik.

## Skill diffs (missing = ada di golden tapi tidak terekstrak; extra = terekstrak tapi tidak ada di golden)
- heldout_cv_01: missing=['git', 'llm', 'pandas', 'python', 'pytorch', 'r', 'streamlit'] extra=[]
- heldout_cv_02: missing=['rag'] extra=[]