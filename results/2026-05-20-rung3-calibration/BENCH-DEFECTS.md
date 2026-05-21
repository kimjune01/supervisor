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

## Patterns worth flagging in any report
- **microsoft/kiota is chronically defective** (2/2 sampled: 6835, 6947) — both class C with ~1868
  P2P regressions. Suggests a systemic env/test-harness mismatch for that repo, not one-off.
- **Class A (non-deterministic IDs)** appears in JVM repos (shadow, detekt) — F2P extraction is
  capturing `Object.toString()`-style identity hashes that can't be reproduced.

## Evidence artifacts
Per instance: `golden_report.json` / `r2_golden_<id>.json` / `<tag>_golden_<id>.json` in this dir
(carries `from_fail_to_pass`, `failed_from_pass_to_pass`, `exit_code`, `passed_match`) + the
`eval.py --golden-eval` command. Re-run: clone the harness, `eval.py --json <tasks> --golden-eval
--instance-ids <id>`.
