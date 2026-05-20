# Rung 1 — post-cutoff autonomous solve (the loop, harness-graded)

*2026-05-20. First rung that licenses a real claim about the method: a CLEAN cheap
model, driving the perturb→inspect→fix→re-test loop, resolves a post-cutoff bug
graded by its actual test suite.*

## Setup
- **Instance:** `detekt__detekt-8803` (Kotlin, created **2025-10-22**). False-positive
  `RedundantSuspendModifier` on an interface function with a default body.
- **Model:** `claude-sonnet-4-5` (training cutoff **Jul 2025**) — CLEAN; the instance
  post-dates the cutoff, so a solve cannot be recall. (Opus 4.7 / Sonnet 4.6 are
  contaminated here — Jan 2026 cutoff — and must not drive the loop. The operator
  Claude is Opus 4.7, hence also contaminated; it was confined to plumbing.)
- **Infra:** ephemeral EC2 (m7i.xlarge) running the prebuilt SWE-rebench Docker image
  `swerebenchv2/detekt-detekt:8803-ffe8f6b`. **ToS-safe split:** the loop + all model
  calls ran locally on the operator's plan; every action (inspect/read/patch/test)
  executed over SSH inside the container. No model/plan creds on the rented box.
- **Gate:** `./gradlew :detekt-rules-coroutines:test --tests RedundantSuspendModifierSpec`
  — resolved iff all 17 tests pass (the 2 added failing tests + 15 regression).
- Harness injected ZERO diagnostic hints; prompt = issue + failing tests only.

## Result: SOLVED
18 steps — 12 inspects, 4 reads, **2 patches**. The loop earned its keep:
- **patch #1 (step 14) FAILED** the test → model re-inspected, re-read the source →
- **patch #2 (step 17) PASSED** all 17 tests (BUILD SUCCESSFUL).

That patch→fail→re-inspect→re-patch→pass cycle is exactly what rung 0 (one-shot, no
execution) could not do. Iterating on execution feedback is the mechanism.

**The fix (divergent from gold — a clean-diagnosis signal):**
```kotlin
if (function.getStrictParentOfType<KtClass>()?.isInterface() == true) return  // Sonnet 4.5
```
Gold used semantic modality (`function.symbol.modality == KaSymbolModality.OPEN`).
Both pass; Sonnet's is a syntactic PSI check, narrower but correct for the suite.
Unlike the contaminated sympy-12171 (byte-identical to gold = recall signature), a
*different correct* fix is the fingerprint of genuine diagnosis, not memorization.

## What it licenses
"The method — a cheap, contamination-clean model running the perturb-inspect-mirror
loop with execution feedback — resolves a post-cutoff bug, harness-graded." n=1.
Does NOT yet license a rate (need many instances, rung 2+) or a method-vs-model
ablation (one-shot vs loop on the same clean model) or harness-shape comparison
(rigid supervisor vs freeform /investigate — next).

## Cost note (the real lesson of this rung)
Every failure en route was operator plumbing, not the model: budget too small;
the task scrolling out of the context window; truncated reads; and — the big one —
the prompt not telling the model the repo was already checked out, so it tried to
`git clone` detekt from scratch and worked against its own clones while the patch
path pointed at the real repo. Fixing those (pin the task, full reads, anchor the
environment, budget 24) is what produced the solve. The rigid action-enum harness
needs the execution environment hand-held; a freeform agent with real tools likely
would not — a hypothesis to test next.

Transcript: was at `/tmp/swebench-abduction/rung1_transcript.txt` (ephemeral).

## Harness comparison: rigid supervisor loop vs freeform full-tool agent
Same instance, same clean model (Sonnet 4.5), same gate (17/17), same no-hint prompt.
Only the harness shape differs.

| | Rigid supervisor loop (JSON inspect/read/patch) | Freeform agent (full default toolset) |
|---|---|---|
| Solved | yes | yes |
| Reached solve | after **3 operator reruns** fixing plumbing (budget; context window dropping the task; env not anchored → it tried to `git clone`) | **first run**, ~299s wall-clock |
| Iteration | patch#1 fail → re-inspect → patch#2 pass (18 steps) | iterated internally, solved in one invocation |
| Operator scaffolding | high — I hand-held budget/context/environment | low — handed it one `box-sh` helper + the prompt |
| Fan-out | not supported by the prototype | available, **unused** (bug too localized to need breadth) |
| Fix shape | interface-parent check only | interface-default **and** abstract — more thorough |

**Verdict (n=1, one localized bug — do not over-generalize).** The freeform agent
solved it first try with minimal scaffolding; the rigid loop solved it only after I
fixed three plumbing failures. But the dominant advantage was **self-management of
context / navigation / environment** (the exact things the rigid enum made me hand-
hold), not a unique "isolate the buggy region" move — the freeform agent grepped to
the rule quickly, but so could the rigid one once it knew where it was. The "freeform
is faster" read also partly conflates harness *maturity* (my prototype was buggy)
with harness *shape*; a fair restatement is **freeform needed far less operator
scaffolding to reach a solve**. Fan-out was never exercised — its value (parallel
hypotheses, breadth) would show on an *ambiguous* bug, not this single-file fix, and
would require pinning subagents to Sonnet 4.5 (contamination) + per-hypothesis repo
copies (parallel interventions collide on one container). Both arms produced
divergent-but-correct fixes — neither matched gold's `KaSymbolModality.OPEN` — which
is consistent across both: clean-model diagnosis, not recall.
