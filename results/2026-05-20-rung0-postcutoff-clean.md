# Rung 0 CLEAN — post-cutoff static plausibility (no execution)

*2026-05-20. The interpretable rung 0: generator and instances chosen so recall is
impossible, so "looks plausible" actually means "diagnosed," not "remembered."*

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
This is the first rung-0 result that licenses anything. On the contaminated Lite
run (`2026-05-20-rung0-static-plausibility.md`), plausibility and recall were
entangled — the "high plausible" patches were the ones reeking of memorization.
Here recall is impossible by construction, so the signal is clean:

- From the **issue text alone**, Sonnet 4.5 reached the correct root-cause
  **direction** on all three unseen bugs (two strongly, one partially while
  correctly flagging its own symptom-vs-cause hedge).
- It nailed no exact file/API — expected with no repo access. That gap is exactly
  what rung 1 (host checkout + perturb-and-inspect) is for.
- Self-confidence was calibrated: 75 where the direction held, 35 where it hedged.

**Licenses:** "the engine plausibly diagnoses bugs it provably could not have
memorized." **Does not license:** a resolved rate (no execution) or exact-fix
accuracy (no repo). Next clean step is rung 1 on these same instances — but their
non-Python toolchains (dotnet/gradle/sbt) are the cost the Python prototype dodged.

Generator transcript with patches + gold was at
`/tmp/swebench-abduction/rung0_postcutoff_results.md` (ephemeral).
