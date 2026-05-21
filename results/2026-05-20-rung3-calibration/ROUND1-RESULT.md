# Round 1 — result + retro (2026-05-20)

Calibration round 1. Prefix = first 5 of the frozen permutation. Box `i-0aa00c1eb3b30c909`
(us-west-2, m7i.xlarge), provisioned → run → **torn down** (instance + key-pair + SG deleted).
Frozen config: model `claude-sonnet-4-5`, `/investigate` skill content sha256
`a2a4808b05c612d3553c17a14a28360285104707d7839b304459643f8efe4e98`.

## Outcome
| instance | lang | golden screen | solve (canonical eval.py) |
|---|---|---|---|
| `kevincianfarini__cardiologist-164` | kotlin | ✅ valid | ✅ RESOLVED (F2P 120/120, 0 P2P reg) |
| `jump-dev__jump.jl-4050` | julia | ✅ valid | ✅ RESOLVED (F2P 108/108, 0 P2P reg) |
| `rook__rook-16165` | go | ✅ valid | ✅ RESOLVED (F2P 2/2, 0 P2P reg) |
| `detekt__detekt-8604` | kotlin | 🚫 bench-defect | not solved (non-deterministic JVM-address F2P IDs) |
| `juliastats__mixedmodels.jl-858` | julia | 🚫 bench-defect | not solved (Aqua.jl F2P names absent from `test_cmd`) |

**Valid-instance result: 3/3 RESOLVED**, canonically (`all_ok: True`), across three toolchains
rung 2 had not all proven (kotlin/julia/go). **Defect base rate: 2/5** (consistent with rung 2).
All 5 are now burned (inspected) per the contamination firewall.

What the agent did, per instance:
- rook: one-line image bump `cephcsi v3.14.1→v3.14.2` (632 B).
- cardiologist: added a 5-field cron-expression parser companion object (10.9 KB).
- jump.jl: extended `Base.promote_shape` for `DenseAxisArray` axis tuples (1.3 KB).

## Calibration finding #1 — HARNESS (fix_target = harness, not skill)
**Patch capture missed agent-*committed* fixes.** The driver captured `git diff HEAD`, but the
agent sometimes `git commit`s its own edits (jump.jl: commit `2ea726da` on top of the
`testpatch` commit). `HEAD` was then the agent's commit → empty diff → a real fix recorded as a
0-byte patch (would grade as a false NOT-RESOLVED).
- **Generalized invariant:** *the model_patch is everything that changed since the recorded
  test-patch commit, whether the agent left it staged, unstaged, or committed.* Capture must
  diff against the recorded base sha, not `HEAD`.
- **Fix:** `setup` records the test-patch commit sha; `capture_patch` runs `git diff <tsha>`
  (plus a `git status`/`log`/`stat` diagnostic so an empty patch is debuggable post-teardown).
- **Motivating instance:** `jump-dev__jump.jl-4050`. Re-ran under the fix → 1.3 KB patch →
  RESOLVED. (rook/cardiologist were unaffected — they left edits unstaged — so the skill's
  result is not tainted by this artifact-extraction bug.)

## Ladder bookkeeping
This round modified the **harness** (capture fix), not the `/investigate` skill — the skill was
untouched and its 3/3-valid result stands. Per the per-skill-version ladder rule a *harness*
modification also resets the rung; but since (a) the bug was pure artifact-extraction, (b) the
two unaffected instances were captured correctly even pre-fix, and (c) jump.jl was re-run and
graded under the fixed driver, the skill's depth-5 result is clean. **Decision for round 2 is
the operator's:** honor the letter (reset to 5, re-run the burned set under the fixed driver —
low new info, 3/3 known) or recognize the skill was untouched and double to 10 (reveal the next
5 fresh). Recommendation: double to 10, since the harness fix doesn't bear on the skill's solve.

## Artifacts (in this dir)
`round1-golden-screen.md`, `golden_report.json`, `r3_eval_report.json`, `round1_patches.json`,
`round1_ledger.jsonl`, `rung3_driver.py` (the fixed driver), `rook__rook-16165_log.txt`.
