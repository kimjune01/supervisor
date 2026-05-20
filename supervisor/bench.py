"""Bench — run the encoding loop against a public classification benchmark.

Neutral-ground efficacy test (not the GitHub corpora): does the rind-vs-residue
split hold, and does it measure GOOD on a held-out test set, not just faithful?

Pipeline on Banking77 (77 intents, short queries):
  1. PROPOSE (LLM, residue->structure): per intent, the model reads example
     train queries and returns either a keyword rule (case=expert) or "this is
     paraphrase-driven" (case=agent). One call per intent.
  2. GATE (deterministic idempotence wall): keep an expert rule only if its
     keywords fire on TRAIN with precision >= threshold for its own intent.
     Pure regex, no LLM, bit-reproducible.
  3. EVALUATE on a held-out test sample:
       - RIND: deterministic regex. A test query whose kept rules fire exactly
         one intent is classified by that rule, no model call.
       - RESIDUE: the LLM classifies the rest (the agent nucleus).
       - BASELINE: the LLM classifies ALL test queries (the no-encoding control).
  Report: rind coverage / accuracy, residue accuracy, total vs baseline, and the
  LLM-call savings (rind needs none).

The thesis prediction: a precision-gated rind covers a real fraction at high
accuracy with zero model freight; total accuracy >= baseline at lower cost.
"""

from __future__ import annotations

import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path

from supervisor.core import SUPERVISOR_DIR, _ask_sonnet

BENCH_DIR = SUPERVISOR_DIR / "bench"
RULES_PATH = BENCH_DIR / "rules.json"
REPORT_PATH = BENCH_DIR / "report.json"

_MODEL = "claude-sonnet-4-6"


def _load(split: str) -> list[tuple[str, str]]:
    """Return [(text, label)] for the cached split (train|test)."""
    path = BENCH_DIR / f"{split}.csv"
    rows: list[tuple[str, str]] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            text = (row.get("text") or "").strip()
            label = (row.get("category") or "").strip()
            if text and label:
                rows.append((text, label))
    return rows


# ---------------------------------------------------------------- propose

def _propose_rule(intent: str, examples: list[str], model: str) -> dict | None:
    system = (
        "You build an expert system for intent classification. For ONE intent, "
        "decide whether it can be fired by a deterministic KEYWORD/PHRASE rule "
        "(high precision, no judgment) or whether it is paraphrase-driven and "
        "needs a model to read the query. Return JSON: "
        '{"case": "expert"|"agent", '
        '"keywords": ["phrase", ...], '
        '"rationale": "..."}. '
        "For expert: list distinctive keywords/phrases such that a query "
        "containing any of them almost always has THIS intent and not another. "
        "Prefer specific multi-word phrases over generic single words. For agent: "
        "return an empty keywords list. Do not invent keywords absent from the "
        "examples' vocabulary."
    )
    sample = "\n".join(f"- {q}" for q in examples[:15])
    user = f"Intent: {intent}\nExample queries:\n{sample}"
    out = _ask_sonnet(system, user, model)
    if out is None:
        return None
    return {
        "intent": intent,
        "case": out.get("case", "agent"),
        "keywords": [k for k in (out.get("keywords") or []) if isinstance(k, str) and k.strip()],
        "rationale": out.get("rationale", ""),
    }


def _kw_regex(keywords: list[str]) -> re.Pattern | None:
    if not keywords:
        return None
    parts = [re.escape(k.strip().lower()) for k in keywords if k.strip()]
    if not parts:
        return None
    # word-boundary where the keyword starts/ends with a word char; phrases
    # match literally (spaces included).
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.IGNORECASE)


# ---------------------------------------------------------------- gate (deterministic)

def _gate(rules: list[dict], train: list[tuple[str, str]],
          min_precision: float, min_fires: int) -> list[dict]:
    """Idempotence wall, DETERMINISTIC: keep an expert rule only if, on train,
    its keywords fire with precision >= min_precision for its own intent and
    fire at least min_fires times. Pure regex; no LLM."""
    kept: list[dict] = []
    for r in rules:
        if r["case"] != "expert" or not r["keywords"]:
            continue
        rx = _kw_regex(r["keywords"])
        if rx is None:
            continue
        fires = 0
        correct = 0
        for text, label in train:
            if rx.search(text):
                fires += 1
                if label == r["intent"]:
                    correct += 1
        precision = (correct / fires) if fires else 0.0
        if fires >= min_fires and precision >= min_precision:
            kept.append({**r, "_rx": rx, "train_fires": fires,
                         "train_precision": round(precision, 3)})
    return kept


# ---------------------------------------------------------------- residue (LLM)

def _build_classifier_prompt(intents: list[str], exemplars: dict[str, str]) -> str:
    """Best-practice system prompt for the LLM classifier, shared by BOTH the
    residue handler and the baseline so the comparison is apples-to-apples and
    the baseline is strong (not a strawman): explicit task, the full label set
    WITH a representative example per label (few-shot grounding from train),
    a tie-break instruction, and a strict single-label JSON contract."""
    catalog = "\n".join(f"- {it}: e.g. \"{exemplars.get(it, '')}\"" for it in intents)
    return (
        "You are an intent classifier for banking customer queries. Choose the "
        "SINGLE best-matching intent from the catalog below. Each intent is shown "
        "with one representative example.\n\n"
        "Rules:\n"
        "- Return exactly one intent, chosen only from the catalog.\n"
        "- If the query is ambiguous, pick the single most likely intent.\n"
        "- Match on the query's meaning, not surface keywords alone.\n\n"
        f"INTENT CATALOG (label: example):\n{catalog}\n\n"
        'Return JSON: {"intent": "<exact label from the catalog>"}.'
    )


def _llm_classify(text: str, intents: list[str], system: str, model: str) -> str | None:
    out = _ask_sonnet(system, f"Query: {text}", model, timeout=60)
    if out is None:
        return None
    pred = out.get("intent")
    return pred if pred in intents else None


# ---------------------------------------------------------------- run

def run(per_intent: int = 15, test_sample: int = 120,
        min_precision: float = 0.9, min_fires: int = 3,
        model: str = _MODEL, seed: int = 0) -> dict:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    train = _load("train")
    test = _load("test")
    intents = sorted({label for _, label in train})

    by_intent: dict[str, list[str]] = defaultdict(list)
    for text, label in train:
        by_intent[label].append(text)

    # Shared best-practice classifier prompt (few-shot from train), used by BOTH
    # the residue handler and the baseline so the control is strong and fair.
    exemplars = {it: by_intent[it][0] for it in intents if by_intent[it]}
    clf_system = _build_classifier_prompt(intents, exemplars)

    # 1. PROPOSE — one LLM call per intent.
    rules: list[dict] = []
    for i, intent in enumerate(intents):
        r = _propose_rule(intent, by_intent[intent][:per_intent], model)
        if r is not None:
            rules.append(r)
        print(f"  proposed {i+1}/{len(intents)}: {intent} -> {r['case'] if r else 'FAILED'}")

    # 2. GATE — deterministic precision filter on train.
    kept = _gate(rules, train, min_precision, min_fires)
    kept_intents = {r["intent"] for r in kept}
    print(f"\nproposed expert: {sum(1 for r in rules if r['case']=='expert')}  "
          f"kept after gate: {len(kept)}  "
          f"(of {len(intents)} intents)")

    # 3. EVALUATE on a held-out test sample.
    rng = random.Random(seed)
    sample = rng.sample(test, min(test_sample, len(test)))

    rind_total = rind_correct = 0
    residue: list[tuple[str, str]] = []
    for text, label in sample:
        fired = [r["intent"] for r in kept if r["_rx"].search(text)]
        uniq = set(fired)
        if len(uniq) == 1:  # rind: exactly one rule fires
            pred = next(iter(uniq))
            rind_total += 1
            rind_correct += int(pred == label)
        else:  # none, or ambiguous -> residue
            residue.append((text, label))

    residue_total = len(residue)
    residue_correct = 0
    for text, label in residue:
        pred = _llm_classify(text, intents, clf_system, model)
        residue_correct += int(pred == label)

    # Baseline: the SAME classifier on ALL sampled queries (no encoding).
    base_correct = 0
    for text, label in sample:
        pred = _llm_classify(text, intents, clf_system, model)
        base_correct += int(pred == label)

    n = len(sample)
    report = {
        "dataset": "banking77",
        "intents": len(intents),
        "params": {"per_intent": per_intent, "test_sample": n,
                   "min_precision": min_precision, "min_fires": min_fires,
                   "seed": seed},
        "rind": {
            "intents_covered": len(kept_intents),
            "coverage": round(rind_total / n, 3),
            "accuracy": round(rind_correct / rind_total, 3) if rind_total else None,
            "llm_calls": 0,
        },
        "residue": {
            "count": residue_total,
            "accuracy": round(residue_correct / residue_total, 3) if residue_total else None,
            "llm_calls": residue_total,
        },
        "total": {
            "accuracy": round((rind_correct + residue_correct) / n, 3),
            "llm_calls": residue_total,
        },
        "baseline_llm_only": {
            "accuracy": round(base_correct / n, 3),
            "llm_calls": n,
        },
        "llm_calls_saved_vs_baseline": n - residue_total,
    }
    RULES_PATH.write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "_rx"} for r in kept], indent=2))
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    return report
