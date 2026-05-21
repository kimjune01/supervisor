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
doesn't beat SOTA. This round produces a **frozen candidate config**; it does not itself
estimate performance or prove SOTA-competitiveness. Only the later publishable rung — its own
clean preregistration (declared estimand, optional-stopping / precision rule, finite-population
CIs, a matched baseline on the identical tail) — estimates the rate.

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

## The ladder is per-skill-version; modification resets it to 5
The doubling ladder belongs to a **single, unmodified skill version**. **Any modification to
the `/investigate` skill or the harness resets the rung back to 5.** A config "earns" its way
up only by climbing **without changes**.

This narrows the optional-stopping concern, it does not abolish it: the rule prevents any
**publishable rate from being estimated on an adaptively modified calibration prefix** (the
bad "peek → tweak → extend the same sequence → report it" pattern). It does **not** make
optional stopping categorically harmless. Two residuals remain and are tolerated *only because
the publishable claim lives on a never-revealed tail*: (a) the final config is **selected** by
having survived prior burned prefixes while other versions failed/were changed — selection over
configs, not bias in the clean-tail estimate; (b) **multiple comparisons across skill versions**
can overfit the calibration distribution. Both are why the ladder yields a *candidate*, and the
clean tail (config frozen first, estimand/CI/baseline preregistered) is what actually estimates
performance.

**The tail is the overfitting detector — not a thing the calibration design must pre-empt.**
Whether the harness/skill overfit the calibration problems is *not decidable here*; it is
decided entirely by performance on the final rung. A config that climbed the ladder but then
drops on the never-revealed tail was overfitting, and the gap measures it. A config that holds
generalized. We do not argue the overfitting risk away in advance — we let the one measurement
that's allowed to count adjudicate it.

**Reset mechanics (minimize burn):** a restart re-runs the modified skill on the instances
**already revealed** (they're already burned — re-running costs no new contamination, and it
verifies the fix didn't regress instances that previously passed). **The burned prefix is
global across all skill versions, not per-version.** Fresh instances are revealed only when a
skill version climbs past the deepest prefix *any* prior version reached. This spends the clean
tail slowly — a cost-control rule, not a performance claim (later revealed instances are by
construction reached by selected configs, so they are calibration, never evidence of a rate).

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
*tokens* on an environment we can't even set up.

> **Burn rule (hard).** Any instance whose id, issue text, test_patch, gold-eval output, image
> behavior, or harness transcript is **inspected** during calibration is **burned** for the
> publishable evaluation — *regardless of whether a Sonnet solve ran.* Skipping the solve saves
> tokens only; it does not preserve the instance. "Revealed" = "inspected," and the burned
> prefix is global. (A pre-flight failure still burns the instance; it just doesn't cost tokens.)

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

## Execution architecture (decided round 1, 2026-05-20)
**Fan out across N ephemeral EC2 boxes — one instance-slice per box — not one box
sequentially.** The model runs locally on the plan and SSH-execs into the box's container;
per-instance wall-clock is dominated by the online *warm* step (building the full
gradle/julia test suite once) and the agent's *gate* calls (each RESOLVED check re-runs the
whole `test_cmd` in the container). Sequential makes those additive — round 1's three solves
ran one box, one at a time, and it dragged.
- **Why boxes, not containers-on-one-box:** a small box (m7i.xlarge = 4 vCPU / 15 GB) can't
  hold two concurrent gradle JVMs + a julia build without contention/OOM; and 2–3 parallel
  local `claude --print` processes risk plan `Overloaded` DNFs (a rung-2 scar). Separate
  ephemeral boxes give each slice full CPU/RAM and isolate failures. Boxes are cheap and torn
  down immediately — provision N, run, terminate (+ delete key-pair & SG).
- **Proven in rung 2** (it used 4 boxes B/C/D). Reuse that pattern for round 2+.
- Concurrency is bounded by plan rate limits, not box count — keep local `claude` fan-out
  modest (≤2–3 in flight) even across many boxes.

## Config to freeze (for reproducibility and the eventual real run)
- Model `claude-sonnet-4-5`, headless invocation, `ANTHROPIC_API_KEY` scrubbed (plan tokens,
  not API), `--disallowedTools WebSearch WebFetch Task`.
- `/investigate` skill git hash injected verbatim, recorded per round.
- Clean-room invariants: offline container (network cut after warm), SUT only via local
  `box-sh`, isolated hygraph dir, `~/Documents/sweep` off-limits, no gold patch visible.

## Feedback loop (the actual deliverable)
After each round, `/retro` over the trajectories:
- **If the round surfaced a fault** → patch the skill/harness, record the new skill git hash,
  and **reset the rung to 5** (re-run on already-revealed instances first; see reset mechanics).
  Each retro patch must name the **generalized invariant** it improves and list the calibration
  instances that motivated it — generalized fixes only, never instance-specific recipes (that
  would be overfitting the burned set).
- **If the round was clean** (no modification needed) → keep the skill hash frozen and **double
  the prefix**, revealing fresh instances.

Output: a hardened skill version that climbed the full ladder unmodified — a frozen
**candidate** config — not a rate. (Whether it's SOTA-competitive is decided by the publishable
rung, not here.)

## Publishable-tail protocol (committed now; full prereg comes later)
Fixed in advance so calibration choices can't bend the eventual claim:
- **Eligible set:** only **never-inspected** instances of this pool (the clean tail), or a
  fresh dataset pull. The burned prefix is excluded by the global burn rule above.
- **Defect handling:** the same pre-flight + `--golden-eval` filter is applied **blind, before
  any solve**, to the tail. Instances whose gold patch doesn't grade are excluded as bench
  defects and reported separately — they never silently re-enter the scored denominator.
- **Freeze before evaluation:** the candidate skill git hash + full config is frozen and
  recorded *before* the tail is touched. No modification during tail evaluation (that's the
  whole point of the practice rungs).
- **Baseline:** the SOTA comparison runs on the **identical tail**, same harness, same grading.
- **Estimand + uncertainty:** declared in the tail's own preregistration (finite-population
  rate, DNFs = failures, CI method, stopping/precision rule). Not asserted here.
