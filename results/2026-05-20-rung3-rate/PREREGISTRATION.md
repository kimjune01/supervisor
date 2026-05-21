# Rung 3 — preregistered post-cutoff rate (SWE-rebench-V2, non-Python)

**Committed:** 2026-05-20, *before* any patch production. This commit is the preregistration.

## Claim under test
A contamination-clean autonomous diagnosis pipeline — the `/investigate` skill driven by
**Claude Sonnet 4.5** (cutoff Jul 2025) in an offline clean room, gate-grounded, graded by
the **official SWE-rebench-V2 harness** — resolves real post-cutoff bugs at a measurable
pass@1 *rate*, compared like-for-like to Sonnet 4.5's ~60% SWE-rebench pass@1 (owning that
ours is **non-Python + strict post-cutoff**, i.e. harder and unmemorizable).

## Population (frozen)
- **Source:** `nebius/SWE-rebench-V2`, parquet `default/train/0.parquet` (32,079 rows).
- **Filter:** `created_at > '2025-07-22' AND language != 'python'`.
  - Rationale: Sonnet 4.5 cutoff = Jul 2025. Python in this dataset tops out 2025-07-22
    (only 2 rows on that exact day, none after), so the post-cutoff clean set is non-Python.
- **Population N = 123**, across 51 repos, all with prebuilt `image_name`.
- **Population fingerprint (sha256 of sorted instance_ids):**
  `09863d6a4d7b549f7516a8abda0098e5ddbba0d25107a64debd06baec4eaa99a`
  (recompute: `sha256(newline-joined instance_ids sorted ascending)`).

## Sampling design (group-sequential over a frozen permutation)
- One seeded permutation of all 123 IDs is committed up front (`PREREGISTRATION.json` →
  `permutation`). Seed = **20260520**; RNG = `python random.Random(20260520).shuffle` on the
  ascending-sorted instance_id list.
- The sample **doubles each round**, always as a **prefix** of the frozen permutation:
  **round schedule = [5, 10, 20, 40, 80, 123]**.
- This is a group-sequential design, not reshuffling-after-results: the order is fixed now,
  rounds only reveal more of it. Denominator at each round = the prefix length.
- **No per-repo cap, true random** (sample reflects the dataset's real composition; shadow
  and detekt are heavy by design).

## Round 1 (first 5)
1. `juliastats__mixedmodels.jl-858`  [julia/medium]  JuliaStats/MixedModels.jl
2. `kevincianfarini__cardiologist-164`  [kotlin/easy]  kevincianfarini/cardiologist
3. `detekt__detekt-8604`  [kotlin/easy]  detekt/detekt
4. `rook__rook-16165`  [go/easy]  rook/rook
5. `jump-dev__jump.jl-4050`  [julia/easy]  jump-dev/JuMP.jl

## Counting rules (fixed in advance)
- **pass@1**, one `model_patch` per instance, no retries on the same instance.
- **DNFs count in the denominator** (no quiet drops). An instance that fails to build,
  times out, or the agent errors on = NOT RESOLVED, counted.
- **Bench-defect exclusion** is the *only* legitimate removal: screen each instance with
  `eval.py --golden-eval` up front; if the GOLD patch itself doesn't grade, exclude it and
  count it separately (the defect base-rate is itself a reported finding). Established in
  rung 2: shadow-1613 (unmatchable F2P lambda IDs) and kiota-6835 (gold fails to grade).
- **RESOLVED** iff `from_fail_to_pass ⊇ FAIL_TO_PASS` AND `failed_from_pass_to_pass == []`,
  per the official harness — never the agent's prose.

## Toolchain risk (acknowledged, not filtered around)
Round 1 spans julia / kotlin / go. Rung 2 only proved gradle + KMP-kotlin gates; julia and
go gates are untested here. True-random selection means we take what comes — toolchain
breakage that yields a DNF is counted in the denominator, not silently dropped or reshuffled
away. (If a *whole toolchain* proves unrunnable in the harness env, that is a harness finding
reported alongside, the same class as a bench defect.)
