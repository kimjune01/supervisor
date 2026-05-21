# Round 4a — result + retro (2026-05-21)

Practice rung. Positions 22/24/25/26/29 of the frozen permutation. Positions 21/23/27/28
were peeked-and-skipped (known-defective repos: detekt × 2 at 21/23, shadow at 27/28).
**Fan-out architecture:** one ephemeral m7i.xlarge per instance, bootstrap + golden-screen,
solves throttled to 3 concurrent, all boxes torn down after grading. Frozen config: model
`claude-sonnet-4-5`, skill sha256
`e8c35338b8863c3a442ebfa074eba90a7be906a7ec22a3c02b0542e97bee4a5c`
(enumerate-before-applying rule added, go-with-the-flow rule removed — first rung with
patched skill).

## Outcome

| instance | pos | lang | golden screen | agent claim | solve (canonical eval.py) | wall_s |
|---|---|---|---|---|---|---|
| `dart-lang__pub-dev-8884` | 24 | dart | 🚫 bench-defect | not attempted | — | — |
| `pilosus__pip-license-checker-156` | 25 | clojure | ✅ valid | ✅ RESOLVED | ✅ RESOLVED (F2P 1/1, reg=0) | 177 |
| `effekt-lang__effekt-1101` | 26 | scala | ✅ valid | ✅ RESOLVED | ✅ RESOLVED (F2P 1/1, reg=0) | 576 |
| `juliasymbolics__symbolics.jl-1639` | 29 | julia | ✅ valid | ✅ RESOLVED | ✅ RESOLVED (F2P 2/2, reg=0) | 644 |
| `dart-lang__pana-1480` | 22 | dart | ✅ valid | ❌ NOT-RESOLVED | ❌ NOT-RESOLVED (F2P 0/10, reg=391) | 1429 |

**rd4a valid-instance result: 3/4 RESOLVED.** Defect rate: 1/5.

## Failure analysis

### pana-1480 — model-wrong-implementation: async propagation cascade

The agent correctly diagnosed the root cause: `updatePassthroughOptions` in
`lib/src/analysis_options.dart` needed to (a) accept a `keepInclude` parameter and
(b) preserve the `include` directive from the original analysis_options.yaml when
`keepInclude=true`. It implemented the `keepInclude` logic correctly and passed 9/10
FAIL_TO_PASS tests.

The failure: to resolve `package:` URIs for extracting transitive formatter settings,
the agent made `updatePassthroughOptions` async. In Dart, async is viral — every
caller must `await` the function, and callers of callers must also be async. The agent
updated only one caller (`sdk_env.dart`) and the test file, leaving all other callers
synchronous. The grader saw 391 P2P regressions from the broken callers.

The agent itself reported NOT-RESOLVED (correctly, knowing 1/10 tests remained) before
teardown — the 391 regression story was in the official grade, not the agent transcript.

**Generalized invariant:** *In Dart (and any language where async is viral), making a
function async requires updating ALL callers transitively. Prefer sync refactors when
the async work can be pushed out-of-band (e.g., precompute the resolved URI map before
calling the function, pass it as a parameter instead of resolving inside).*

**Contributing factor (Dart specifics):** The agent was running the Dart toolchain
offline after network cut. Dart's package URI resolution requires network access to
resolve `package:` paths for transitive dependencies. The offline constraint forced the
agent toward an async resolution approach rather than a precomputed map. This is a
valid harness-class contributing factor (not the primary cause, but it narrowed the
solution space).

**Failure class:** `model-wrong-implementation`. No harness contribution at the patch
level (the approach was wrong, not blocked by tooling).

## Bench defect — pub-dev-8884 (class B, new)

`dart-lang__pub-dev-8884`: golden-eval `passed_match=False`, exit 1, 0 P2P regressions.
The 5 F2P test names (`404 page link to package page`, `Adjust like counts no need to
change like counts #1`, `pub.dev importer tests retry`, etc.) are integration/e2e tests
that the standard `test_cmd` does not run — they require a live pub.dev service or a
specific test target flag not in the configured command. Added to BENCH-DEFECTS.md.

## Ladder bookkeeping

- **Skill signal:** pana is `model-wrong-implementation` (async-propagation). The
  enumerate-before-applying rule is not implicated — this is a different failure mode.
  No skill modification needed from this round.
- **No ladder reset** (skill unchanged this round; the new sha was from R3b→rd4a transition).
- **Harness note:** offline Dart `package:` URI resolution is a marginal contributing
  factor for pana. Not proposing a specific harness fix (the primary cause is a wrong
  repair strategy, not a tooling block).
- **Decision:** 3/4 on a practice rung is informative. The enumerate-before-applying
  rule did not cause any failure this round; the new failure mode (async propagation) is
  captured as a generalized invariant above. Ready to proceed to SWE-bench Verified
  leaderboard track.

## Defect rate running total

| round | valid | RESOLVED | defects/total | defect rate |
|---|---|---|---|---|
| R1 | 3/5 | 3/3 | 2/5 | 40% |
| R2 | 4/5 | 4/4 | 1/5 | 20% |
| R3a | 1/5 | 1/1 | 4/5 | 80% |
| R3b | 4/5 | 1/4 | 1/5 | 20% |
| **R3 total** | **5/10** | **2/5** | **5/10** | **50%** |
| rd4a | 4/5 | 3/4 | 1/5 | 20% |
| **cumulative** | **16/25** | **12/16** | **9/25** | **36%** |

## Cumulative skill tally

| round | valid RESOLVED |
|---|---|
| R1 | 3/3 |
| R2 | 4/4 |
| R3 | 2/5 |
| rd4a | 3/4 |
| **total** | **12/16 = 75%** |

## Artifacts

`rd4a_verdicts.json`, `rd4a_golden_*.json`, `rd4a_drv_*.log`,
`rung3_results_rd4abox_*.jsonl`, `r3_out_*.txt`, `r3_patch_*.diff`,
`rd4a_grade_*.json`, `fanout_rd4a_grade.log`, `fanout_rd4a_up.log`,
`fanout_rd4a_solve.log` — all in `results/2026-05-20-rung3-calibration/`.
