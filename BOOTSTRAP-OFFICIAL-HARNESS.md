# BOOTSTRAP — canonical official-harness run on the 4 challenges, then climb

*Self-contained. A fresh agent should run this cold. Produced 2026-05-20 after a long
night of bespoke-harness pain; the lesson is: stop hand-rolling the grader, use the
official SWE-rebench-V2 harness. This doc is the clean re-do.*

## Mission
Get **canonical, official-harness verdicts** on the 4 "confusing" post-cutoff instances
(where my bespoke grader gave ambiguous/wrong results), then climb the ladder. The
intellectual method is done and validated; this is the squeaky-clean *measurement*.

## The 4 challenges (instance_ids in `nebius/SWE-rebench-V2`, all post-cutoff, non-Python)
- `gradleup__shadow-1613` — directory ZIP regression. My grader FAILED it; fail-on-base
  proved the F2P went red→green (the failures were pre-existing/dirty-base). Likely a PASS.
- `gradleup__shadow-1714` — multi-class-descriptor relocation. **Genuine wall** (3 blind
  agents all missed it; one falsely self-reported 99% on unit tests while the functional
  test stayed red). Real defining tests: `relocateMultiClassSignatureStringConstants`,
  `relocateSignaturePatterns`, `classSignatureStringConstants`.
- `orchestr7__ktoml-353` — KMP `jvmTest` (flip-flopped FAILED→pass across runs).
- `arkivanov__decompose-916` — KMP, gradle-wrapper unzip noise.

**Two bench-garbage caveats (verified tonight):** (a) the `FAIL_TO_PASS` metadata field is
**wrong** for several shadow instances (lists `PropertiesFileTransformerTest` /
`SimpleRelocatorTest`, unrelated to the test_patch) — the *real* defining tests are the
methods ADDED by `test_patch`. (b) Base repos are **dirty** (6–12 tests already red at the
pinned commit). The official harness grades against the dataset's `FAIL_TO_PASS`/`PASS_TO_PASS`
and excludes pre-existing failures correctly — which is exactly why we use it over my
whole-class grader. If the canonical F2P for an instance is itself garbage, flag it as an
unscoreable bench defect (a publishable finding, not our failure).

## Architecture (keep / retire)
- **KEEP — our clean-room agent phase** produces ONE artifact per instance: a `model_patch`
  (git diff). Everything below "produce patches" is ours.
- **RETIRE — my bespoke setup/derive_gate/grade.** Grading is the official harness.

## Phase A — produce patches (clean-room agent)
Per instance, on a box with Docker (NOT local — pulls are too slow locally; see infra):
1. `docker run` the row's `image_name` (prebuilt, public on Docker Hub). Repo is at base_commit.
2. `git apply` the `test_patch` (adds the failing tests).
3. **Warm online**: run the gold/defining test once with network UP (caches gradle deps +
   wrapper; also captures fail-on-base attestation). THEN `docker network disconnect bridge`.
4. Run the clean-room agent: `claude --print --model claude-sonnet-4-5` (CLEAN: cutoff
   Jul 2025 < instances' Aug–Oct 2025), `--disallowedTools WebSearch WebFetch Task`,
   **env with `ANTHROPIC_API_KEY` scrubbed** (else it bills API credits, not the plan).
   Inject the FULL `/investigate` skill verbatim (no paraphrase confound). The SUT is
   reached only via a local `box-sh` helper (ssh→`docker exec`); hygraph writes to an
   isolated `/tmp` dir; `~/Documents/sweep` is OFF-LIMITS (contains prior diagnoses).
5. **Gate-grounded resolution (the key fix):** give the agent a `gate` tool that runs the
   *defining* tests (the added methods, dirty-base-safe) and self-logs to `gate.log`. The
   agent is RESOLVED only when `gate` prints PASS. No PASS in `gate.log` = not resolved,
   regardless of the agent's prose. (Stops the shadow-1714 false-resolve by construction.)
6. Capture `git diff` → the `model_patch`.

## Phase B — grade with the official harness (canonical)
Harness: `github.com/SWE-rebench/SWE-rebench-V2` → `scripts/eval.py` (NOT vanilla `swebench`;
it can't parse non-Python). Cloned at `/tmp/swerebench-v2`. **Needs Python 3.10+** (`str|None`).
```bash
# patches.json = JSON LIST of {"instance_id","patch"} (NOT model_patch/model_name_or_path)
cd /tmp/swerebench-v2
python3.12 scripts/eval.py \
  --hf-dataset nebius/SWE-rebench-V2 --hf-config default --hf-split train \
  --patches patches.json \
  --instance-ids gradleup__shadow-1613,gradleup__shadow-1714,orchestr7__ktoml-353,arkivanov__decompose-916 \
  --max-workers 4 --report-json eval_report.json
# DO NOT pass --golden-eval (grades the gold patch, not yours).
```
- **If HF rate-limits (429)** — likely after heavy querying — use `--json tasks.json` instead
  of `--hf-dataset`: a local JSON list of the full rows (must include `image_name`,
  `install_config`, `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`). Pull rows once via the
  parquet (`huggingface.co/.../resolve/refs%2Fconvert%2Fparquet/.../0000.parquet`, duckdb).
  Cached partial rows are in `~/Documents/supervisor/.../rung2_instances.json` (lacks
  `install_config` — re-pull that field, or reuse same-repo config).
- Uses the row's prebuilt `image_name` (pull + `rmi` after). Needs Docker + network + disk.
- **Verdict (programmatic):** instance RESOLVED iff `from_fail_to_pass == FAIL_TO_PASS`
  (all) AND `failed_from_pass_to_pass == []`. Per-instance logs in `logs/<id>_log.txt`.

## Critical gotchas (paid for in full last night)
1. **Use a fast-network box for image pulls**, not local — 5GB images time out locally
   (~hours); on EC2 they pull in minutes. Provision, run, **tear down immediately** (cost).
2. **Scrub `ANTHROPIC_API_KEY`** before any headless `claude` call → uses the plan, not
   pay-per-token API credits (this silently drained the API pool all night).
3. **box-sh is LOCAL** (where the model runs), not on the box.
4. **Grade on the defining tests / canonical F2P, never the agent's self-report.**
5. **No data pollution between runs**: isolated hygraph dir, sweep off-limits, evacuate strays.
6. Concurrency vs API overload: keep agent concurrency low (≤2–3) to avoid `Overloaded` DNFs.

## Climb the ladder
See `BOOTSTRAP-SWEBENCH.md` (the rung ladder) and `RUNG2-PLAN.md`. Status:
- **Rung 1 — DONE.** Clean post-cutoff solves (detekt-8803, shadow-1611), harness comparison,
  bug-hunt. Results in `results/2026-05-20-rung1-*`.
- **Rung 2 — DIRECTIONAL.** ~6/8 by the *bespoke* grader (dirty-base caveat); shadow-1714 a
  genuine wall; detekt a rescued DNF. `RUNG2-LEDGER.md` has the scars.
- **Rung 3 — THIS DOC + codex's prescription.** Freeze the driver, preregister a random/
  stratified post-cutoff sample, full denominator (count DNFs), grade canonically with the
  official harness, blinded patch-quality review. That's the publishable, SOTA-comparable run.
- **Then:** a *rate* over a larger preregistered set → the SWE-rebench-shaped, re-runnable
  claim. Compare like-for-like (our pass@1 vs Sonnet 4.5's ~60% SWE-rebench pass@1), owning
  that ours is non-Python + strict-post-cutoff (harder).

## The one-line repro test for any published result
A stranger should `checkout <skill>`, point `claude --model claude-sonnet-4-5` at it, run
`scripts/eval.py` on the listed instance_ids, and get the number ± noise — without talking
to you. Everything in the manifest exists to make that sentence true.
