"""`sweep supervisor …` — run the encoding loop over a classifier, list and
apply its staged proposals.

The supervisor reads a target actor's attention channels (andon + operator
inbox), clusters recurring patterns, runs the four-case switch
(expert > agent > supervisor > human) via Sonnet, replay-gates the hoists,
and stages propose-only artifacts. This CLI is the standalone driver: no
worker, no metronome — `run` does one pass in-process.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from supervisor.core import PROPOSALS_DIR, supervise
from supervisor.specs import (SPECS, contributor_spec, review_action_spec,
                              author_response_spec, with_outcomes,
                              OUTCOME_KEYS)
from supervisor import bench as _bench

supervisor_app = typer.Typer(
    help="Supervisor — encoding loop over classifiers (propose-only)",
    no_args_is_help=True,
)


def _resolve(name: str, limit: int | None = None):
    if name in SPECS:
        return SPECS[name]
    if name.startswith("actions-"):
        return review_action_spec(name[len("actions-"):], limit=limit or 30)
    if name.startswith("respond-"):
        return author_response_spec(name[len("respond-"):], limit=limit or 25)
    if name.startswith("corpus-"):
        return contributor_spec(name[len("corpus-"):])
    return None


@supervisor_app.command("run")
def supervisor_run(
    spec: str = typer.Argument(
        ..., help="switch | remit | compose | corpus-<login> | actions-<login> | respond-<login>"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="Print the full pass summary"),
    outcomes: bool = typer.Option(
        False, "--outcomes",
        help="Also pull the regret channel (fetch PR outcomes via gh to catch "
             "silent misclassifications). Slower — one gh call per recent "
             "decision. switch/remit only."),
    limit: int = typer.Option(
        None, "--limit",
        help="Corpus sample size for actions-/respond- specs (PRs to pull). "
             "Full-time contributors have hundreds; bump this for coverage."),
) -> None:
    """Run one supervisor pass over SPEC. Stages proposals to
    ~/.sweep/supervisor/proposals/ and HITL cards to the human inbox.
    Never edits source — propose-only."""
    s = _resolve(spec, limit=limit)
    if s is None:
        raise typer.BadParameter(
            f"unknown spec '{spec}' (have: {', '.join(SPECS)}, or corpus-<login>)")
    if outcomes:
        if spec not in OUTCOME_KEYS:
            raise typer.BadParameter(
                f"--outcomes not supported for '{spec}' (have: {', '.join(OUTCOME_KEYS)})")
        s = with_outcomes(s, **OUTCOME_KEYS[spec])
    summary = supervise(s, verbose=verbose)
    print(f"# Supervisor pass — {summary['spec']}")
    print(f"goal: {summary['goal']}")
    print(f"observations={summary['observations']}  "
          f"clusters={summary['clusters']}  "
          f"recurring={summary['recurring']}")
    print(f"  expert     (trivial hoist):   {len(summary['expert'])}")
    print(f"  supervisor (gated hoist):     {len(summary['supervisor'])}")
    print(f"  agent      (left in nucleus): {len(summary['agent'])}")
    print(f"  human      (escalated HITL):  {len(summary['human'])}")
    print(f"  replay-rejected (conflict):   {len(summary['replay_rejected'])}")
    print(f"  verifier-down (not a verdict):{len(summary.get('verifier_down', []))}")
    print(f"  cache-skipped (known reject): {len(summary['cache_skipped'])}")
    proposed = summary["expert"] + summary["supervisor"]
    if proposed:
        print("\nstaged proposals:")
        for p in proposed:
            print(f"  [{p.get('stratum', '?')}] {p['signature']}  "
                  f"({p['count']}×)  -> {p['path']}")


@supervisor_app.command("list")
def supervisor_list() -> None:
    """List staged proposals awaiting operator review."""
    if not PROPOSALS_DIR.exists():
        print(f"(none at {PROPOSALS_DIR})")
        return
    files = sorted(PROPOSALS_DIR.glob("*.md"))
    if not files:
        print(f"(none at {PROPOSALS_DIR})")
        return
    for f in files:
        head = ""
        for line in f.read_text().splitlines():
            if line.startswith("# Supervisor proposal"):
                head = line.lstrip("# ").strip()
                break
        print(f"  {f.name}  {head}")


@supervisor_app.command("show")
def supervisor_show(
    name: str = typer.Argument(..., help="proposal filename (with or without .md)"),
) -> None:
    """Print one staged proposal."""
    fn = name if name.endswith(".md") else f"{name}.md"
    path = PROPOSALS_DIR / fn
    if not path.exists():
        raise typer.BadParameter(f"no such proposal: {fn}")
    print(path.read_text())


@supervisor_app.command("archive")
def supervisor_archive(
    name: str = typer.Argument(..., help="proposal filename (with or without .md)"),
) -> None:
    """Archive a proposal after you've applied or rejected it. The signal
    that you've Attended — the edit (if any) is in git history."""
    fn = name if name.endswith(".md") else f"{name}.md"
    path = PROPOSALS_DIR / fn
    if not path.exists():
        raise typer.BadParameter(f"no such proposal: {fn}")
    archive_dir = PROPOSALS_DIR / "archived"
    archive_dir.mkdir(parents=True, exist_ok=True)
    path.rename(archive_dir / fn)
    print(f"archived {fn}")


@supervisor_app.command("bench")
def supervisor_bench(
    dataset: str = typer.Argument("banking77", help="benchmark name (banking77)"),
    per_intent: int = typer.Option(15, "--per-intent", help="train examples shown per intent when proposing"),
    test_sample: int = typer.Option(120, "--test-sample", help="held-out test queries to score"),
    min_precision: float = typer.Option(0.9, "--min-precision", help="train-precision threshold to keep an expert rule"),
    seed: int = typer.Option(0, "--seed"),
) -> None:
    """Run the encoding loop against a public classification benchmark and score
    rind vs residue vs a strong LLM-only baseline (same classifier, few-shot).
    Neutral-ground efficacy test: measures GOODNESS (accuracy), not just
    faithfulness."""
    if dataset != "banking77":
        raise typer.BadParameter("only 'banking77' is wired up so far")
    r = _bench.run(induce_per_intent=per_intent, test_sample=test_sample,
                   min_precision=min_precision, seed=seed)
    a = r["arms"]
    print(f"\n# Bench — {r['dataset']} ({r['intents']} intents, "
          f"test_sample={r['test_sample']})")
    print(f"  sonnet-only     acc={a['sonnet_only']['accuracy']}  (control, expensive)")
    print(f"  haiku-only      acc={a['haiku_only']['accuracy']}  (cheap model)")
    print(f"  tfidf-only      acc={a['tfidf_only']['accuracy']}  (trained, no LLM)")
    for thr, m in a["tfidf_reject"].items():
        print(f"  tfidf+reject {thr}  acc={m['accuracy']}  "
              f"shell_cover={m['shell_coverage']:.0%}  sonnet_residue={m['calls']['sonnet_residue']}")
    f = a["features_rules"]
    print(f"  features+rules  acc={f['accuracy']}  "
          f"rind_cover={f['rind']['coverage']:.0%}  rind_acc={f['rind']['accuracy']}  "
          f"intents={f['rind']['intents_covered']}/{r['intents']}")
    print(f"\n  (4 trained-shell vs 5 no-weights-rules is the key contrast; "
          f"report at {_bench.REPORT_PATH})")


@supervisor_app.command("bench-abduction")
def supervisor_bench_abduction(
    induce_per_intent: int = typer.Option(6, "--per-intent"),
    test_sample: int = typer.Option(120, "--test-sample"),
    rounds: int = typer.Option(3, "--rounds"),
    per_round: int = typer.Option(8, "--per-round", help="features abducted per round"),
    seed: int = typer.Option(0, "--seed"),
) -> None:
    """Is abduction a real thinking tool FOR AN LLM? Same LLM, same feature
    budget; abductive (figure/ground diff of the confusion, with corpus
    retrieval) vs naive (blind brainstorming). The delta is the result."""
    r = _bench.run_abduction(induce_per_intent=induce_per_intent,
                             test_sample=test_sample, rounds=rounds,
                             per_round=per_round, seed=seed)
    s, a, nv = r["start_arm5"], r["abductive_6a"], r["naive_6n"]
    d = r["delta_6a_minus_6n"]
    print(f"\n# Abduction experiment — banking77 (test={r['test_sample']})")
    print(f"  start (no growth)  rind_cover={s['rind_coverage']:.0%}  correct/total={s['rind_correct_of_total']}")
    print(f"  6a abductive       rind_cover={a['rind_coverage']:.0%}  correct/total={a['rind_correct_of_total']}  (+{a['features_added']} feats)")
    print(f"  6n naive control   rind_cover={nv['rind_coverage']:.0%}  correct/total={nv['rind_correct_of_total']}  (+{nv['features_added']} feats)")
    print(f"  DELTA 6a-6n        cover={d['rind_coverage']:+.3f}  correct/total={d['rind_correct_of_total']:+.3f}")
    print(f"  -> abduction {'HELPS' if d['rind_correct_of_total'] > 0 else 'does NOT help'} at equal budget")


@supervisor_app.command("nearby")
def supervisor_nearby(
    query: str = typer.Argument(..., help="query to find nearby corpus examples for"),
    k: int = typer.Option(8, "-k"),
    intent: str = typer.Option(None, "--intent", help="filter to one intent"),
) -> None:
    """Corpus retrieval tool: nearest Banking77 train examples to a query
    (TF-IDF cosine). The 'find nearby examples' tool the abductive loop uses."""
    train = _bench._load("train")
    nearby = _bench.make_retriever(train)
    for text, label, score in nearby(query, k=k, intent=intent):
        print(f"  {score:.3f}  [{label}]  {text}")


def main() -> None:
    """Console-script entry point."""
    supervisor_app()


if __name__ == "__main__":
    main()
