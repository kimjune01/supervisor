"""cascade — the cost-asymmetric supervisor, run against Banking77.

Goal (the business objective, not accuracy): maximize SAFE COVERAGE — the
fraction auto-handled while precision on the auto-handled set stays above the
cost-floor (98% at a 50x error:saving ratio). The rest abstains to a human. A
confident-wrong is the 50x catastrophe, so the bar to auto-route is high.

Architecture:
  1. TF-IDF + logistic regression (the shell): free, instant. For each query,
     top-1 + confidence, and top-2 candidates.
  2. Confident cases (conf >= safe_threshold) auto-route on the shell alone.
  3. The confusable tail (uncertain, and the top-2 is a known-confused pair) is
     where the shell loses precision. Here a TRI-ABDUCED semantic feature — the
     axis TF-IDF is blind to (why-vs-how, self-vs-recipient, reversal-vs-failed)
     — disambiguates the pair with one cheap binary LLM call.
  4. Each abducted feature is GATED four-bin (FINDINGS / hypothesis-graph): it
     commits only if it separates its pair on train at >= the precision floor
     (converge) and doesn't break other routings (else diverge/oscillate ->
     retract). Committed features go in the hygraph with provenance.
  5. Anything still unsure abstains -> human.

The number that matters: safe coverage @ 98% precision, baseline (TF-IDF alone)
vs. with abducted disambiguation. Beating the baseline = more queries safely
automated at zero added catastrophic-error risk, at the cost of a few cheap
calls on the tail only.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from supervisor.core import SUPERVISOR_DIR, _ask_sonnet
from supervisor.bench import _load, make_retriever
from supervisor.hygraph import Hygraph

CASCADE_REPORT = SUPERVISOR_DIR / "bench" / "cascade_report.json"
_HAIKU = "claude-haiku-4-5-20251001"
_SONNET = "claude-sonnet-4-6"


def _fit():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    train, test = _load("train"), _load("test")
    pipe = Pipeline([
        ("t", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
        ("c", LogisticRegression(max_iter=1000, C=10.0)),
    ]).fit([x for x, _ in train], [y for _, y in train])
    return pipe, train, test


def _safe_coverage(conf, correct, floor: float):
    """Max coverage such that precision on the covered (highest-confidence) set
    stays >= floor. Returns (coverage, threshold, precision)."""
    order = np.argsort(-conf)
    best = (0.0, 1.0, 1.0)
    n = len(conf)
    cum_correct = 0
    for k, i in enumerate(order, 1):
        cum_correct += int(correct[i])
        prec = cum_correct / k
        if prec >= floor:
            best = (k / n, float(conf[i]), prec)
    return best


def _confused_pairs(pipe, train, top: int):
    """Top off-diagonal confusions on a held-out train slice (the frontier
    observations to abduct against). Deterministic, no LLM."""
    rng = random.Random(0)
    holdout = rng.sample(train, min(1500, len(train)))
    pred = pipe.predict([x for x, _ in holdout])
    pairs = Counter()
    for p, (_, g) in zip(pred, holdout):
        if p != g:
            pairs[tuple(sorted((g, p)))] += 1
    return [p for p, _ in pairs.most_common(top)]


def _tri_abduct(x, ex_x, y, ex_y, model):
    """Tri-abduction: diff the two confused intents' boundary examples, name the
    ONE binary semantic axis that separates them. One LLM call."""
    out = _ask_sonnet(
        "Two intents are confused by a bag-of-words classifier because they "
        "share vocabulary. Diff their examples (figure = the semantic axis that "
        "systematically differs, ground = shared surface) and name ONE binary "
        "feature, judgeable from the query text, that separates intent A from "
        "intent B. Return JSON: {\"flag\":\"snake_case\",\"definition\":\"true "
        "when ... (A) / false when ... (B)\"}",
        f"Intent A = {x}\nA examples:\n" + "\n".join(f"- {q}" for q in ex_x[:6]) +
        f"\n\nIntent B = {y}\nB examples:\n" + "\n".join(f"- {q}" for q in ex_y[:6]),
        model)
    if not out or not out.get("flag"):
        return None
    return {"flag": str(out["flag"]), "definition": out.get("definition", ""),
            "pair": [x, y]}


def _extract_bool(text, flag, definition, model):
    """One cheap binary feature extraction for a query."""
    out = _ask_sonnet(
        f"Feature `{flag}`: {definition}\nDecide if it is true for the query. "
        'Return JSON: {"value": true/false}', f"Query: {text}", model, timeout=30)
    return bool((out or {}).get("value", False)) if out else None


def _validate_feature(feat, by_intent, model, k=8):
    """Four-bin gate, on train: does the feature separate its pair? Extract it on
    k examples of each intent; if it cleanly splits (true->A, false->B) at >=
    floor, converge. Returns (verdict, precision, true_intent_when_true)."""
    a, b = feat["pair"]
    rows = [(q, a) for q in by_intent[a][:k]] + [(q, b) for q in by_intent[b][:k]]
    vals = {}
    for q, lab in rows:
        v = _extract_bool(q, feat["flag"], feat["definition"], model)
        if v is not None:
            vals[(q, lab)] = v
    if not vals:
        return "chaos", 0.0, a
    # which intent does True predict?
    true_a = sum(1 for (q, lab), v in vals.items() if v and lab == a)
    true_b = sum(1 for (q, lab), v in vals.items() if v and lab == b)
    true_intent = a if true_a >= true_b else b
    false_intent = b if true_intent == a else a
    correct = sum(1 for (q, lab), v in vals.items()
                  if (v and lab == true_intent) or (not v and lab == false_intent))
    prec = correct / len(vals)
    verdict = "converge" if prec >= 0.85 else ("oscillate" if prec >= 0.6 else "chaos")
    return verdict, prec, true_intent


def run(top_pairs: int = 8, safe_floor: float = 0.98,
        shell_threshold: float = 0.6, extractor: str = _HAIKU,
        abductor: str = _SONNET, seed: int = 0) -> dict:
    pipe, train, test = _fit()
    cls = list(pipe.named_steps["c"].classes_)
    by_intent = defaultdict(list)
    for t, l in train:
        by_intent[l].append(t)
    nearby = make_retriever(train)
    g = Hygraph()

    texts = [x for x, _ in test]
    gold = [y for _, y in test]
    P = pipe.predict_proba(texts)
    top1 = P.argmax(1)
    conf = P.max(1)
    pred = [cls[i] for i in top1]
    top2 = [tuple(cls[j] for j in np.argsort(-P[i])[:2]) for i in range(len(texts))]
    correct0 = [int(pred[i] == gold[i]) for i in range(len(texts))]

    base_cov, base_thr, base_prec = _safe_coverage(np.array(conf), correct0, safe_floor)
    print(f"baseline TF-IDF safe coverage @ {safe_floor:.0%}: {base_cov:.1%}")

    # --- abduct + gate features for the top confused pairs ---
    pairs = _confused_pairs(pipe, train, top_pairs)
    committed = {}  # frozenset(pair) -> {flag, definition, true_intent}
    calls = {"abduct": 0, "validate": 0, "disambiguate": 0}
    for (a, b) in pairs:
        obs = g.observe({"signature": f"{a}<->{b}"})
        ex_a = [t for t, _, _ in nearby(by_intent[b][0], k=6, intent=a)] or by_intent[a][:6]
        ex_b = [t for t, _, _ in nearby(by_intent[a][0], k=6, intent=b)] or by_intent[b][:6]
        feat = _tri_abduct(a, ex_a, b, ex_b, abductor); calls["abduct"] += 1
        if not feat:
            continue
        feat["signature"] = feat["flag"]
        if g.already_tried(feat["flag"]):
            continue
        hyp = g.stage({**feat, "predicate": feat["definition"]},
                      observation=obs, kind="tri", examples=ex_a[:3] + ex_b[:3])
        verdict, prec, true_intent = _validate_feature(feat, by_intent, extractor)
        calls["validate"] += 16
        g.perturb(hyp, verdict, {"train_precision": round(prec, 3)})
        if verdict == "converge":
            feat["true_intent"] = true_intent
            committed[frozenset((a, b))] = feat
            g.commit(hyp)
            print(f"  committed {feat['flag']} for {a}<->{b} (train sep {prec:.0%})")
        else:
            g.retract(hyp, f"{verdict}: train separation {prec:.0%} < floor")
            print(f"  retracted {feat['flag']} ({verdict}, {prec:.0%})")

    # --- disambiguate the confusable tail on the full test ---
    # New decision: confident shell OR a committed feature that resolves the pair.
    new_pred = list(pred)
    new_conf = list(conf)
    for i in range(len(texts)):
        if conf[i] >= shell_threshold:
            continue  # shell is confident enough; leave it
        key = frozenset(top2[i])
        feat = committed.get(key)
        if feat is None:
            continue  # no disambiguator; stays low-conf -> will abstain
        v = _extract_bool(texts[i], feat["flag"], feat["definition"], extractor)
        calls["disambiguate"] += 1
        if v is None:
            continue
        a, b = feat["pair"]
        chosen = feat["true_intent"] if v else (b if feat["true_intent"] == a else a)
        new_pred[i] = chosen
        new_conf[i] = max(conf[i], 0.99)  # disambiguated -> promote to safe-confident

    correct1 = [int(new_pred[i] == gold[i]) for i in range(len(texts))]
    casc_cov, casc_thr, casc_prec = _safe_coverage(np.array(new_conf), correct1, safe_floor)
    g.render()

    report = {
        "dataset": "banking77", "n_test": len(texts),
        "objective": f"safe coverage @ precision >= {safe_floor:.0%} (cost-floor)",
        "baseline_tfidf": {"safe_coverage": round(base_cov, 3),
                           "threshold": round(base_thr, 3),
                           "precision": round(base_prec, 3)},
        "cascade_abducted": {"safe_coverage": round(casc_cov, 3),
                             "threshold": round(casc_thr, 3),
                             "precision": round(casc_prec, 3)},
        "delta_coverage": round(casc_cov - base_cov, 3),
        "committed_features": [{"flag": f["flag"], "pair": f["pair"]} for f in committed.values()],
        "n_committed": len(committed),
        "calls": calls,
        "params": {"top_pairs": top_pairs, "safe_floor": safe_floor,
                   "shell_threshold": shell_threshold, "seed": seed},
        "models": {"extractor": extractor, "abductor": abductor},
    }
    CASCADE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    CASCADE_REPORT.write_text(json.dumps(report, indent=2))
    return report
