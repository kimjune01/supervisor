# Rust Debugging Actor

`actor/` is a concrete Rust-debugging actor implementing the supervisor thesis:
supplement an expert system and resolve its residue via LLM calls.

The actor has three tiers:

1. Hygraph committed rules: exact-match fixes with zero LLM cost.
2. Trained model: placeholder for learned ranking or prediction.
3. LLM fallback: Claude/Sonnet proposes a novel hypothesis and patch.

It uses three stores, aligned with Peirce's triad:

- Hygraph: semantic memory. Abduction writes staged hypotheses; induction
  commits or retracts rules.
- Worktree: experiment surface. Deduction applies patches and runs tests.
- Epmem: episodic memory. A two-tier tape of short-term episodes and
  long-term counters.

Run from the repository root:

```sh
python3 -m actor.commit --dry-run
```

Corpus data belongs under `actor/data/`, which is gitignored.
