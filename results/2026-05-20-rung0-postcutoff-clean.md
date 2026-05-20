# Rung 0 CLEAN — post-cutoff static plausibility (PLUMBING, not evidence)

*2026-05-20. Generator and instances chosen so recall is impossible. **But rung 0
does not exercise the engine** — with no repo there is nothing to perturb, so this
is a single model call, not the loop. It measures the base model's prior, not the
method. Kept as a calibration note; the first real measurement is rung 1.*

## Setup
- **Generator:** `claude-sonnet-4-5` (training cutoff **Jul 2025**). Chosen over
  Sonnet 4.6 (cutoff Jan 2026) precisely because 4.6 post-dates every public
  decontaminated dataset, leaving no clean window.
- **Instances:** SWE-rebench V2, `created_at` Aug–Oct 2025 — strictly after the
  generator's cutoff. Mainstream langs (python/go/ts/js/rust/java) top out at
  ~2025-07 in V2, so the only post-cutoff instances are **non-Python**: C#, Kotlin,
  Scala. (SWE-bench-Live is worse: ceiling 2025-08-30, Python-centric.)
- Sonnet 4.5 generated a candidate patch from `problem_statement` alone (gold
  withheld), self-rated. codex (gpt-5.5) judged diagnostic direction + plausibility,
  also gold-blind. No clone, no Docker, no tests.

| instance | lang | created | self-conf | codex: direction / plausible | vs gold |
|---|---|---|---|---|---|
| spectre.console-1942 | C# | 2025-10-31 | 75 | yes / high | right direction, wrong method (gold patches `Measure()`) |
| detekt-8803 | Kotlin | 2025-10-22 | 75 | yes / high | right direction, narrower predicate (gold exempts OPEN modality, not just interface) |
| effekt-1101 | Scala | 2025-08-06 | 35 | partly / med-low | implemented symptom-fix but *named* gold's upstream fix; conf appropriately low |

## Finding
Fixing contamination exposed a deeper limit: **rung 0 cannot test the method.** The
thesis is that the loop (reproduce → perturb-and-inspect → mirror → re-test) beats
one-shot guessing. With no repo, nothing is perturbed — the engine is never invoked.
So what this run observed is the **base model's prior**, not the engine:

- From the **issue text alone**, Sonnet 4.5 reached a plausible root-cause
  **direction** on all three unseen bugs (two strongly, one partially while
  flagging its own symptom-vs-cause hedge). For a frontier model, this is close to
  expected — not a surprising result, and there is no baseline here.
- It nailed no exact file/API — expected with no repo access.
- Self-confidence tracked direction (75 vs 35), n=3. Thin.

**Licenses:** nothing about the engine. **Genuinely learned (all meta):**
1. A hard constraint — post-cutoff ∩ Python ∩ executable = empty in public data
   (mainstream langs top out 2025-07 in V2; clean Python needs build-your-own).
2. The cutoff-based selection pipeline is mechanically sound and executable.

**Next:** skip rung 0 as a stage; start measurement at **rung 1** (a checkout to
perturb) — where the non-Python toolchains (dotnet/gradle/sbt) become the real cost.

Generator transcript with patches + gold was at
`/tmp/swebench-abduction/rung0_postcutoff_results.md` (ephemeral).
