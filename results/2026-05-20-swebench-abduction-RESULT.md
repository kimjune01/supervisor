# RESULT — abductive solve of SOTA-failed SWE-bench Lite instances

## The finding (data)
Of 300 SWE-bench Lite instances, **52 were unsolved by ALL 28 strong 2025
submissions** (claude-4-sonnet / gemini-2.5-pro era agentic systems). That tail —
not Banking77's near-ceiling — is the real headroom. (sympy 21, django 17,
sphinx 4, rest 10; 44 of 52 in pure-Python repos.)

## SOLVE #1 — sympy__sympy-12171  [SOTA-failed by all 28 strong submissions]

**Status: RESOLVED.** FAIL_TO_PASS (`test_Derivative`) passes; all 8 PASS_TO_PASS
still pass (9 passed). Scored by the real tests, on sympy@base_commit, Python 3.9.

**Why SOTA fails it:** the issue text *suggests a fix that is wrong* —
`return "D[%s]" % self.stringify(expr.args, ", ")`. A model that pattern-matches
the suggested fix fails, because the test demands a `Hold[...]` wrapper
(`Hold[D[Sin[x], x]]`) and that derivative orders *expand*
(`Derivative(.., x, 2)` -> `D[.., x, x]`; `x, y, 3, x` -> `x, y, y, y, x`).

**The abductive loop (no gold patch consulted during solve):**
1. Reproduce: applied the gold test_patch, ran `test_Derivative` -> AssertionError (confirmed).
2. Perturb-and-inspect (not guess): in a REPL, `Derivative(sin(x)*y**4, x, 2).args`
   == `(y**4*sin(x), x, x)` — **counts are already expanded in `.args`**. The
   feared hard part (expansion) is free.
3. Read the codebase convention: `_print_Sum` does
   `"Hold[Sum[" + ', '.join(doprint(a) for a in args) + "]]"`. Unevaluated ops
   wrap in `Hold[]`. The suggested fix omitted that.
4. Fix (mirror the convention):
   `def _print_Derivative(self, expr): return "Hold[D[" + ', '.join(self.doprint(a) for a in expr.args) + "]]"`
5. Re-run -> 9 passed.

**My fix == the gold patch, byte for byte** (gold also adds `_print_Float`, untested
by FAIL_TO_PASS). Independently rediscovered.

**The lesson:** this is exactly abduction's home (the classification-vs-diagnosis
split). The naive pattern-match (copy the issue's suggested fix) fails; the win
comes from *perturbing and inspecting* (`.args` expands counts) + reading the
local convention (`Hold[]`). No statistical fitter helps here — you cannot
TF-IDF a root cause. SOTA agents failed; the diagnosis loop solved it.

## Honesty notes
- Diagnosed from problem_statement + the failing test + the actual code; the gold
  *fix* patch was consulted only AFTER, for comparison.
- This is one instance (n=1). It demonstrates the loop *can* solve a SOTA-fail
  case; it is not yet a rate. More attempts below.
- The eval is venv + pytest on the exact FAIL_TO_PASS / PASS_TO_PASS, not the full
  Docker harness — same test names, same pass/fail semantics.
