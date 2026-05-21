# Round 2 — result + retro (2026-05-20)

Calibration round 2. Prefix = positions 6–10 of the frozen permutation (fresh slice; we do not
re-run round-1's attributed bench defects). **Fan-out architecture:** one ephemeral box per
instance (5 boxes), parallel bootstrap + golden-screen, solves throttled to 3 concurrent local
`claude`, all boxes torn down after grading. Frozen config unchanged from round 1: model
`claude-sonnet-4-5`, skill content sha256 `a2a4808b…` (skill NOT modified this round).

## Outcome
| instance | lang | golden screen | solve (canonical eval.py) |
|---|---|---|---|
| `r-lib__usethis-2142` | R | ✅ valid | ✅ RESOLVED (F2P 1/1, 0 reg) |
| `segmentio__analytics-swift-406` | swift | ✅ valid | ✅ RESOLVED (F2P 89/89, 0 reg) |
| `ferrite-fem__ferrite.jl-1235` | julia | ✅ valid | ✅ RESOLVED (F2P 50/50, 0 reg) |
| `fredrikekre__runic.jl-170` | julia | ✅ valid | ✅ RESOLVED (F2P 27/27, 0 reg) |
| `microsoft__kiota-6947` | csharp | 🚫 bench-defect | not attempted (gold 0/5 F2P, **1868 P2P regressions** — same class as rung-2 kiota-6835) |

**Valid-instance result: 4/4 RESOLVED**, canonically. **Defect rate: 1/5.** New toolchains
**R and Swift proven runnable + solvable** for the first time (rung 2 had only gradle/KMP; round 1
added go/julia). Positions 1–10 of the pool are now burned (10/123).

**Microsoft/kiota is chronically bench-defective:** kiota-6947 here mirrors kiota-6835 (rung 2) —
gold patch returns ~1868 P2P regressions and 0 F2P. Two-for-two on kiota defects. Attributed to
the bench; not massaged (no re-run, no flaky-gold patching).

## Calibration finding #2 — patch hygiene (capture; agent leaves backup detritus)
The swift solve produced a **70 KB** patch: 4 real source fixes (`DeviceToken.swift`,
`Timeline.swift`, `JSON.swift`, `KeyPath.swift`) plus **9 backup files** the agent left behind
(`KeyPath.swift.bak`, `.bak2` … `.bak9`), swept in by `git add -A` at capture.
- **Impact: cosmetic, not fatal.** SPM ignores non-`.swift` extensions, so it still graded
  RESOLVED 89/89. But it pollutes the model_patch and would mislead review / inflate sizes.
- **Generalized invariant:** *the model_patch contains only the fix, never the agent's working
  detritus.* Capture must strip backup/junk files (`*.bak`, `*.bak[0-9]*`, `*.orig`) before
  diffing.
- **Fix (harness):** `capture_patch` now `find … -delete`s those patterns before `git add -A`.
  Motivating instance: `segmentio__analytics-swift-406`.
- Note (skill-side, deferred): the agent *making* `.bak` copies as it edits is itself worth a
  skill nudge later (edit in place / rely on git), but it's low-priority since it didn't affect
  correctness. Logged, not fixed this round (would be a skill modification → ladder reset).

## Ladder bookkeeping
Round 2 modified only the **harness** (capture `.bak` strip), not the `/investigate` skill. The
skill's tally across rounds 1–2 on valid instances is now **7/7 RESOLVED** across six toolchains
(go, kotlin, julia, R, swift; csharp only seen via defects). Operator's call whether the next
round advances to positions 11–15 (fresh) or holds.

## Artifacts (in this dir)
`round2_tasks.json`, `round2_ledger.jsonl`, `round2_patches.jsonl`, `r2grade_*.json`,
`r2_golden_*.json` (screen), `rung3_driver.py` (now with the `.bak`-strip capture fix),
`fanout_round2.py` (the multi-box orchestrator).
