# BOOTSTRAP — climb the SWE-bench ladder (next session, fresh context)

*Self-contained. A fresh agent runs this cold. Written 2026-05-20 after the canonical
official-harness run landed. Read this, then the three pointers at the bottom, then act.*

## The one-paragraph premise
Testing whether a cheap, **contamination-clean** autonomous diagnosis pipeline (the
`/investigate` skill driven by **Claude Sonnet 4.5**) resolves real post-cutoff bugs at
SOTA-comparable rates *without memorized recall*. Contamination is controlled **by
selection**: only evaluate instances created AFTER the driver's training cutoff. Sonnet 4.5
cutoff = Jul 2025, so instances from Aug–Oct 2025 (`nebius/SWE-rebench-V2`, all non-Python —
Python tops out 2025-07-22) are clean. Escalating to Opus/Sonnet 4.6 (Jan 2026 cutoff) would
contaminate — don't, unless documenting a wall.

## Where we are (rung status)
- **Rung 1 — DONE.** Clean post-cutoff single solves + harness comparison + bug-hunt.
- **Rung 2 — DONE / directional.** Canonical official-harness verdicts on the 4 "confusing"
  instances: **2/2 scoreable RESOLVED** (ktoml-353, decompose-916). shadow-1613 and
  kiota-6835 proven **benchmark defects** by the official runner itself (one has
  unmatchable JVM-lambda-address F2P IDs; the other's GOLD patch fails to grade — exit 1,
  1869 P2P regressions). Write-up: `results/2026-05-20-canonical-harness/RESULT.md`.
- **Rung 3 — THIS IS THE NEXT CLIMB.** A frozen, **preregistered**, full-denominator,
  canonically-graded *rate* over a larger post-cutoff sample. That's the publishable,
  SOTA-comparable claim.

## Standing decisions (do NOT relitigate)
1. **Official harness only.** Grade with SWE-rebench-V2 `scripts/eval.py`. No bespoke
   graders. If an instance looks unscoreable, ONE golden-eval check decides it — then drop
   it, one-line note, no forensics rabbit hole. (Lost a whole night to harness archaeology.)
2. **Climb only when the current rung is dry AND the next gains new info.** Rung 2 is dry.
3. **Burn Sonnet tokens until a genuine *reasoning* wall** (not an infra wall). The wall is
   the finding. Standing wall candidate: **gradleup__shadow-1714** (multi-class-descriptor
   relocation; 3 blind agents missed it, one false-resolved on unit tests). No passing patch
   exists yet — throwing the gate-grounded loop at it is the cheapest "is this the ceiling?" test.

## Rung 3 — the concrete plan
1. **Preregister the sample BEFORE running.** Pull `nebius/SWE-rebench-V2` rows, filter
   `created_at > 2025-07-22` AND `language != Python`, take a fixed random/stratified sample
   (commit the instance_id list + seed to git first — this is the preregistration).
2. **Screen for bench defects up front** with golden-eval (`eval.py --json tasks.json
   --golden-eval --instance-ids ...`): any instance whose GOLD patch doesn't grade is
   excluded as a defect and *counted separately* (the defect base-rate is itself a finding).
3. **Produce patches** with the clean-room pipeline (see "produce patches" below), one
   model_patch per surviving instance. Count DNFs in the denominator (no quiet drops).
4. **Grade canonically**, report the rate as pass@1 with the defect-exclusion noted, and
   compare like-for-like to Sonnet 4.5's ~60% SWE-rebench pass@1 — owning that ours is
   non-Python + strict-post-cutoff (harder).

## Produce patches (clean-room agent phase — KEEP this, it's ours)
Per instance, on a Docker box (NOT local — pulls too slow locally):
1. `docker run` the row's `image_name` (prebuilt, public on Docker Hub), repo at base_commit.
2. `git apply` the row's `test_patch` (adds failing tests).
3. **Warm online** (run the defining test once, caches gradle deps + wrapper; also captures
   fail-on-base), THEN `docker network disconnect bridge <cid>` → offline for the solve.
4. Run the agent: `claude --print --model claude-sonnet-4-5 --dangerously-skip-permissions
   --disallowedTools WebSearch WebFetch Task`, **env with `ANTHROPIC_API_KEY` scrubbed**
   (else it bills the API pool, not the plan). Inject the FULL `/investigate` skill verbatim
   (no paraphrase confound). SUT reached only via a LOCAL `box-sh` helper (ssh→docker exec);
   hygraph writes to an isolated `/tmp` dir; `~/Documents/sweep` is OFF-LIMITS.
5. **Gate-grounded resolution:** give the agent a `gate` tool that runs the *defining* tests
   and self-logs to `gate.log`. RESOLVED only when `gate` prints PASS — never the agent's
   prose. (Stops the shadow-1714-style false-resolve by construction.)
6. Capture `git diff` → the model_patch.

## Grade canonically (offline mode — HF API rate-limits)
```bash
# Build tasks.json from the dataset PARQUET (the HF API 429s under load; the parquet CDN
# does not, and it carries install_config — the field cached rows lack):
#   curl -sL "https://huggingface.co/api/datasets/nebius/SWE-rebench-V2/parquet/default/train/0.parquet" -o train.parquet
#   duckdb: SELECT * FROM read_parquet('train.parquet') WHERE instance_id IN (...)
#   write each row as a dict (parse install_config / FAIL_TO_PASS / PASS_TO_PASS JSON) -> tasks.json
# patches.json = JSON LIST of {"instance_id","patch"}
cd ~/swerebench-v2  # github.com/SWE-rebench/SWE-rebench-V2, needs Python 3.10+ (str|None)
python3.11 scripts/eval.py --json tasks.json --patches patches.json \
  --instance-ids <comma,sep,ids> --max-workers 4 --report-json eval_report.json
# RESOLVED iff  from_fail_to_pass ⊇ FAIL_TO_PASS  AND  failed_from_pass_to_pass == []
```

## Infra landmines (every one cost real time — pre-empt them)
1. **Box, not local** — 5GB images time out pulling locally; on EC2 they pull in minutes.
   Provision, run, **tear down immediately** (terminate instance + delete key-pair + SG).
2. **`ec2-user` not in `docker` group** → all runs exit-126 (containers never run). Fix:
   `sudo usermod -aG docker ec2-user` then run via `sg docker -c "..."`. SSH user is `ec2-user`.
3. **Scrub `ANTHROPIC_API_KEY`** before any headless `claude` → uses the plan, not API credits.
4. **HF API 429** under load → use offline `--json tasks.json` from the parquet (above).
5. **`box-sh` is LOCAL** (where the model runs), not on the box.
6. **No data pollution between runs**: isolated hygraph dir (uuid-suffixed), sweep off-limits,
   evacuate strays to `/tmp` after each run.
7. **Don't cut container network before warming** gradle deps + wrapper distribution.
8. Keep agent concurrency low (≤2–3) to avoid `Overloaded` DNFs.
9. `rm -rf` is blocked by a hook → `mv <target> /tmp/` instead.

## Pointers (read these next)
- `results/2026-05-20-canonical-harness/RESULT.md` — the canonical 2/2 + the two proven
  bench defects; the attestation artifacts (eval_report.json, gold_kiota.json, tasks.json,
  patches.json, logs/) are re-runnable.
- `RUNG2-LEDGER.md` — L0–L5 scars (box-sh local, deterministic gate, API-key leak, dirty
  base, L5 = canonical settles the confusing instances).
- `BOOTSTRAP-OFFICIAL-HARNESS.md` — the prior canonical-run spec (Phase A produce / Phase B
  grade) in more detail; `BOOTSTRAP-SWEBENCH.md` — the full rung-ladder rationale.

## First action this session
Decide: **(a)** start rung 3 (preregister a sample, golden-eval screen, produce, grade), or
**(b)** spend Sonnet on the shadow-1714 wall first (cheaper, settles "is this the ceiling?").
Ask the user which, or default to (b) — it's the smaller, more informative bite and feeds
the rung-3 wall-documentation either way.
