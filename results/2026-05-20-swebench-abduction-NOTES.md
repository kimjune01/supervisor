# SWE-bench Lite — abductive solve experiment (NOTES / cleanup guide)

## What this is
Testing the abductive diagnosis loop (the `/investigate` reasoning mode) on
SWE-bench Lite instances that **all 28 strong 2025 submissions failed** — the
genuine SOTA-fail tail (headroom). Goal: solve >=1, scored by the real tests.

## Cleanup (everything is here or ephemeral)
- `rm -rf /tmp/swebench-abduction`  ← all artifacts: instance data, cloned repos, venvs
- No Docker images pulled (using venv + pytest directly, not the SWE-bench Docker harness).
  If any `docker` got used later: `docker system prune -af --filter "until=1h"`.
- Nothing written into git repos. The RESULT summary is copied to
  `~/Documents/supervisor/results/` at the end (that's the only thing to keep).

## Files here
- `instances.json` — all 300 SWE-bench Lite instances (from HF datasets-server)
- `unsolved_by_all_strong.json` — the 52 instance IDs unsolved by all 28 strong subs
- `repos/` — cloned target repos at base_commit (large; delete freely)
- `RESULT.md` — the writeup (filled in as solves complete)

## Key finding (data)
- 300 Lite instances; 248 solved by >=1 of 28 strong 2025 submissions.
- **52 unsolved by ALL 28 strong submissions** (sympy 21, django 17, sphinx 4, rest 10).
- 44 of the 52 are pure-Python repos (tractable without compiling C extensions).

## Method (honest)
For each target: clone repo @ base_commit, install in venv, apply the gold
`test_patch` (adds the failing test — this is what a dev has: an issue + a
failing test), run FAIL_TO_PASS → confirm it FAILS (reproduce). Then diagnose
from problem_statement + actual code **without looking at the gold fix patch**,
write a fix, apply, re-run FAIL_TO_PASS + PASS_TO_PASS. Resolved iff FAIL_TO_PASS
passes and PASS_TO_PASS still pass. (Gold fix patch consulted only AFTER, for
comparison — noted per instance.)

## Status
- [in progress] sympy__sympy-12171 (smallest gold patch, 554b)
