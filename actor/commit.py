"""Extract and commit rules from confirmed abduction traces.

A confirmed trace has at least one step where:
  - trajectory == 'convergent'
  - observation_after.test_vector shows all tests passing

That step's hypothesis + applied_diff become a committed rule.
The rule's signatures are keyword phrases extracted from observation_before's
error output — the patterns that would trigger this rule on a future match.

Usage:
  python3 -m actor.commit                        # all runs
  python3 -m actor.commit --runs-dir actor/data/runs
  python3 -m actor.commit --dry-run              # print only
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ACTOR = Path(__file__).resolve().parent

from .hygraph import Hygraph, HYGRAPH_DIR  # noqa: E402

DEFAULT_RUNS = ACTOR / "data" / "runs"

# Patterns in Rust compiler/test output worth indexing as rule signatures.
# Each is a regex; the first capture group (or whole match) becomes the signature.
_SIG_PATTERNS: list[re.Pattern] = [
    re.compile(r"byte index \d+ is not a char boundary"),
    re.compile(r"panicked at '([^']{10,80})'"),
    re.compile(r"error\[E\d+\]: (.{10,80})"),
    re.compile(r"thread '.*?' panicked at (.{10,80})"),
    re.compile(r"called `Option::unwrap\(\)` on a `None` value"),
    re.compile(r"called `Result::unwrap\(\)` on an `Err` value: (.{10,80})"),
    re.compile(r"attempt to (subtract|add|multiply) with overflow"),
    re.compile(r"index out of bounds: the len is \d+ but the index is \d+"),
    re.compile(r"assertion `left == right` failed"),
    re.compile(r"assertion failed: (.{10,80})"),
]


def extract_signatures(obs_text: str) -> list[str]:
    """Pull distinctive error phrases from observation text to use as rule triggers."""
    sigs: list[str] = []
    for pat in _SIG_PATTERNS:
        for m in pat.finditer(obs_text):
            sig = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
            sig = sig.strip()[:120]
            if sig and sig not in sigs:
                sigs.append(sig)
    return sigs[:5]  # cap at 5 signatures per rule


def _obs_text(obs: dict) -> str:
    parts: list[str] = []
    for key in ("cargo_test_all", "cargo_test_target"):
        v = obs.get(key)
        if isinstance(v, dict):
            parts.append(v.get("stderr", ""))
            parts.append(v.get("stdout", ""))
    return "\n".join(p for p in parts if p)


def _is_confirmed(record: dict) -> bool:
    obs_after = record.get("observation_after") or {}
    tv = obs_after.get("test_vector") or {}
    return bool(tv) and all(v == "ok" for v in tv.values())


def load_trace(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8").strip()
    records = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return records


def commit_from_trace(trace_path: Path, hygraph: Hygraph, dry_run: bool = False) -> int:
    source = trace_path.parent.name
    records = load_trace(trace_path)
    committed = 0

    for record in records:
        if not _is_confirmed(record):
            continue

        hypothesis = (record.get("hypothesis") or "").strip()
        applied_diff = (record.get("applied_diff") or "").strip()
        obs_before = record.get("observation_before") or {}
        obs_text = _obs_text(obs_before)
        sigs = extract_signatures(obs_text)

        if not hypothesis or not sigs:
            continue

        # Check if an identical signature set is already committed
        existing = hygraph.match(obs_text)
        if existing:
            continue  # already have a rule for this pattern

        if dry_run:
            print(f"  [DRY] would commit rule from {source}")
            print(f"    hypothesis: {hypothesis[:100]}")
            print(f"    signatures: {sigs}")
            committed += 1
            continue

        obs_id = hygraph.observe(
            {"text": obs_text[:2000], "source_trace": source},
            spawned_by=source,
        )
        hyp_id = hygraph.stage(
            {
                "hypothesis": hypothesis,
                "diff": applied_diff,
                "signatures": sigs,
                "signature": sigs[0] if sigs else "",
                "source_trace": source,
            },
            observation=obs_id,
            source="trace",
        )
        hygraph.perturb(hyp_id, "converge", {"source": source, "auto_committed": True})
        hygraph.commit(hyp_id)
        committed += 1
        print(f"  committed rule from {source}: {sigs[0]!r}")

    return committed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS)
    parser.add_argument("--hygraph-dir", type=Path, default=HYGRAPH_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    hygraph = Hygraph(args.hygraph_dir)
    total = 0

    for trace_path in sorted(args.runs_dir.glob("*/trace.jsonl")):
        n = commit_from_trace(trace_path, hygraph, dry_run=args.dry_run)
        if n:
            total += n

    print(f"\n{'Would commit' if args.dry_run else 'Committed'} {total} rules total.")
    print(f"Hygraph now has {len(hygraph.committed_rules())} committed rules.")
    hygraph.render()
    return 0


if __name__ == "__main__":
    sys.exit(main())
