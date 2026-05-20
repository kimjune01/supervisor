# BOOTSTRAP — beat SWE-bench Lite with the abductive diagnosis engine

*Self-contained spec. A fresh agent should be able to continue from this file alone.*

## ⚠️ CONTAMINATION RISK — read this first
SWE-bench Lite instances are **old public GitHub PRs** (sympy-12171 is from 2017),
almost certainly **in the training data** of Opus, Sonnet, and the SOTA
submissions. So "solving" one — especially producing a fix **byte-identical to the
gold patch** — may be **memorized recall, not diagnosis.** This is the #1 confound,
bigger than model-strength.
- It directly undercuts the sympy-12171 result: a 2017 fix, reproduced exactly,
  is what recall looks like. Treat that result as **suspect** until contamination
  is controlled.
- Paradox to keep in mind: the 28 SOTA agents likely had it in training too and
  *still failed* — probably the issue's *wrong suggested fix* derails recall inside
  an agent loop. So contamination muddies BOTH the failures and the solves.
- **The only clean test: POST-CUTOFF instances** — bugs/PRs created *after* the
  model's training cutoff, so the fix cannot be memorized. Filter instances by
  `created_at` > model cutoff. Concrete sources (see Roadmap §0 for the ladder):
  - **SWE-rebench (Nebius)** — best decontaminated source. Continuously updated,
    contamination tracked against model release dates. V2 = 32k executable tasks,
    20 langs, with `created_at`/`FAIL_TO_PASS`/`PASS_TO_PASS`/`image_name`.
    `nebius/SWE-rebench-V2` on HF.
  - **SWE-bench-Live (Microsoft fork)** — `full` split, but the public HF viewer
    tops out at `created_at` = **2025-08-30**. NOT clean for any model with a
    later cutoff. If used, filter `created_at > cutoff + 30d`.
  - For extra rigor: require no browsing during solve; exclude repos known to be
    in post-training eval corpora.
  - OpenAI (Feb 2026) stopped reporting SWE-bench Verified — found ≥59.4% flawed
    tests in an audited subset, all frontier models could reproduce some gold
    patches — and now recommends **SWE-bench Pro** (Scale; 731 public instances).
- Weaker signals while you lack post-cutoff data: (a) the **trajectory** — does the
  model genuinely perturb/inspect and reason, or emit the gold fix immediately
  (recall smell)? (b) solve with the issue text **withheld** — if it still nails the
  exact fix from the repo alone, that's recall.
**Any "we beat SOTA" claim is void without post-cutoff instances.**

## Mission
Build a **cheap, autonomous, self-improving diagnosis engine** that solves
SWE-bench Lite instances the SOTA models fail — at a fraction of the cost, with
auditable provenance. Beat the hard tail, not the leaderboard average.

## The thesis (why this should work)
Supplement an expert system; resolve its residue via LLM calls; encode recurring
structure so cost falls over time. The key scoping result we earned the hard way:
**abduction's home is DIAGNOSIS on a perturbable system, NOT classification.**
- Classification (Banking77): a statistical fitter (TF-IDF) wins; abduction was
  marginal. Three negatives. Wrong domain.
- Diagnosis (SWE-bench): you must infer a hidden cause by perturbing — no
  statistical shortcut ("you can't TF-IDF a root cause"). Abduction's home.

**The loop** (this is the whole method): `reproduce` (run the failing test) →
`perturb-and-inspect` (run code to OBSERVE the system's actual structure — do not
guess) → `read the local convention` (how does the codebase handle similar cases?)
→ `fix by mirroring it` → `re-test` → on fail, the failure names the next
hypothesis. A hypothesis-graph (SMEM) records provenance; recurring root-cause
patterns get encoded so later instances are cheaper (the learning curve).

## State of evidence (as of 2026-05-20)
- **Headroom found:** of 300 SWE-bench Lite instances, **52 are unsolved by ALL
  28 strong 2025 submissions** (sympy 21, django 17, sphinx 4, rest 10; 44/52
  pure-Python). List: `/tmp/swebench-abduction/unsolved_by_all_strong.json`.
- **First solve:** `sympy__sympy-12171` (SOTA-failed by all 28) — RESOLVED, fix
  **byte-identical to the gold patch**, 9/9 tests pass, re-verified clean.
  Why SOTA fails it: the issue text *suggests a wrong fix*; the win needs
  `inspect Derivative(..).args` (counts pre-expanded) + mirror the `Hold[Sum[]]`
  convention. **CAVEAT: solved by Opus interactively — confounds model strength;
  the cheap/autonomous version is the open question.**
- **Disentangling run — TIMED OUT, no verdict yet.** The autonomous **Sonnet**
  loop (`/tmp/swebench-abduction/swe_solve.py`) crashed: a single `claude --print
  --model claude-sonnet-4-6` call exceeded the 150s timeout (CLI cold-start +
  inference + big prompt). RETRY with `timeout=300+` per call, and/or trim the
  prompt. Still pending — and even if it solves, contamination (above) means it
  may be recall; the disentangling it buys is only model-strength + ablation, NOT
  contamination.

## Infra — concrete commands

**Instances (HF datasets-server, works here):**
```python
import requests
for off in (0,100,200):
    r=requests.get("https://datasets-server.huggingface.co/rows",
      params={"dataset":"princeton-nlp/SWE-bench_Lite","config":"default","split":"test","offset":off,"length":100},timeout=40)
    # row fields: problem_statement, base_commit, patch[GOLD-don't peek pre-solve],
    #   test_patch, FAIL_TO_PASS, PASS_TO_PASS, environment_setup_commit, version, repo
```
Cached at `/tmp/swebench-abduction/instances.json`.

**Find SOTA-failed instances (per-model results via gh):**
```
gh api repos/swe-bench/experiments/contents/evaluation/lite            # list submissions
gh api repos/swe-bench/experiments/contents/evaluation/lite/<sub>/results/results.json  # base64 -> {"resolved":[...]}
```
Aggregate the 2025-dated subs; instances in NO "resolved" list = unsolved-by-all-strong.

**Eval recipe (when the base commit IS fetchable):**
```
git clone https://github.com/<repo>; git checkout <base_commit>
uv venv --python 3.9 .venv          # old sympy needs 3.9; pick per instance
uv pip install --python .venv/bin/python mpmath -e .
git apply <test_patch>              # adds the failing test (what a dev has)
.venv/bin/python -m pytest <FAIL_TO_PASS> <PASS_TO_PASS> -q   # resolved iff all pass
```

**THE WALL (read this):** many instances' base-commit *file-trees* are NOT
fetchable from github by SHA (partial clone / GC'd refs — `git checkout` gives
"unable to read tree", `git fetch <sha>` gives "not our ref"). sympy-12171's
commit was fetchable; sympy-13437's was not. **To run a real RATE, use the
SWE-bench Docker harness** (pinned per-instance env). Docker IS available here
(28.5.2). See https://github.com/swe-bench/SWE-bench (harness + `swebench` pip pkg,
`python -m swebench.harness.run_evaluation`).

**Compute — a cheap CPU box (e.g. Hetzner) is one option, NOT a settled
recommendation.** The harness itself is CPU-only and disk-hungry (per-instance
Docker images, 120GB+ for a Lite slice), so a rented CCX/CPX or auction dedicated
box (~€0.02–0.05/hr up to a few €/day) has the cores + disk + bandwidth the laptop
lacks. Open questions before relying on it:
- **ToS risk (the real blocker):** running your Claude *plan* (Pro/Max) creds on a
  rented server for automated, headless harness calls likely violates Anthropic's
  terms (plans are for interactive personal use, not server/automated workloads).
  Don't do this. If you go remote, use a metered **API key** for the model calls
  and keep the harness (which needs no model) on whatever box is convenient.
- Hetzner's own AUP also restricts some automated workloads — check before scaling.
So: the box solves the *disk/CPU* problem for the harness; it does NOT license
pointing plan creds at it. Decide the model-call path (API key vs local) first.

## The autonomous loop (prototype: /tmp/swebench-abduction/swe_solve.py)
A model (Sonnet for cost, Opus for hard cases) gets the issue + failing test, and
emits ONE JSON action/turn: `inspect` (run python to observe), `read` (a file),
`patch` (search/replace; tests auto-run; failure fed back). Loop to pass/budget.
Extend it: add the hypothesis-graph (`supervisor/hygraph.py`) to record each
`(observation -> root cause -> fix)`; on a new instance, check `already_tried`
and reuse encoded kill-conditions/fix-templates so later solves get cheaper.

## Controls — DO NOT fool yourself
0. **CONTAMINATION (the gate):** old instances may be memorized. No "beat SOTA"
   claim is valid without **post-cutoff instances**. This dominates all others.
1. **Model strength vs method:** always run cheap (Sonnet/Haiku) AND strong (Opus).
   A cheap model solving a SOTA-fail is the real signal (it can't be raw power).
2. **Ablation:** with-loop (perturb→inspect→mirror) vs without (just "fix this").
   Does the structure help, or is it the model?
3. **Trajectory > verdict:** did it actually PERTURB (inspect/read) or pattern-match
   the issue's suggested fix (the way the failed SOTA agents do)? Read the transcript.
4. **Real baseline, not strawman.** The competitor is the strong submissions, not
   a weak one.
5. **n=1 is not a rate.** Need many instances via the Docker harness.
6. **Honesty: publish all** — record negatives (see `results/*NEGATIVE*`). Diagnose
   without the gold *fix* patch; consult it only after, for comparison.

## Roadmap (the quest)
0. **POST-CUTOFF instances first** — without them, nothing below is a real claim.
   This is the gate on the entire quest. [HARD GATE] Cheapest→most-definitive ladder
   (each rung names the claim it licenses — don't overclaim a lower rung):

   | Rung | Setup | Effort | Claim licensed |
   |---|---|---|---|
   | 0 | Static patch review on Lite fails, no exec | Hours | "patch looks plausible" — no rate |
   | 1 | Host checkout on *fetchable* Lite/Verified, run targeted tests | 0.5–2d | directional smoke signal, selected tasks |
   | 2 | Host checkout on post-cutoff Live/rebench slice | 1–3d | some uncontaminated traction (env-biased) |
   | 3 | Docker harness, small Lite subset | ~1d, 120GB+ disk | legacy SWE-bench mechanics, small slice |
   | 4 | Docker harness, Verified (500) | days | legacy Verified score — contamination dominates |
   | 5 | Docker harness, SWE-bench-Live `full`, filtered `created_at>cutoff` | days–wks | **public post-cutoff resolution rate** |
   | 6 | SWE-rebench monthly/V2 slice, filtered by `created_at` | days–wks | decontaminated public monthly signal |
   | 7 | SWE-bench Pro public + held-out/commercial | highest | most defensible frontier claim |

   Plan: run rungs 1–2 now for cheap triage; reserve real claims for rung 5 or 6.
   The sympy-12171 Lite solve is a **legacy diagnostic only** until the same engine
   is validated on post-cutoff SWE-rebench/Live.
1. **Confirm cheap-autonomous** — Sonnet loop solves >=1 SOTA-fail (run TIMED OUT,
   retry with timeout>=300s). [gate]
2. **Docker harness** — clear the commit-wall; run a real RATE on the 52 (and on
   SWE-bench Lite Verified). Report: solved / attempted, with the controls above.
3. **Encode + the learning curve** — wire the hygraph so recurring root-cause
   patterns are encoded; measure Sonnet-calls-per-solve FALLING across a stream of
   instances (cost-decrease = the structural win).
4. **Endgame** — cheap autonomous self-improving diagnosis engine beating SOTA on
   the hard tail at a fraction of cost, every fix git-blameable. Then: point the
   same engine at any engineered system (incl. a classifier's own code).

## Repo
`github.com/kimjune01/supervisor` (AGPL). Harness: `supervisor/core.py`
(`supervise` loop, blinded replay), `hygraph.py` (SMEM + provenance + four-bin
verdicts), `bench.py`/`cascade.py`/`online.py` (Banking77 — the wrong-domain
detour, kept for the negative results), `results/` (all runs, incl. the
SWE-bench solve + the negatives). Read `docs/FINDINGS.md` for the full thesis +
the 38 findings behind all this.

## Cleanup
SWE-bench artifacts live in `/tmp/swebench-abduction` (`rm -rf` to clean; no
Docker images pulled yet — if you use the harness, `docker system prune -af
--filter "until=24h"` after).
