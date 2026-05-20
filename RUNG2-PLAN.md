# RUNG 2 — a RATE over post-cutoff instances

*Resumable plan. Picks up from the rung-1 results (2026-05-20). Read this + the
`results/2026-05-20-rung1-*` docs to continue cold.*

## Why rung 2 (the info-gain case)
Rung 1 is informative and now ~dry for single instances: clean post-cutoff solves on
detekt-8803 (one-liner-ish) and shadow-1611 (meaty hidden-cause recursion), plus a
harness comparison (rigid vs freeform vs fan-out) and a level-3 bug-hunt showing
tests-pass ≠ correct. What rung 1 CANNOT give is a **rate**: does the clean-model
/investigate loop solve at some fraction across *many* post-cutoff instances, not just
hand-picked ones? That's the new information rung 2 buys. (Climb criterion satisfied:
current rung dry + next gains new info.)

## Claim target
"Clean model (Sonnet 4.5, cutoff Jul 2025) running the /investigate loop in a clean
room resolves N/M post-cutoff instances, harness-graded." A real resolved-rate, the
thing the SWE-rebench leaderboard compares — and the first thing worth broadcasting.

## Instance set (selection = the one filter that does the work)
- Source: `nebius/SWE-rebench-V2` parquet, `created_at` in **(2025-08-01, 2025-10-31]**
  (post-dates Sonnet 4.5's Jul-2025 cutoff → clean by construction). Mainstream langs
  top out 2025-07, so this window is **non-Python** (kotlin/scala/swift/csharp/dart/julia).
- Filter for tractability/economy-of-research: small/fast repos, has `image_name`
  (`swerebenchv2/...`), gold patch 1–2 files & a few hunks (real logic, not typo/refactor).
- Start from the shortlist already surfaced (see chat 2026-05-20): GradleUp/shadow has
  several (1611 done, 1703/1714/1731/1787/1613 remain), plus orchestr7/ktoml-353,
  arkivanov/decompose-916, microsoft/kiota-6835/7021, dart-lang/http-1803.
- **Target M ≈ 8–12** for a first rate. Stratify: don't over-weight one repo (shadow
  has many; cap ~3 to avoid single-repo bias).

## Protocol (proven in rung 1 — reuse verbatim)
- Ephemeral EC2 (m7i.xlarge, 80GB) — but images are ~5GB each, so **pull→run→grade→`docker rm`/`rmi` per instance** (don't hold many at once), OR provision bigger disk (200GB) and/or run a few parallel containers (token headroom allows parallel solves; each its own container = no `/shadow` collision).
- Per instance: pull image → apply `test_patch` → confirm reproduce (F2P fails) → cut
  container network (offline clean room) → run clean Sonnet 4.5 /investigate loop via
  `box-sh` (web tools disabled) → grade on the offline gate → record resolved/attempted.
- ToS-safe: model local on the plan, exec over SSH into the offline container.
- Fan-out: default k=1 (rung-1 showed fan-out ~2x slower on localized bugs); only fan
  out (into `clean-sonnet` pinned subagents) on instances that look ambiguous.

## The hard part (why run it ATTENTIVELY, not blind-overnight)
Per-instance plumbing varies and breaks in repo-specific ways: the **gate command**
differs per repo (gradle `test` vs `functionalTest` vs sbt vs dotnet; module + test
selector derived from `test_patch`), JDK/toolchain versions, offline-build quirks. An
unattended batch will half-fail on env/gate issues and return low-information noise —
which violates the climb criterion (only spend when certain to gain info). So: run it
with attention, fixing per-repo gate derivation as it goes, like rung 1. Budget a
focused session, not a fire-and-forget.

## Metrics + controls (report these)
- **Rate**: resolved / attempted, with per-instance verdict + the gate command used.
- Controls: clean model (cutoff < created_at, asserted), offline container, web off,
  diff-not-byte-identical-to-gold noted per solve (recall check), trajectory (did it
  perturb or one-shot).
- Cost: Sonnet-calls / solve, wall-clock / solve.

## First actions when resuming
1. Re-pull the post-cutoff window from the parquet (mind HF 429; cache locally).
2. Lock the M-instance set (stratified, images confirmed).
3. Provision one box; write a per-instance driver (reproduce → offline → loop → gate)
   that takes the gate command as a parameter (derive per instance from `test_patch`).
4. Run, fixing gate derivation per repo; log to `results/2026-XX-rung2-rate.md`.
5. Report the rate. If ≥ a few solves cleanly, THAT is the broadcast-worthy artifact
   (Show HN / SWE-rebench-shaped) — not before.
