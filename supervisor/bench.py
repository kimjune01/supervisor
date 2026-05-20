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
import datetime as dt
import json
import random
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from supervisor.core import SUPERVISOR_DIR, _ask_sonnet


def _provenance() -> dict:
    """Stamp every result with what's needed to reproduce it (ch12/ch25): the
    repo commit, UTC timestamp, corpus source, and model versions. LLM calls are
    non-deterministic, so exact replication needs the pinned models + temp=0;
    the corpus is a frozen closed-PR/issue set (Banking77), so it doesn't drift."""
    here = Path(__file__).resolve().parent.parent
    try:
        sha = subprocess.run(["git", "-C", str(here), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        sha = "unknown"
    return {
        "git_sha": sha,
        "utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "corpus": "banking77 (PolyAI-LDN/task-specific-datasets, frozen)",
        "models": {"cheap": _HAIKU, "strong": _SONNET},
        "caveat": "LLM verdicts are non-deterministic; pin models + temperature=0 "
                  "for bit-reproduction. Structural findings are drift-robust.",
    }

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

def make_retriever(train: list[tuple[str, str]]):
    """Corpus access for the supervisor: a 'find nearby examples' tool. TF-IDF
    cosine over the train corpus. Returns nearby(text, k, intent=None) ->
    [(text, label, score)], optionally filtered to one intent. This is the
    cli-tool stratum (FINDINGS #33) handed to the abductive loop so it diffs the
    actually-confusable BOUNDARY cases, not arbitrary examples."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import linear_kernel
    texts = [t for t, _ in train]
    labels = [l for _, l in train]
    vec = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)
    mat = vec.fit_transform(texts)

    def nearby(text: str, k: int = 8, intent: str | None = None):
        sims = linear_kernel(vec.transform([text]), mat).ravel()
        order = sims.argsort()[::-1]
        out = []
        for i in order:
            if intent is not None and labels[i] != intent:
                continue
            if texts[i] == text:
                continue
            out.append((texts[i], labels[i], float(sims[i])))
            if len(out) >= k:
                break
        return out
    return nearby


def _boundary_examples(nearby, by_intent, x: str, y: str, k: int = 6):
    """The confusable boundary: examples of X nearest to Y's region and vice
    versa. Seed from a couple of each intent's examples, retrieve cross-near."""
    x_seed = by_intent[x][:2]
    y_seed = by_intent[y][:2]
    x_bound, y_bound = [], []
    for s in y_seed:  # X examples that look like Y
        x_bound += [t for t, _, _ in nearby(s, k=k, intent=x)]
    for s in x_seed:  # Y examples that look like X
        y_bound += [t for t, _, _ in nearby(s, k=k, intent=y)]
    # de-dup, fall back to plain slices if retrieval came up empty
    x_bound = list(dict.fromkeys(x_bound)) or by_intent[x][:k]
    y_bound = list(dict.fromkeys(y_bound)) or by_intent[y][:k]
    return x_bound[:k], y_bound[:k]


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


def _extract_flags(text, flags: list[str], model) -> dict:
    """Extract ONLY the given boolean flags for a query (incremental growth:
    new abducted features cost a small flag-only call, not a full re-extract)."""
    if not flags:
        return {}
    out = _ask_sonnet(
        f"For the banking query, set each flag true/false based only on the "
        f"query text. Flags: {flags}. Return JSON: "
        '{"flags": {"<flag>": true/false}}',
        f"Query: {text}", model, timeout=40)
    fl = (out or {}).get("flags") or {}
    return {f: bool(fl.get(f, False)) for f in flags}


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
        "provenance": _provenance(),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    return report


# ================================================================ abduction
#
# Is abduction a real thinking tool FOR AN LLM? Same LLM, same feature budget,
# same deterministic gate; the only difference is HOW new features are born:
#   6a (abductive): figure/ground DIFF of the confusion. The shape of the
#       failure names the feature. (tri-abduction: diff the two confused
#       intents' examples; bi-abduction available on misclassified residue.)
#   6n (naive control): the LLM brainstorms the same NUMBER of features from
#       the intent list, BLIND to where the rind is failing.
# If 6a > 6n at equal budget, the diff earned its keep. If 6a ~= 6n, abduction
# is just feature-count here. The delta is the result.

ABDUCTION_REPORT = BENCH_DIR / "abduction_report.json"


def _confusion_pairs(vecs, schema, rules, top: int) -> list[tuple[str, str]]:
    """Where the current rules fail to separate intents. On the (held-out)
    vectors, for each example compute the rule verdict; tally (true, predicted)
    off-diagonal and residue collisions. Return the top confused (X, Y) pairs."""
    pair_counts: Counter = Counter()
    for vec, true in vecs:
        fired = _apply(vec, schema, rules)
        if true in fired and len(fired) > 1:      # true intent fires but so do others
            for other in fired:
                if other != true:
                    pair_counts[tuple(sorted((true, other)))] += 1
        elif fired and true not in fired:          # fires only wrong intents
            for other in fired:
                pair_counts[tuple(sorted((true, other)))] += 1
    return [p for p, _ in pair_counts.most_common(top)]


def _abduct(x: str, ex_x: list[str], y: str, ex_y: list[str],
            existing: list[str], model: str) -> dict | None:
    """Tri-abduction: diff examples of intent X vs intent Y, propose ONE boolean
    feature (extractable from query text) that separates them, reasoning about
    whether it extends an existing rule or makes a new distinction. Figure =
    what differs; ground = what they share."""
    out = _ask_sonnet(
        "Two intents are being CONFUSED by the current feature set. Diff their "
        "example queries (figure = what systematically differs, ground = what "
        "they share) and propose ONE new BOOLEAN feature, extractable from query "
        "text alone, whose presence separates intent X from intent Y. Do not "
        f"duplicate an existing feature: {existing}. Return JSON: "
        '{"flag": "snake_case_name", "definition": "true when ...", '
        '"separates": "X has it / Y lacks it (or vice versa)"}',
        f"Intent X = {x}\nX examples:\n" + "\n".join(f"- {q}" for q in ex_x[:8]) +
        f"\n\nIntent Y = {y}\nY examples:\n" + "\n".join(f"- {q}" for q in ex_y[:8]),
        model)
    if not out or not out.get("flag"):
        return None
    return {"flag": str(out["flag"]), "definition": out.get("definition", ""),
            "from": f"{x} vs {y}"}


def _naive_feature(intents: list[str], existing: list[str], model: str) -> dict | None:
    """Control: propose a new boolean feature WITHOUT the confusion diff — blind
    to where the rind fails. Same output shape, same budget."""
    out = _ask_sonnet(
        "Propose ONE new BOOLEAN feature, extractable from a banking query's "
        "text alone, that would help an intent classifier over these intents. "
        f"Do not duplicate an existing feature: {existing}. Return JSON: "
        '{"flag": "snake_case_name", "definition": "true when ..."}',
        f"Intents: {', '.join(intents)}", model)
    if not out or not out.get("flag"):
        return None
    return {"flag": str(out["flag"]), "definition": out.get("definition", ""),
            "from": "naive"}


def _grow(mode: str, schema0: dict, base_vecs: dict, test_vecs: dict,
          induce_items, test_items, intents, by_intent,
          rounds: int, per_round: int, min_precision: float, min_fires: int,
          extractor: str, proposer: str, nearby=None) -> dict:
    """One arm of the abduction experiment. base_vecs/test_vecs: text->vec dicts
    seeded with the initial (subject + initial flags) extraction, mutated in
    place as flags are added. Returns rind metrics + the feature provenance."""
    schema = {"subject_values": schema0["subject_values"],
              "flags": list(schema0["flags"])}
    provenance: list[dict] = []
    haiku = 0
    induce_vecs = [(base_vecs[q], l) for q, l in induce_items]
    for rnd in range(rounds):
        rules = _induce(induce_vecs, schema, min_precision, min_fires)
        new_flags: list[dict] = []
        if mode == "abductive":
            pairs = _confusion_pairs(induce_vecs, schema, rules, per_round)
            for x, y in pairs:
                if nearby is not None:
                    ex_x, ex_y = _boundary_examples(nearby, by_intent, x, y)
                else:
                    ex_x, ex_y = by_intent[x][:8], by_intent[y][:8]
                f = _abduct(x, ex_x, y, ex_y, schema["flags"], proposer)
                if f and f["flag"] not in schema["flags"]:
                    new_flags.append(f)
        else:  # naive control
            for _ in range(per_round):
                f = _naive_feature(intents, schema["flags"], proposer)
                if f and f["flag"] not in schema["flags"] and \
                        f["flag"] not in [g["flag"] for g in new_flags]:
                    new_flags.append(f)
        if not new_flags:
            break
        names = [f["flag"] for f in new_flags]
        schema["flags"].extend(names)
        provenance += new_flags
        # incremental extraction of ONLY the new flags
        for q, _ in induce_items:
            base_vecs[q].update(_extract_flags(q, names, extractor)); haiku += 1
        for q, _ in test_items:
            test_vecs[q].update(_extract_flags(q, names, extractor)); haiku += 1
        induce_vecs = [(base_vecs[q], l) for q, l in induce_items]

    rules = _induce(induce_vecs, schema, min_precision, min_fires)
    rind_n = rind_ok = 0
    for q, g in test_items:
        fired = _apply(test_vecs[q], schema, rules)
        if len(fired) == 1:
            rind_n += 1; rind_ok += int(next(iter(fired)) == g)
    n = len(test_items)
    return {
        "mode": mode,
        "features_added": len(provenance),
        "total_flags": len(schema["flags"]),
        "rules": len(rules),
        "rind_coverage": round(rind_n / n, 3),
        "rind_accuracy": round(rind_ok / rind_n, 3) if rind_n else None,
        "rind_correct_of_total": round(rind_ok / n, 3),
        "extract_calls": haiku,
        "provenance": provenance,
    }


def run_abduction(induce_per_intent: int = 6, test_sample: int = 120,
                  rounds: int = 3, per_round: int = 8,
                  min_precision: float = 0.85, min_fires: int = 3,
                  seed: int = 0, extractor: str = _HAIKU,
                  proposer: str = _SONNET) -> dict:
    """The clean delta: does an LLM build a better rind from confusion-diffs
    (abductive) than from blind brainstorming (naive), at equal feature budget?"""
    BENCH_DIR.mkdir(parents=True, exist_ok=True)
    train, test = _load("train"), _load("test")
    intents = sorted({l for _, l in train})
    by_intent = defaultdict(list)
    for t, l in train:
        by_intent[l].append(t)

    rng = random.Random(seed)
    induce_items = []
    for it in intents:
        qs = by_intent[it][:]; rng.shuffle(qs)
        induce_items += [(q, it) for q in qs[:induce_per_intent]]
    test_items = rng.sample(test, min(test_sample, len(test)))

    # Initial schema (Sonnet) + initial full extraction (Haiku), shared start.
    schema0 = _propose_schema(by_intent, intents, proposer)
    print(f"init schema: {len(schema0['subject_values'])} subjects, "
          f"{len(schema0['flags'])} flags; extracting initial vectors ...")
    base_vecs, test_vecs = {}, {}
    for q, _ in induce_items:
        base_vecs[q] = _extract(q, schema0, extractor) or {"subject": None}
    for q, _ in test_items:
        test_vecs[q] = _extract(q, schema0, extractor) or {"subject": None}

    # arm-5 starting point (no growth)
    start = _grow("none-start", schema0,
                  {k: dict(v) for k, v in base_vecs.items()},
                  {k: dict(v) for k, v in test_vecs.items()},
                  induce_items, test_items, intents, by_intent,
                  rounds=0, per_round=0, min_precision=min_precision,
                  min_fires=min_fires, extractor=extractor, proposer=proposer)

    print("growing ABDUCTIVE arm (with corpus retrieval) ...")
    nearby = make_retriever(train)
    abductive = _grow("abductive", schema0,
                      {k: dict(v) for k, v in base_vecs.items()},
                      {k: dict(v) for k, v in test_vecs.items()},
                      induce_items, test_items, intents, by_intent,
                      rounds, per_round, min_precision, min_fires, extractor, proposer,
                      nearby=nearby)
    print("growing NAIVE control arm ...")
    naive = _grow("naive", schema0,
                  {k: dict(v) for k, v in base_vecs.items()},
                  {k: dict(v) for k, v in test_vecs.items()},
                  induce_items, test_items, intents, by_intent,
                  rounds, per_round, min_precision, min_fires, extractor, proposer)

    report = {
        "dataset": "banking77", "intents": len(intents),
        "test_sample": len(test_items),
        "params": {"induce_per_intent": induce_per_intent, "rounds": rounds,
                   "per_round": per_round, "min_precision": min_precision,
                   "min_fires": min_fires, "seed": seed},
        "start_arm5": start,
        "abductive_6a": abductive,
        "naive_6n": naive,
        "delta_6a_minus_6n": {
            "rind_coverage": round(abductive["rind_coverage"] - naive["rind_coverage"], 3),
            "rind_correct_of_total": round(
                abductive["rind_correct_of_total"] - naive["rind_correct_of_total"], 3),
        },
        "verdict": "abduction helps if delta > 0 at equal feature budget",
        "provenance": _provenance(),
    }
    ABDUCTION_REPORT.write_text(json.dumps(report, indent=2))
    return report
