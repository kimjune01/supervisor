# RESULT — abductive diagnosis on SOTA-failed SWE-bench Lite instances

## Headline
The abductive loop **solved a SWE-bench Lite instance that all 28 strong 2025
SOTA submissions failed** — fix byte-identical to the gold patch, scored by the
real tests, diagnosed without the gold patch. n=1 rigorous (+1 correct-diagnosis,
version-blocked). This is on abduction's home turf — diagnosis, not classification
— where Banking77 had none.

## The headroom (data)
Of 300 SWE-bench Lite instances, **52 are unsolved by ALL 28 strong 2025
submissions** (claude-4-sonnet / gemini-2.5-pro-era agents). sympy 21, django 17,
sphinx 4, rest 10; 44/52 pure-Python. That tail is the real headroom.

## SOLVE #1 — sympy__sympy-12171  [RIGOROUS; SOTA-failed by all 28] ✅
- **RESOLVED**: FAIL_TO_PASS (`test_Derivative`) passes + all 8 PASS_TO_PASS pass
  (9 passed). Exact base_commit (sympy 1.0), Python 3.9, scored by the real tests.
  **Re-verified on a clean checkout.**
- **Why SOTA fails it:** the issue text *suggests a wrong fix*
  (`"D[%s]" % stringify(...)`). Pattern-matching the suggestion fails — the test
  needs a `Hold[...]` wrapper and expanded derivative orders.
- **Abductive loop:** reproduce (test fails) -> perturb-and-inspect
  (`Derivative(..,x,2).args == (expr, x, x)` — counts pre-expanded, the hard part
  is free) -> read the local convention (`_print_Sum` -> `Hold[Sum[...]]`) ->
  fix by mirroring it. **My fix == the gold patch, byte for byte.**

## SOLVE #2 — sympy__sympy-13437  [correct diagnosis; version-blocked, NOT rigorous] ⚠️
- The reported bug: `bell(oo)` should be `oo` (not unevaluated).
- Abductive loop found the precedent (fibonacci/lucas `eval` do
  `if n is S.Infinity: return S.Infinity`) and applied it to `bell.eval`.
  **Directly verified:** `bell(oo)==oo`, `bell(n).limit(n,oo)==oo`,
  `bell(oo,x)` raises `ValueError` — all correct, the reported issue is fixed.
- **NOT counted as a rigorous solve:** the instance pins sympy 1.1, but its base
  commit's file-tree isn't fetchable (GitHub: "not our ref"; partial clone) — so
  I could only run on sympy 1.0. The 1.1 test also asserts `bell(-1)` raises
  (off-issue, version-dependent), which doesn't hold on 1.0. Honest status:
  correct diagnosis of the reported bug; not a validated instance pass.

## The lesson (the point)
This is exactly the classification-vs-diagnosis split. Banking77 (classification)
gave abduction no edge — TF-IDF won. SWE-bench (diagnosis on a perturbable system)
is abduction's home: the win comes from *reproduce -> inspect -> mirror the
convention*, which no statistical fitter can do (you can't TF-IDF a root cause).
SOTA agents fail #1 because they pattern-match the issue's wrong suggested fix;
the diagnosis loop solves it by *looking at the actual structure*.

## Honest bounds
- **n=1 rigorous.** Demonstrates the loop *can* solve a SOTA-fail case; not yet a rate.
- **Infra wall to scaling:** many instances' exact base-commit trees aren't
  fetchable from github by SHA (partial clone / GC'd refs). A real rate needs the
  **SWE-bench Docker harness** (pinned per-instance env), which is the next step.
- Eval = venv + pytest on the exact FAIL_TO_PASS/PASS_TO_PASS (same names/semantics
  as the Docker harness), not the harness itself.
- Diagnosis done without the gold *fix* patch; gold consulted only for comparison.

## Cleanup
All artifacts in `/tmp/swebench-abduction` (instance data, cloned sympy + venv).
`rm -rf /tmp/swebench-abduction`. No Docker images pulled. This file is mirrored to
`~/Documents/supervisor/results/`.
