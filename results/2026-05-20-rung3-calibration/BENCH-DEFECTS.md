# SWE-rebench-V2 bench defects — running ledger

Golden-eval-proven defects only: the **gold reference patch itself fails to grade**, so no
solution can score RESOLVED. Each is re-runnable evidence, ready to report upstream
(`github.com/SWE-rebench/SWE-rebench-V2` issues / `nebius/SWE-rebench-V2` HF Community tab) via
`/file-issue` if/when worth it. We attribute and exclude these; we never massage the runner or
patch a flaky gold (see [[feedback-official-harness-only]]).

*(Skepticism noted that maintainers may not act — this list stands regardless, as our honest
exclusion record / denominator for any published rate, and as a data-quality finding about
auto-mined benchmarks.)*

## Defect classes
- **A — non-deterministic F2P IDs:** test names embed runtime addresses → never string-matchable.
- **B — F2P names absent from `test_cmd`:** metadata grades against tests the configured command
  never runs.
- **C — gold patch fails to grade:** the reference solution itself yields F2P misses / P2P regressions.

## Ledger
| instance | lang | class | golden-eval evidence | found |
|---|---|---|---|---|
| `gradleup__shadow-1613` | kotlin | A | F2P IDs embed `$$Lambda/0x..@hash`; metadata names wrong test class | rung 2 (canonical) |
| `microsoft__kiota-6835` | csharp | C | gold patch exit 1, F2P 0/1, **1869 P2P regressions** | rung 2 (canonical) |
| `detekt__detekt-8604` | kotlin | A | gold 5442/5444 F2P; 2 missing IDs embed `BindingContext$1@217d67f` (JVM addresses) | rung 3 R1 |
| `juliastats__mixedmodels.jl-858` | julia | B | F2P names `Piracy`/`Persistent tasks`/`Compare Project.toml` (Aqua.jl) never run under `test_cmd`; gold 0/5 | rung 3 R1 |
| `microsoft__kiota-6947` | csharp | C | gold 0/5 F2P, **1868 P2P regressions** (same as kiota-6835) | rung 3 R2 |
| `spectreconsole__spectre.console-1942` | csharp | C | gold exit **145** (runner killed), 0/495 F2P, **952 P2P regressions** | rung 3 R3a |
| `gradleup__shadow-1596` | kotlin | A/B | gold exit 0, reg 0, but 0/4 F2P — recorded F2P names never matched in parsed output (JVM) | rung 3 R3a |
| `detekt__detekt-8787` | kotlin | A/B | gold exit 0, reg 0, F2P names unmatched (full-suite ran clean) | rung 3 R3a |
| `detekt__detekt-8588` | kotlin | A/B | gold exit 0, reg 0, F2P names unmatched | rung 3 R3a |

## Patterns worth flagging in any report (systemic, not one-off)
- **C# is 3/3 defective** (kiota-6835, kiota-6947, spectre.console-1942) — all class C, gold patch
  yields mass P2P regressions (~950–1870) and/or a killed runner (exit 145). Strongly suggests a
  systemic dotnet test-runner / log-parser failure in the C# lane, not per-instance bad luck.
- **detekt is 3/3 defective** (8604, 8787, 8588) and **GradleUp/shadow 2/2** (1613, 1596) — the
  JVM/kotlin "meaty" repos. Class A/B: gold runs clean (exit 0, 0 regressions) but the recorded
  `FAIL_TO_PASS` names never match the parsed test output (non-deterministic identity IDs and/or
  names the `test_cmd` doesn't emit).
- **The defects cluster in exactly the hard corner** (detekt, shadow, C#). The easy/portable
  toolchains (go, R, swift, most julia) grade cleanly. So the bench is *least* trustworthy
  precisely where the problems are hardest — the instances most worth testing reasoning on are
  disproportionately the unscoreable ones. This is the load-bearing finding for any "eval for
  evals" writeup.
- **Running defect rate: 7/15 (~47%) once R3a is counted** (R1 2/5, R2 1/5, R3a 4/5).

## Evidence artifacts
Per instance: `golden_report.json` / `r2_golden_<id>.json` / `<tag>_golden_<id>.json` in this dir
(carries `from_fail_to_pass`, `failed_from_pass_to_pass`, `exit_code`, `passed_match`) + the
`eval.py --golden-eval` command. Re-run: clone the harness, `eval.py --json <tasks> --golden-eval
--instance-ids <id>`.
