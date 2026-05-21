# Round 1 — golden-eval defect screen (2026-05-20)

Box: `i-0aa00c1eb3b30c909` (us-west-2). Harness: SWE-rebench-V2 `eval.py --golden-eval`,
`--json round1_tasks.json --max-workers 3`. Report: `golden_report.json`.
**All 5 are now burned (inspected) per the contamination firewall.**

| instance | lang | verdict | detail |
|---|---|---|---|
| `kevincianfarini__cardiologist-164` | kotlin | ✅ GOLD-GRADES | passed_match, F2P 120/120, 0 P2P reg |
| `jump-dev__jump.jl-4050` | julia | ✅ GOLD-GRADES | passed_match, F2P 108/108, 0 P2P reg (exit 1 but parser extracts passes — julia Pkg.test returns nonzero normally) |
| `rook__rook-16165` | go | ✅ GOLD-GRADES | passed_match, F2P 2/2, 0 P2P reg |
| `detekt__detekt-8604` | kotlin | 🚫 BENCH-DEFECT | gold passes 5442/5444; the 2 missing F2P IDs embed non-deterministic JVM object addresses (`BindingContext$1@217d67f`) → unmatchable. Same class as shadow-1613. |
| `juliastats__mixedmodels.jl-858` | julia | 🚫 BENCH-DEFECT | F2P names (`Piracy`, `Persistent tasks`, `Compare Project.toml`) are Aqua.jl testset names that never appear in the configured `test_cmd` run → gold can't grade (0/5). Metadata/config mismatch. |

**Defect base rate this draw: 2/5.** Consistent with rung 2 (SWE-rebench-V2 has a real defect
base rate; golden-eval is the arbiter). Bench-defects are harness-suitability signal, not
skill-calibration signal — they do not enter the solve phase.

**Proceed to clean-room solve on the 3 valid instances** (kotlin / julia / go) — a clean
toolchain spread for the first calibration pass. Frozen config: model `claude-sonnet-4-5`,
skill content sha256 `a2a4808b05c612d3553c17a14a28360285104707d7839b304459643f8efe4e98`.
