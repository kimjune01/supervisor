# BOOTSTRAP — continue rung 3 calibration (fresh session, Sonnet ok)

*Self-contained. A fresh agent runs this cold. Written 2026-05-20 mid-rung-3.
Read this + the 3 pointers at the bottom, then act. The orchestrating agent's model does
NOT matter for contamination — the clean-room SOLVES are always run by headless
`claude-sonnet-4-5` (see below); you're just driving the harness, so Sonnet is fine.*

## One-paragraph premise
Rung 3 is a **practice / calibration** effort: exercise the clean-room `/investigate` pipeline
on real post-cutoff non-Python SWE-rebench-V2 instances to **find and fix faults in the skill +
harness BEFORE the final rung freezes the skill**. It asserts no rate. We only ever publish a
result from a frozen config that beats SOTA on a clean comparable set. Full design:
`results/2026-05-20-rung3-calibration/CALIBRATION-PLAN.md` (READ IT — burn firewall, ladder rule,
counting rules all live there).

## Where we are (2026-05-20)
- **Frozen pool:** 123 clean instances (`created_at > 2025-07-22 AND language != python` in
  `nebius/SWE-rebench-V2`). Seed 20260520. Order + fingerprint in
  `results/2026-05-20-rung3-calibration/calibration-pool.json` → `permutation`.
- **Reveal in doubling prefixes:** R1 = pos 1-5, R2 = pos 6-10, **R3 = pos 11-20 (doubled to 10)**.
- **Done:** R1 (3/3 valid RESOLVED), R2 (4/4 valid RESOLVED), **R3 wave A = pos 11-15 (1/5 valid;
  geoswift RESOLVED 800/800; 4 defects)**. **Skill tally: 8/8 on every valid instance.**
- **Positions 1-15 are BURNED (inspected).** Pos 16-20 are next and still clean until you run them.
- **IMMEDIATE NEXT ACTION: run R3 wave B = positions 16-20** (the second half of the doubled round):
  `symbolics.jl-1613, ktoml-357, forwarddiff.jl-770, partiql-lang-kotlin-1789, mljbase.jl-1023`.

## How to run a wave (the generalized orchestrator)
`/tmp/swebench-abduction/fanout.py` (also copied to the results dir). One ephemeral EC2 box per
instance. Phases — run in order, each observable/resumable; state in `/tmp/swebench-abduction/fanout_<tag>.json`:
```
python3 fanout.py up    <tasks.json> <tag>   # provision N boxes + bootstrap + golden-screen -> records survivors
python3 fanout.py solve <tag>                # rung3_driver.py per survivor, throttle 3 concurrent local claude
python3 fanout.py grade <tag>                # eval.py per survivor box -> verdicts in <tag>_verdicts.json
python3 fanout.py down  <tag>                # terminate all boxes + key + SG (ALWAYS do this when the wave is done)
```
For wave B: first build the tasks file (positions 16-20 already in
`results/2026-05-20-rung3-calibration/round3b_tasks.json`), then
`python3 fanout.py up <abs path>/round3b_tasks.json rd3b` (run in background; it takes ~20-40min:
image pulls + golden-screen). Then `solve rd3b`, `grade rd3b`, `down rd3b`.

## HARD CONSTRAINTS (every one cost real time — do not relitigate)
1. **vCPU quota = 32** in us-west-2. m7i.xlarge = 4 vCPU, so **max ~7 boxes at once** (your 2 prod
   boxes use a little). `--count N` sets min=max=N, so >8 boxes **fails atomically** (IndexError in
   `up`, nothing launches — but key/SG leak; clean with the sweep below). **Run 10-instance rounds as
   two waves of 5.** Round 4 (20) → four waves of 5.
2. **Official harness only.** Grade with SWE-rebench-V2 `scripts/eval.py`. **Golden-eval screens
   defects first** (`up` does this): if the GOLD patch can't grade, it's a bench defect — log it in
   `BENCH-DEFECTS.md`, exclude it, MOVE ON. **Never massage the runner or patch a flaky gold.** DNFs
   and defects are logged, not scored.
3. **Clean-room solves run headless `claude-sonnet-4-5` with `ANTHROPIC_API_KEY` SCRUBBED**
   (`plan_env()` in `rung3_driver.py`) → uses the Max plan, not API credits. The `/investigate` skill
   is injected verbatim from `~/Documents/june.kim/skills/investigate/skill.md` (symlink →
   `~/Documents/sweep/skills/investigate.md`). **Frozen skill content sha256 =
   `a2a4808b05c612d3553c17a14a28360285104707d7839b304459643f8efe4e98`** — record per round; the skill
   has NOT been modified during rung 3 (only the harness has).
4. **Ladder rule:** a `/investigate` SKILL modification resets the rung to 5; a HARNESS-only fix does
   not reset the skill's ladder (rounds 1-2 each fixed harness bugs, skill untouched, tally stands).
   Reveal fresh instances only forward in the permutation; never re-run burned ones for score.
5. **Cost/teardown:** ~$0.20/box-hr, model is $0 (plan). Boxes self-terminate after 3h (watchdog:
   `shutdown -h +180` + `instance-initiated-shutdown-behavior terminate` baked into `fanout.py up`).
   STILL run `fanout.py down <tag>` when a wave finishes. **Always sweep for orphans:**
   `aws ec2 describe-instances --filters "Name=tag:Name,Values=rung3-*" "Name=instance-state-name,Values=running,pending" --region us-west-2 --query "Reservations[].Instances[].InstanceId" --output text`
   and delete stray `rung3-*` key-pairs/SGs. (An orphan probe box leaked once from a tool-call that ran despite a UI rejection — always sweep.)

## Findings so far (the actual deliverable of calibration)
- **2 harness fixes, both already in `rung3_driver.py`:** (#1) patch capture must diff against the
  recorded test-patch commit sha, not `git diff HEAD` (agent sometimes commits its fix → empty patch);
  (#2) strip `*.bak`/`*.orig` agent detritus before diffing (swift left 9 backup files → 70KB patch).
- **Defect rate ~47% (7/15), clustered in the HARD corner:** C# 3/3 defective (kiota×2,
  spectre.console — class C, gold yields ~950-1870 P2P regressions / killed runner), detekt 3/3,
  GradleUp/shadow 2/2 (class A/B — gold runs clean but recorded F2P names never match parsed output:
  non-deterministic JVM identity hashes / names `test_cmd` doesn't emit). Portable lanes (go, R, swift,
  most julia) grade clean. **The bench is least trustworthy exactly where problems are hardest.**
  Full evidence ledger: `results/2026-05-20-rung3-calibration/BENCH-DEFECTS.md`.
- **Emergent thread — "eval for evals":** golden-eval IS a benchmark-validity check the dataset
  doesn't publish. Our defect taxonomy (A: non-deterministic IDs; B: F2P names not in test_cmd; C:
  gold fails to grade) is the spec for a benchmark health-card. Cheap byproduct of finishing the pool.
- **Known wall:** `gradleup__shadow-1714` at **permutation position 49** (3 blind agents missed it in
  rung 2) — the "is this the ceiling?" probe. BUT shadow is 2/2 defective here, so it may itself be
  unscoreable. The deeper risk: **hard VALID instances are scarce**, so the skill may run low on clean
  hard problems before meeting a genuine reasoning wall.

## After wave B
- Write `ROUND3-RESULT.md` (combine waves A+B), update `BENCH-DEFECTS.md` running rate, commit.
- Decide with the operator: continue doubling (Round 4 = positions 21-40, four waves of 5) or stop
  calibrating. Stop criterion: skill climbs a deep-enough/hard-enough prefix UNMODIFIED → it's
  effectively frozen → graduate to the publishable run on the never-revealed tail (NOT SWE-bench Live
  first; the SWE-rebench-V2 clean tail is the apples-to-apples claim — see CALIBRATION-PLAN + chat).
- Reporting bad goldens upstream is low-priority/optional (maintainers likely won't act); the ledger
  is primarily our honest exclusion record. `/file-issue` can batch a report if ever worth it.

## Pointers (read next)
- `results/2026-05-20-rung3-calibration/CALIBRATION-PLAN.md` — the full design (firewall, ladder,
  counting rules, publishable-tail protocol).
- `results/2026-05-20-rung3-calibration/ROUND1-RESULT.md` + `ROUND2-RESULT.md` + `round3a_*` artifacts
  + `BENCH-DEFECTS.md` — what happened + the defect evidence.
- `/tmp/swebench-abduction/fanout.py` + `rung3_driver.py` — the orchestrator + the per-instance driver
  (also copied into the results dir). `rung2_driver.py` is the older single-box version (reference only).
- Memories: `project-swebench-skill-freeze`, `feedback-official-harness-only`,
  `project-swebench-ec2-cost`, `project-swebench-spectacle-run`, `project-swebench-rung-discipline`.

## First action this session
Build/confirm `round3b_tasks.json` exists, then `python3 fanout.py up <abs>/round3b_tasks.json rd3b`
in the background; when survivors are recorded, `solve rd3b` → `grade rd3b` → `down rd3b`; log defects;
commit. Then ask the operator whether to double into Round 4.
