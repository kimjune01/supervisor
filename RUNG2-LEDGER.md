# RUNG 2 — autonomous run ledger

*Running log of the rung-2 batch (bench-resolved rate over post-cutoff instances).
Started 2026-05-20, autonomous while operator AFK. Lessons logged as they happen —
failures are the point. Grading at the SWE-bench bar only (FAIL_TO_PASS pass +
PASS_TO_PASS hold); no correctness gold-plating (it's a benchmark, not a maintainer).*

## Protocol
- Clean model: Sonnet 4.5 (cutoff Jul 2025). Instances created Aug–Oct 2025 → clean.
- Clean room: offline container (network cut), agent web tools off, exec via box-sh.
- Per instance: pull image → apply test_patch → reproduce (F2P fails) → cut net →
  clean Sonnet 4.5 /investigate loop → grade (independent re-run of the gate, F2P pass)
  → rm image. Fan-out k=1 (rung-1: fan-out slower on localized).
- Multi-box parallel; tear down all at end.

## Running tally
(updated as instances complete)

| instance | lang | repro | solved (bench bar) | wall-clock | notes |
|---|---|---|---|---|---|

## Lessons (append-only)

### L0 — design decisions (pre-run)
- Gradle-lane bias: most post-cutoff non-Python instances with fast/proven toolchains
  are Kotlin/gradle (image base kotlin-jdk-21, `./gradlew`, builds offline from warm
  cache — proven in rung 1). Bias the set there to maximize solves-per-plumbing-effort.
  A couple non-gradle (csharp/dart) included as stretch to surface toolchain lessons.
- Gate derivation from test_patch: module = path segment before `/src/`; task = segment
  after `src/` (`test`→`test`, `functionalTest`→`functionalTest`); class fqcn from
  package+filename. Pre-derive (robust) rather than parse agent output.
- Anti-test-gaming: re-apply test_patch over any agent edits before grading, so the
  agent can't weaken the failing test.

### L1 — box-sh must be LOCAL, not on the box (shadow-1703, run 1 FAILED)
First validation run: agent returned NOT-RESOLVED claiming "the container isn't set up."
Cause: the driver wrote `/tmp/box-sh` *on the EC2 box*, but the agent runs *locally* — so
it had no helper, used its local Read/Bash, wandered into `/tmp/swebench-abduction`, found
the driver script itself, and concluded the env wasn't provisioned. Fix: write a LOCAL
per-box helper (`/tmp/box-sh-<iid>`) that ssh→docker-exec's into that box's container, and
run the agent in a clean empty cwd so it can't discover the driver. Lesson: the model-side
tool surface (local) and the SUT (remote container) must be bridged by a helper that lives
where the *model* runs. Cost: one ~6min wasted run.

### L2 — grade on a DETERMINISTIC derived gate, not the agent's saved command (shadow-1703 run 2)
Run 2 (box-sh fixed): agent operated in-container, fixed, claimed RESOLVED, saved its gate
to `/tmp/gate_cmd.sh` — but the saved command was malformed (`./gradlew :functionalTest
--tests "*MinimizeTest*" --no-configuration-cache` → BUILD FAILED in 1s). The agent's
working command and its saved command diverged; globs/`:task` forms are fragile. Fix:
grade with a gate derived from the test_patch path + class (module = before `/src/`, task
= segment after `src/`, `commonTest`→`jvmTest` for KMP, fqcn from package+filename) →
`./gradlew [:mod:]task --tests "FQCN" --offline` (proven rung-1 form). Never trust the
agent's self-reported gate for scoring; keep it only as a fallback for non-gradle repos.

### Batch launched (4 boxes, 2 instances each, parallel)
A: shadow-1703, detekt-8605 | B: shadow-1613, shadow-1714 | C: ktoml-353, decompose-916 (KMP)
| D: kiota-6835 (C#), dart-http-1803 (Dart). Gradle lane expected to mostly work; KMP
`jvmTest` derivation and the C#/Dart toolchains are the open risks. Awaiting results.

### L3 — THE WALL: credit exhaustion voided the whole batch (run aborted)
All 8 agent outputs were 26 bytes: `"Credit balance is too low"`. **Zero real diagnoses
ran** — the batch is void; nothing about the method was tested. Cause: the headless
`claude --print` agents burn an API credit pool that is *separate* from the Max-plan
Sonnet tokens ("many sonnet tokens" ≠ headless-API credits), and 4 parallel + sequential
agents drained it. This is an external blocker, not a code bug — can't fix from here.
Decision: stopped (did not retry into the wall), fixed the driver bugs found, tore down
all 4 boxes (no agents = no reason to bill). **Resume when credits are available.**

### Bugs fixed so the re-run is clean (driver now correct)
- L1: local per-box `box-sh` helper.
- L2: deterministic derived gate, not the agent's saved command.
- L3-fix: `derive_gate` single-module bug — guarded on `"/src/"` (leading slash) which
  excluded single-module repos whose paths start with `"src/"` (shadow, ktoml). Now
  checks `"src" in path.split("/")`. (This is why shadow/ktoml graded as "non-gradle".)

### Rate so far: 0 attempted (all void on credits). NOT a method result — an infra wall.
Open risks still untested for the re-run: KMP `jvmTest` derivation (ktoml/decompose),
gradle-wrapper needing network on some images (decompose's wrapper tried to download the
gradle distribution and failed offline — may need network during setup, only cut it for
the solve), and C#/Dart gate derivation (kiota/dart — derive returns None by design).

### L4 — the credit wall was self-inflicted: headless leaked ANTHROPIC_API_KEY
The "credit balance too low" was NOT a real plan-token shortage. `claude` (Claude Code)
prefers `ANTHROPIC_API_KEY` over the subscription login when the env var is set, so every
headless `claude --print` billed the pay-per-token API pool (depleted) instead of the Max
plan. The rung-1 *rigid* loop scrubbed the key (`env_nokey()`) and used the plan fine; the
rung-2 driver (and the freeform/bench/bug-hunt runs launched via raw Bash) inherited the
env WITH the key → API billing → drained over the session. **Fix:** `run_agent` now runs
`claude` with `ANTHROPIC_API_KEY` scrubbed (`plan_env()`) → uses the subscription's plentiful
Sonnet tokens. Verified: `env -u ANTHROPIC_API_KEY claude --print` returns normally. The
wall dissolves; re-running on the plan.

## How to resume (when credits are back / now, on the plan)
1. Confirm headless credits available (`echo hi | claude --print --model claude-sonnet-4-5`).
2. Consider serial, not 4-way parallel, to avoid burning the pool in a burst — or a small
   concurrency (2). Throughput is secondary to not hitting the wall mid-batch.
3. Re-provision boxes, `python3 /tmp/swebench-abduction/rung2_driver.py <box.env> <ids...>`
   (driver + instance metadata cached in `/tmp/swebench-abduction/`).
4. For decompose/KMP: don't cut container network until AFTER the first successful build
   (so the gradle wrapper can fetch its distribution), then go offline for the clean solve.

## L5 — canonical harness settles the "confusing" instances (2026-05-20)
Ran the official SWE-rebench-V2 `scripts/eval.py` on the 4 confusing instances (offline
`--json` mode; HF API 429-locked, so rows pulled from the dataset **parquet CDN** which
carries `install_config` — the field the cached rows lacked). Box gotchas paid again:
`ec2-user` not in the `docker` group → first run was all exit-126 (containers never ran);
`usermod -aG docker` + `sg docker -c` fixed it.

**Result: 2/2 of the *scoreable* instances RESOLVED** (ktoml-353 918/918, decompose-916
594/594). The other two are **benchmark defects, proven canonically:**
- `shadow-1613`: F2P test IDs embed JVM lambda addresses (`$$Lambda/0x..@hash`) → never
  matchable; metadata names the wrong test class. **This overturns my earlier hand-argued
  "6/8" dirty-base correction** — the bespoke grader was guessing; the instance is unscoreable.
- `kiota-6835`: **golden-eval is the clincher** — the gold reference patch returns exit 1,
  F2P 0/1, 1869 P2P regressions. Our 2 "regressions" are a strict subset of gold's. The
  harness env can't grade this instance; our patch actually beat gold on it.

**Lesson:** retire all hand-rolled grading. When an instance looks "confusing," run
golden-eval — if gold doesn't grade, it's a bench defect, not a method failure. Artifacts +
write-up in `results/2026-05-20-canonical-harness/`.
