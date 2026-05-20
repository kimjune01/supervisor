"""Bench — run the encoding loop against a public classification benchmark, and
compare it head-to-head with the feasible alternatives.

Banking77 is small enough to run the whole matrix. Five arms over ONE shared
test sample (LLM predictions are cached and reused across arms, never re-called):

  1. sonnet-only      — full 77-way classify, no structure. The expensive control.
  2. haiku-only       — same, cheap model. Cost/quality control.
  3. tfidf-only       — TF-IDF + logistic regression, NO LLM. Pure trained classical.
  4. tfidf + reject   — TF-IDF shell answers when confident; abstains to sonnet
                        below a probability threshold. A *small trained model* +
                        LLM residue. (Classifier-with-reject-option, Chow 1970.)
  5. features + rules — an LLM (Haiku) extracts a bounded feature vector;
                        DETERMINISTIC rules induced from train decide the rind;
                        sonnet handles residue. A *no-weights expert system* +
                        LLM residue. THE THESIS ARCHITECTURE.

The honest comparison is (4) vs (5): does the cheap deterministic shell NEED
trained weights (tfidf), or do induced rules over LLM-extracted features suffice?
On a lexically rich task we expect (4) > (5); on a structured-field task
(FINDINGS #19) we expect (5) to close the gap. (1)/(2)/(3) bound the field.

Faithful to FINDINGS #33: the deterministic layers (3,4,5) never let the model
read prose at decision time — tfidf is a fit linear model; features are extracted
once, then rules are pure counting.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from supervisor.core import SUPERVISOR_DIR, _ask_sonnet

BENCH_DIR = SUPERVISOR_DIR / "bench"
REPORT_PATH = BENCH_DIR / "report.json"
SCHEMA_PATH = BENCH_DIR / "schema.json"
RULES_PATH = BENCH_DIR / "rules.json"

_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"


def _load(split: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with open(BENCH_DIR / f"{split}.csv", newline="") as f:
        for row in csv.DictReader(f):
            t, l = (row.get("text") or "").strip(), (row.get("category") or "").strip()
            if t and l:
                rows.append((t, l))
    return rows


def _acc(preds: list[str | None], golds: list[str]) -> float:
    return round(sum(int(p == g) for p, g in zip(preds, golds)) / len(golds), 3)


# ---------------------------------------------------------------- LLM classifier (arms 1,2 + residue)

def _classifier_prompt(intents: list[str], exemplars: dict[str, str]) -> str:
    catalog = "\n".join(f"- {it}: e.g. \"{exemplars.get(it, '')}\"" for it in intents)
    return (
        "You are an intent classifier for banking customer queries. Choose the "
        "SINGLE best-matching intent from the catalog (each shown with one "
        "example).\nRules: return exactly one intent from the catalog; if "
        "ambiguous pick the most likely; match on meaning, not keywords.\n\n"
        f"INTENT CATALOG (label: example):\n{catalog}\n\n"
        'Return JSON: {"intent": "<exact label>"}.'
    )


def _classify(text: str, intents: list[str], system: str, model: str) -> str | None:
    out = _ask_sonnet(system, f"Query: {text}", model, timeout=60)
    if not out:
        return None
    p = out.get("intent")
    return p if p in intents else None


# ---------------------------------------------------------------- TF-IDF arms (3,4)

def _fit_tfidf(train: list[tuple[str, str]]):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    X = [t for t, _ in train]
    y = [l for _, l in train]
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("clf", LogisticRegression(max_iter=1000, C=10.0)),
    ])
    pipe.fit(X, y)
    return pipe


# ---------------------------------------------------------------- feature-rule arm (5)

def _propose_schema(by_intent, intents, model) -> dict:
    spread = []
    for it in intents:
        spread += by_intent[it][:2]
    sample = "\n".join(f"- {q}" for q in spread[:120])
    system = (
        "Design a compact FEATURE SCHEMA for an intent classifier, extracted from "
        "short banking queries by a small model and consumed by deterministic "
        "rules. Propose ONE categorical `subject` (10-20 coarse topic values that "
        "partition what queries are ABOUT) and 4-8 boolean `flags` (orthogonal, "
        "surface-checkable: is_problem_report, mentions_timing, mentions_fee, "
        "mentions_card, is_question_howto, ...). Extractable from text alone, "
        "reusable, not restating an intent label. Return JSON: "
        '{"subject_values": ["..."], "flags": ["..."]}'
    )
    out = _ask_sonnet(system, f"Example queries:\n{sample}", model)
    if not out or not out.get("subject_values"):
        return {"subject_values": ["card", "transfer", "account", "payment",
                "exchange", "fees", "verification", "topup", "withdrawal", "other"],
                "flags": ["is_problem_report", "mentions_timing", "mentions_fee", "mentions_card"]}
    return {"subject_values": [str(v) for v in out["subject_values"]],
            "flags": [str(f) for f in (out.get("flags") or [])]}


def _extract(text, schema, model) -> dict | None:
    out = _ask_sonnet(
        "Extract a feature vector from the banking query. Choose exactly one "
        f"`subject` from: {schema['subject_values']}. Set each flag true/false: "
        f"{schema['flags']}. Judge only from the query text. Return JSON: "
        '{"subject": "<one value>", "flags": {"<flag>": true/false}}',
        f"Query: {text}", model, timeout=40)
    if not out:
        return None
    subj = out.get("subject")
    vec = {"subject": subj if subj in schema["subject_values"] else None}
    fl = out.get("flags") or {}
    for f in schema["flags"]:
        vec[f] = bool(fl.get(f, False))
    return vec


def _preds_of(vec, schema):
    preds = []
    subj = vec.get("subject")
    if subj is not None:
        preds.append(("subject", subj))
        for f in schema["flags"]:
            preds.append((f"subject+{f}", (subj, vec.get(f, False))))
    for f in schema["flags"]:
        preds.append((f, vec.get(f, False)))
    return preds


def _induce(train_vecs, schema, min_precision, min_fires) -> dict:
    fires = defaultdict(Counter)
    for vec, label in train_vecs:
        for p in _preds_of(vec, schema):
            fires[p][label] += 1
    rules = {}
    for p, c in fires.items():
        total = sum(c.values())
        intent, n = c.most_common(1)[0]
        if total >= min_fires and n / total >= min_precision:
            rules[p] = intent
    return rules


def _apply(vec, schema, rules) -> set:
    return {rules[p] for p in _preds_of(vec, schema) if p in rules}


# ---------------------------------------------------------------- run all arms

def run(induce_per_intent: int = 6, test_sample: int = 120,
        min_precision: float = 0.9, min_fires: int = 4,
        reject_thresholds=(0.3, 0.5, 0.7), seed: int = 0) -> dict:
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    train, test = _load("train"), _load("test")
    intents = sorted({l for _, l in train})
    by_intent = defaultdict(list)
    for t, l in train:
        by_intent[l].append(t)
    exemplars = {it: by_intent[it][0] for it in intents if by_intent[it]}
    clf_system = _classifier_prompt(intents, exemplars)

    rng = random.Random(seed)
    sample = rng.sample(test, min(test_sample, len(test)))
    texts = [t for t, _ in sample]
    golds = [l for _, l in sample]
    calls = {"haiku": 0, "sonnet": 0}

    # Cached LLM predictions over the sample (computed once, reused by arms).
    print("classifying sample: sonnet ...")
    sonnet_pred = {}
    for t in texts:
        sonnet_pred[t] = _classify(t, intents, clf_system, _SONNET); calls["sonnet"] += 1
    print("classifying sample: haiku ...")
    haiku_pred = {}
    for t in texts:
        haiku_pred[t] = _classify(t, intents, clf_system, _HAIKU); calls["haiku"] += 1

    arms = {}
    arms["sonnet_only"] = {"accuracy": _acc([sonnet_pred[t] for t in texts], golds),
                           "calls": {"sonnet": len(texts)}}
    arms["haiku_only"] = {"accuracy": _acc([haiku_pred[t] for t in texts], golds),
                          "calls": {"haiku": len(texts)}}

    # Arms 3 & 4 — TF-IDF (trained shell), no LLM to fit.
    print("fitting tfidf + logistic regression ...")
    pipe = _fit_tfidf(train)
    proba = pipe.predict_proba(texts)
    classes = list(pipe.named_steps["clf"].classes_)
    tfidf_pred = [classes[row.argmax()] for row in proba]
    tfidf_conf = [float(row.max()) for row in proba]
    arms["tfidf_only"] = {"accuracy": _acc(tfidf_pred, golds), "calls": {}}
    arms["tfidf_reject"] = {}
    for thr in reject_thresholds:
        preds, rejected = [], 0
        for i, t in enumerate(texts):
            if tfidf_conf[i] >= thr:
                preds.append(tfidf_pred[i])
            else:
                preds.append(sonnet_pred[t]); rejected += 1
        arms["tfidf_reject"][f"thr={thr}"] = {
            "accuracy": _acc(preds, golds),
            "shell_coverage": round((len(texts) - rejected) / len(texts), 3),
            "calls": {"sonnet_residue": rejected},  # sonnet preds were cached
        }

    # Arm 5 — LLM-feature rules (no-weights expert system).
    print("arm5: schema ...")
    schema = _propose_schema(by_intent, intents, _SONNET); calls["sonnet"] += 1
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2))
    induce_set = []
    for it in intents:
        qs = by_intent[it][:]; rng.shuffle(qs)
        induce_set += [(q, it) for q in qs[:induce_per_intent]]
    print(f"arm5: extracting {len(induce_set)} train (haiku) ...")
    train_vecs = []
    for q, l in induce_set:
        v = _extract(q, schema, _HAIKU); calls["haiku"] += 1
        if v:
            train_vecs.append((v, l))
    rules = _induce(train_vecs, schema, min_precision, min_fires)
    RULES_PATH.write_text(json.dumps({f"{k[0]}={k[1]}": v for k, v in rules.items()}, indent=2))
    print(f"arm5: induced {len(rules)} rules; extracting test (haiku) ...")
    rind_n = rind_ok = 0
    preds5 = []
    for t, g in zip(texts, golds):
        v = _extract(t, schema, _HAIKU); calls["haiku"] += 1
        fired = _apply(v, schema, rules) if v else set()
        if len(fired) == 1:
            p = next(iter(fired)); rind_n += 1; rind_ok += int(p == g); preds5.append(p)
        else:
            preds5.append(sonnet_pred[t])  # residue, cached sonnet
    arms["features_rules"] = {
        "accuracy": _acc(preds5, golds),
        "rind": {"rules": len(rules),
                 "intents_covered": len(set(rules.values())),
                 "coverage": round(rind_n / len(texts), 3),
                 "accuracy": round(rind_ok / rind_n, 3) if rind_n else None},
        "calls": {"haiku_extract": len(induce_set) + len(texts),
                  "sonnet_schema": 1,
                  "sonnet_residue": len(texts) - rind_n},
    }

    report = {
        "dataset": "banking77", "intents": len(intents),
        "test_sample": len(texts),
        "params": {"induce_per_intent": induce_per_intent,
                   "min_precision": min_precision, "min_fires": min_fires,
                   "reject_thresholds": list(reject_thresholds), "seed": seed},
        "models": {"cheap": _HAIKU, "strong": _SONNET},
        "arms": arms,
        "total_calls_this_run": calls,
        "note": "arms 3-5 reuse the cached sonnet predictions for their residue; "
                "call counts under each arm are what that arm would cost in "
                "isolation. Weigh sonnet calls ~10x haiku for cost.",
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    return report
