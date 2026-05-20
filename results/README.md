# results

Recorded bench runs, kept for reproducibility (methodeutics ch12/ch13; FINDINGS
#25). Each file is a frozen result with provenance — not a transient report.

## What's recorded

Every run carries a `provenance` block: the repo `git_sha`, UTC timestamp, the
corpus source, and the **model versions** used. That's the full reproduction
recipe:

```
checkout <git_sha>  +  same params (in the report)  +  same model versions
   -> re-runnable benchmark, not a pre-registration
```

## The honest reproduction caveats

- **LLM non-determinism.** The four-case switch, feature extraction, residue
  classification, and abductive proposals are model calls; verdicts vary run to
  run. For bit-reproduction, pin the model versions in `provenance.models` and
  set temperature=0. The *structural* findings (rind exists; abductive vs naive
  direction; tfidf-vs-rules ordering) are robust to this; the exact decimals are
  samples.
- **Corpus is frozen.** Banking77 is a fixed published train/test split
  (PolyAI-LDN/task-specific-datasets), so it does not drift. Re-fetch is
  deterministic.
- **Single seed / single dataset = suggestive, not proof.** A claim like
  "abduction is an ML primitive" needs multiple seeds (delta > noise) and >1
  corpus type. These files record what was actually run; read the `params` for
  seed and sample sizes before generalizing.

## Naming

`YYYY-MM-DD-<experiment>[-seedN].json` — e.g. `2026-05-19-banking77-5arm.json`,
`2026-05-19-abduction-6a-vs-6n-seed0.json`.

## Reproduce

```sh
git checkout <git_sha>
uv sync
supervisor bench banking77            # 5-arm matrix
supervisor bench-abduction            # 6a abductive vs 6n naive
# compare against the recorded report's params + provenance.models
```
