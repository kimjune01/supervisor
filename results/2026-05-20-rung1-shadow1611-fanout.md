# Rung 1 (meaty) — shadow-1611, clean-room, /investigate method ± fan-out

*2026-05-20. A non-trivial hidden-cause bug (StackOverflowError) solved clean-room by
Sonnet 4.5 running the /investigate method. Compares single-thread vs fan-out.*

## Setup
- **Instance:** `gradleup__shadow-1611` (Kotlin, created **2025-08-08**). `minimize` +
  circular dependency → StackOverflowError. Symptom (crash) far from cause (unbounded
  recursion in `MinimizeDependencyFilter.resolve()`), so genuine diagnosis needed.
- **Model:** Sonnet 4.5 (cutoff Jul 2025 < instance) — clean by training.
- **Clean room:** ephemeral EC2 + `swerebenchv2/gradleup-shadow:1611` image, **network
  disconnected** (builds offline off warm gradle cache), agent web tools disallowed.
  Fan-out subagents pinned to a `clean-sonnet` agent type (`model: claude-sonnet-4-5`)
  so every branch is clean by construction. Local model, exec over `box-sh` (ToS-safe).
- **Gate:** `./gradlew functionalTest --tests MinimizeTest --offline` → BUILD SUCCESSFUL.

## Result: both arms SOLVED (verified on offline gate)

| arm | solved | wall-clock | fix |
|---|---|---|---|
| single-thread (no fan-out) | ✓ | **156s** | +5-line skip guard in `resolve()` |
| fan-out (3 `clean-sonnet` subagents) | ✓ | **327s** | restructured recursion guard; picked from 3 tested hypotheses |

Both diagnosed the same root cause (no visited-tracking → infinite recursion on cycles)
and fixed the implementation, not the test. Clean-room held: web blocked, container
offline, all branches Sonnet 4.5.

## Findings (n=1 each — hold the bench-noise lesson)
- **Clean-room + pinned-subagent fan-out works mechanically.** 3 parallel Sonnet-4.5
  subagents tested distinct fixes (visited-set param / included-excluded-set check /
  path-based detection), measurement-only, no collision on the shared container; parent
  applied the cleanest. The `clean-sonnet` pin held — no contamination leak via subagents.
- **Fan-out was slower, not faster, on this localized bug** (~2x in this single run).
  The cause is one method's recursion; subregion-isolation already pinpoints it, so the
  three branches were largely redundant. Fan-out's breadth pays on *ambiguous/multi-cause*
  bugs, not a localized one. Wall-clock gap not yet median-verified (n=1).
- **Drove a skill change:** /investigate now gates fan-out on uncertainty (k=1 when the
  cause is already localized) — see `skills/investigate.md` Phase 2 and the blog post.

## What it licenses / doesn't
Licenses: "a clean model running the /investigate method solves a non-trivial,
hidden-cause, post-cutoff bug in a clean room (offline, no retrieval)." Stronger than
detekt (real recursion diagnosis, not a one-liner). Does NOT license: a rate (n=1), or
the fan-out slowdown as a number (needs medians via parallel containers).

## Bug-hunt (level 3): tests pass ≠ correct
Ran a clean-room adversarial bug-hunt on the fix — Sonnet-4.5 *adversary* (codex/gemini
are 2026 models, contaminated here, so fell back to the documented clean-cutoff Sonnet
adversary), web-blocked, offline, scoped to the diff's blast radius. **Verdict: DEFECT
FOUND.** The fix resolves the StackOverflowError (bench-green) but changes diamond-
dependency classification to order-dependent (first-visit-wins): a shared child reachable
via both an included and an excluded path is misclassified by visit order. The test suite
doesn't cover that case → green but regressive on the edge.

This is the concrete demonstration that **passing the test gate is not correctness**:
- level 1 (bench-resolved): tests pass ✓
- level 2 (read the diff): looks like a clean cycle guard ✓
- level 3 (adversarial review): found a diamond-dependency hole the tests miss.

Caveats: the finding is **analytical, not demonstrated** (the adversary reasoned it but
did not write a failing test; ~40% adversary false-positive prior). And the flaw is
partly pre-existing — our diff made it deterministic/worse.

**Deliberately NOT fixed.** shadow-1611 is a *benchmark instance*, not a maintainer we
ship to. The model's fix already clears the SWE-bench gate (FAIL_TO_PASS green,
PASS_TO_PASS green) = resolved, by definition. The diamond finding's value is to
*characterize the bench's pass-bar* (the gate sits below correctness — the OpenAI
flawed-tests critique, demonstrated on a clean post-cutoff instance), NOT a TODO. Acting
on it would be gold-plating a scoring target with no downstream beneficiary. Bug-hunt-to-
correct is reserved for the production lane (a real PR to a real maintainer). See
`feedback_bench_vs_production_bar` memory.
