# Canonical official-harness grade — 4 confusing post-cutoff instances

**Date:** 2026-05-20
**Harness:** SWE-rebench-V2 official `scripts/eval.py` (offline `--json tasks.json` mode; HF API was 429-locked, rows pulled from the dataset parquet CDN with `install_config` intact).
**Driver:** Claude Sonnet 4.5 (cutoff Jul 2025; all instances created Aug–Oct 2025 → contamination-clean by selection), `/investigate` skill injected verbatim, clean-room offline container, gate-grounded resolution.
**Box:** ephemeral EC2 (i-0bdb1e7789a0db2b1), torn down after grade.

## Verdicts

| Instance | Verdict | Detail |
|---|---|---|
| `orchestr7__ktoml-353` | ✅ RESOLVED | exit 0, F2P 918/918, 0 P2P regressions |
| `arkivanov__decompose-916` | ✅ RESOLVED | exit 0, F2P 594/594, 0 P2P regressions |
| `gradleup__shadow-1613` | 🚫 UNSCOREABLE (bench defect) | F2P metadata test IDs embed non-deterministic JVM lambda addresses (`$$Lambda/0x...@hash`) → never string-matchable; metadata also points at `PropertiesFileTransformerTest` while the bug/patch is in `ShadowJar.kt`. PropertiesFileTransformerTest ran clean (26/26). |
| `microsoft__kiota-6835` | 🚫 UNSCOREABLE (bench defect) | Our patch: F2P 1/1 passed, 2 P2P "regressions" (Go/Dart integration tests, unrelated to the C# fix). **Golden-eval proof:** the gold patch itself returns exit 1, F2P 0/1, **1869 P2P regressions**; our 2 fails are a strict subset of gold's. The harness env can't score this instance. |

**Scoreable: 2/2 RESOLVED.** Two of the four "confusing" instances are demonstrably broken benchmark instances, proven by the official harness (one has unmatchable F2P IDs; the other's gold reference solution fails to grade).

## Why this matters

The all-night "confusion" on shadow-1613 and kiota-6835 was **not** the diagnosis method failing — it was benchmark-instance defects. The bespoke grader couldn't distinguish "our fix is wrong" from "the instance is broken." The official harness can: golden-eval shows the canonical solution itself doesn't grade. This retires the "your grader is buggy" critique and is a publishable data-quality finding for the decontaminated-benchmark conversation.

## Attestation (re-runnable)

Artifacts in this dir: `eval_report.json` (our grade), `gold_kiota.json` (golden-eval proof), `tasks.json` (full rows incl. install_config), `patches.json` (the model patches), `logs/` (per-instance test output).

Repro: clone `github.com/SWE-rebench/SWE-rebench-V2`, `python3.11 scripts/eval.py --json tasks.json --patches patches.json --instance-ids <ids> --max-workers 4 --report-json out.json` on a Docker box. RESOLVED iff `from_fail_to_pass ⊇ FAIL_TO_PASS && failed_from_pass_to_pass == []`.
