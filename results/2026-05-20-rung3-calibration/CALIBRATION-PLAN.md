# Rung 3 (practice) — calibration round to harden the pipeline

**Committed:** 2026-05-20, before any patch production.

## What this round IS (and is not)
A **practice / calibration round**, not a publishable result. Its only purpose is to
**exercise the clean-room pipeline on real post-cutoff instances and surface what to fix** in
the `/investigate` skill and the surrounding harness (gate derivation, toolchain support,
clean-room hygiene). Failures here are the product: each DNF, broken gate, or wrong diagnosis
is an improvement target fed back into the skill (the backward pass).

It asserts **no rate**. The team only publishes a result from a frozen config that **matches
or beats SOTA models on a clean comparable set** — nobody cares about a bench number that
doesn't beat SOTA. This round earns that config; the publishable rung gets its own clean
preregistration later (declared estimand, optional-stopping / precision rule, finite-population
CIs, a matched baseline run).

## Contamination firewall (the load-bearing rule)
**Every instance revealed during calibration is BURNED for the publishable evaluation.** We
tune the skill/harness on what breaks here, so these instances are no longer a fair test set.
- The publishable rung draws **only from never-revealed instances** of this pool (or a fresh
  pull). Calibration therefore must **not** consume the whole pool — we reveal in small
  doubling prefixes and stop calibrating while clean tail remains.
- `calibration-pool.json` records the full seeded order so we always know exactly which
  prefix has been revealed (= burned) and which tail is still clean.

## Why a frozen permutation + doubling
Cost discipline. Each instance is a Docker box-run (~5GB pull) + a Sonnet solve + a canonical
grade. We commit one seeded order now and reveal it in doubling prefixes
(**5 → 10 → 20 → 40 …**) so we fix the skill on cheap evidence before scaling spend. The
doubling is a spend cadence, not a statistical design — and it doubles as the burn ledger.

## Calibration pool (frozen order, NOT an evaluation population)
- **Source:** `nebius/SWE-rebench-V2`, parquet `default/train/0.parquet` (32,079 rows).
- **Filter:** `created_at > '2025-07-22' AND language != 'python'` → **123 instances**, 51
  repos, all with prebuilt `image_name`.
- **Why `2025-07-22`:** the *empirical last-Python date* in this dataset (Python tops out
  2025-07-22; none after) — a conservative contamination boundary against Sonnet 4.5's
  ~Jul-2025 cutoff, not a day-level cutoff claim. Post-cutoff lowers contamination *risk*; it
  does not prove zero memorization.
- **Pool fingerprint (sha256 of newline-joined instance_ids sorted ascending):**
  `09863d6a4d7b549f7516a8abda0098e5ddbba0d25107a64debd06baec4eaa99a`.
- Seed = **20260520**; RNG = `python random.Random(20260520).shuffle` on the ascending-sorted
  instance_id list. Full order in `calibration-pool.json` → `permutation`.

### Round 1 (first 5 — burned on reveal)
1. `juliastats__mixedmodels.jl-858`  [julia/medium]
2. `kevincianfarini__cardiologist-164`  [kotlin/easy]
3. `detekt__detekt-8604`  [kotlin/easy]
4. `rook__rook-16165`  [go/easy]
5. `jump-dev__jump.jl-4050`  [julia/easy]

Spans julia / kotlin / go. Rung 2 only proved gradle + KMP-kotlin gates, so julia and go are
the first things expected to break — exactly what we want to learn cheaply.

## Pre-flight (run BEFORE any Sonnet spend, per instance — fail fast, cheap)
1. Image exists + pulls; **record image digest** (not just `image_name`).
2. Container boot smoke test; disk budget OK.
3. Language runtime + package-manager entrypoint present in the image.
4. `git apply` the `test_patch` cleanly; cheap test-discovery / build command runs.
5. **`eval.py --golden-eval`** — gold patch grades? If not → bench defect, set aside (does
   NOT enter skill calibration; it's a harness-compatibility signal only).
6. After warming online then cutting network: offline mode still permits required local deps.
7. `box-sh` reaches the SUT from where the model runs (the rung-2 L1 scar).
8. **Clean-room audit:** confirm gold patch / future-commit diffs / harness metadata beyond
   issue text + test names are NOT mounted in the agent-visible workspace.

Any pre-flight failure = skip the Sonnet solve for that instance and log it; no point burning
tokens (or the instance) on an environment we can't even set up.

## Per-run log (one record per instance — so /retro gets trendable signal, not anecdotes)
`instance_id`, repo, language, **image digest**, gold-eval verdict + transcript, solve
start/end, wall-clock + container timeouts, token/cost totals, exact agent prompt + `/investigate`
**skill git hash**, tool versions, derived gate command + derivation rationale, every gate
attempt + output, final patch diff, official grading JSON, **failure_class** (taxonomy below),
suspected root cause, and **fix_target** ∈ {skill, harness, image/toolchain, bench-defect,
model-behavior}.

### Failure taxonomy (type every non-RESOLVED outcome)
`bench-defect` · `image-pull-fail` · `toolchain/dep-missing` · `build-system-unsupported` ·
`gate-derivation-error` · `clean-room-violation` · `timeout` · `model-wrong-diagnosis` ·
`model-incomplete-patch` · `official-harness-mismatch`. Bench-defects and harness/toolchain
classes are **harness work**; only `model-*` classes are skill-calibration signal proper.

## RESOLVED definition (when it happens)
`from_fail_to_pass ⊇ FAIL_TO_PASS` AND `failed_from_pass_to_pass == []`, per the official
harness — never the agent's prose. Gate-grounded: the agent declares RESOLVED only when its
`gate` tool prints PASS.

## Config to freeze (for reproducibility and the eventual real run)
- Model `claude-sonnet-4-5`, headless invocation, `ANTHROPIC_API_KEY` scrubbed (plan tokens,
  not API), `--disallowedTools WebSearch WebFetch Task`.
- `/investigate` skill git hash injected verbatim, recorded per round.
- Clean-room invariants: offline container (network cut after warm), SUT only via local
  `box-sh`, isolated hygraph dir, `~/Documents/sweep` off-limits, no gold patch visible.

## Feedback loop (the actual deliverable)
After each round: `/retro` over the trajectories, compress recurring failure modes into
skill/harness patches, re-freeze the skill hash, reveal the next prefix. **Each retro patch
must name the generalized invariant it improves and list the calibration instances that
motivated it** — generalized fixes only, never instance-specific recipes (that would be
overfitting the burned set). Output: a hardened, frozen, SOTA-competitive config — not a rate.
