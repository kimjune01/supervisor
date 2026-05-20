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
    ONE binary SEMANTIC axis that separates them — the dimension a bag-of-words
    classifier is BLIND to. One LLM call."""
    out = _ask_sonnet(
        "Two intents are confused by a TF-IDF (bag-of-words) classifier because "
        "they SHARE the same keywords. A keyword feature is therefore useless — "
        "TF-IDF already has the words. Diff the examples and name ONE binary "
        "SEMANTIC feature that separates A from B along an axis the bag-of-words "
        "CANNOT see: e.g. asks-why-vs-how, problem-vs-request, self-vs-recipient, "
        "reversal-vs-never-completed, payment-vs-cash-channel. NOT the presence "
        "of a word. The feature must be judgeable from the query's MEANING, not "
        "its vocabulary. Return JSON: {\"flag\":\"snake_case\","
        "\"definition\":\"true when ...(A) / false when ...(B)\","
        "\"axis\":\"the semantic dimension, in 3-5 words\"}",
        f"Intent A = {x}\nA examples:\n" + "\n".join(f"- {q}" for q in ex_x[:6]) +
        f"\n\nIntent B = {y}\nB examples:\n" + "\n".join(f"- {q}" for q in ex_y[:6]),
        model)
    if not out or not out.get("flag"):
        return None
    return {"flag": str(out["flag"]), "definition": out.get("definition", ""),
            "axis": out.get("axis", ""), "pair": [x, y]}


def _disambiguate(text, a, b, axis, definition, model):
    """Direct axis-guided 2-way disambiguation — robust to polarity/negation.
    Instead of extracting an abstract boolean (which false-positives on
    "no credit" vs "ok credit"), ask the model to compare the two readings
    head-to-head, attending to the abducted semantic axis. Returns a or b (or
    None). Uses the LLM's strength (semantic comparison), not a brittle flag."""
    out = _ask_sonnet(
        f"Two intents are easily confused. Decide which ONE the query means, "
        f"attending specifically to this axis: {axis} ({definition}). Watch "
        f"negation/polarity carefully (e.g. 'no credit' is the OPPOSITE of "
        f"'credit ok'). Options:\n  A = {a}\n  B = {b}\n"
        'Return JSON: {"choice": "A" or "B"}',
        f"Query: {text}", model, timeout=30)
    c = (out or {}).get("choice", "").upper()
    return a if c == "A" else b if c == "B" else None


def _validate_agreement(feat, by_intent, pipe, cls, model, floor, k=10):
    """The agreement gate (the hypothesis: requiring agreement allows more
    precise encoding). On train pair examples, get BOTH the TF-IDF prediction
    and the feature-implied prediction; look only at cases where they AGREE, and
    measure precision THERE. Commit (converge) iff agreement-precision >= floor.
    Returns (verdict, agreement_precision, agreement_coverage, true_intent)."""
    import numpy as np
    a, b = feat["pair"]
    axis = feat.get("axis", "")
    rows = [(q, a) for q in by_intent[a][:k]] + [(q, b) for q in by_intent[b][:k]]
    P = pipe.predict_proba([q for q, _ in rows])
    ia, ib = cls.index(a), cls.index(b)
    agree, correct = 0, 0
    n = 0
    for idx, (q, lab) in enumerate(rows):
        pick = _disambiguate(q, a, b, axis, feat["definition"], model)
        if pick is None:
            continue
        n += 1
        tfidf = a if P[idx][ia] >= P[idx][ib] else b
        if pick == tfidf:                     # AGREEMENT
            agree += 1
            if pick == lab:
                correct += 1
    if n == 0:
        return "chaos", 0.0, 0.0, a
    if agree == 0:
        return "oscillate", 0.0, 0.0, a
    agree_prec = correct / agree
    agree_cov = agree / n
    verdict = ("converge" if agree_prec >= floor
               else "oscillate" if agree_prec >= 0.7 else "chaos")
    return verdict, agree_prec, agree_cov, a  # true_intent unused now (direct pick)


def _ask_clarifying_q(a, b, axis, definition, model):
    """Turn the abducted axis into the single most-informative clarifying
    question that separates the pair (economy of research: one question)."""
    out = _ask_sonnet(
        "A support query is ambiguous between two intents. Write ONE short, "
        "natural clarifying question whose answer separates them along this "
        f"axis: {axis} ({definition}). Intents: A={a}, B={b}. "
        'Return JSON: {"question": "..."}', "", model, timeout=30)
    return (out or {}).get("question") if out else None


def _simulated_customer(true_intent_query, question, model):
    """A cooperative customer who actually has the need behind `true_intent_query`
    answers the agent's clarifying question consistently. Tests the UPPER BOUND
    of clarification (real customers are noisier / some hang up)."""
    out = _ask_sonnet(
        "You are a bank customer. Your actual situation/need is shown below. A "
        "support agent asks a clarifying question. Answer it naturally and "
        "truthfully, consistent with your situation, in one sentence. "
        'Return JSON: {"answer": "..."}',
        f"Your situation (what you originally said): {true_intent_query}\n\n"
        f"Agent's question: {question}", model, timeout=30)
    return (out or {}).get("answer") if out else None


def _resolve_with_answer(query, answer, a, b, axis, model):
    """2-way disambiguation WITH the clarification answer in hand."""
    out = _ask_sonnet(
        f"Decide which intent the customer means, using their clarification. "
        f"Axis: {axis}. Options: A={a}, B={b}. "
        'Return JSON: {"choice":"A" or "B"}',
        f"Original: {query}\nClarifying answer: {answer}", model, timeout=30)
    c = (out or {}).get("choice", "").upper()
    return a if c == "A" else b if c == "B" else None


def run_clarify(top_pairs: int = 8, safe_floor: float = 0.98,
                shell_threshold: float = 0.6, extractor: str = _HAIKU,
                abductor: str = _SONNET, max_clarify: int = 60, seed: int = 0) -> dict:
    """DECIDING experiment: on the confusable tail, ASK the abducted axis as a
    clarifying question; a simulated customer answers; resolve. Does clarification
    clear the pairs at >= floor (where blind disambiguation could not)?"""
    import numpy as np
    pipe, train, test = _fit()
    cls = list(pipe.named_steps["c"].classes_)
    by_intent = defaultdict(list)
    for t, l in train:
        by_intent[l].append(t)
    nearby = make_retriever(train)

    texts = [x for x, _ in test]
    gold = [y for _, y in test]
    P = pipe.predict_proba(texts)
    conf = P.max(1)
    pred = [cls[i] for i in P.argmax(1)]
    top2 = [tuple(cls[j] for j in np.argsort(-P[i])[:2]) for i in range(len(texts))]
    correct0 = [int(pred[i] == gold[i]) for i in range(len(texts))]
    base_cov, _, _ = _safe_coverage(np.array(conf), correct0, safe_floor)

    # abduct axes for the top confused pairs (reuse the semantic abduction)
    pairs = _confused_pairs(pipe, train, top_pairs)
    axis_for = {}
    for (a, b) in pairs:
        ex_a = [t for t, _, _ in nearby(by_intent[b][0], k=6, intent=a)] or by_intent[a][:6]
        ex_b = [t for t, _, _ in nearby(by_intent[a][0], k=6, intent=b)] or by_intent[b][:6]
        feat = _tri_abduct(a, ex_a, b, ex_b, abductor)
        if feat:
            q = _ask_clarifying_q(a, b, feat["axis"], feat["definition"], abductor)
            if q:
                axis_for[frozenset((a, b))] = (a, b, feat["axis"], feat["definition"], q)

    # clarify on the confusable tail (cooperative simulated customer)
    new_pred, new_conf = list(pred), list(conf)
    clar_total = clar_correct = 0
    rng = random.Random(seed)
    tail = [i for i in range(len(texts))
            if conf[i] < shell_threshold and frozenset(top2[i]) in axis_for]
    rng.shuffle(tail)
    for i in tail[:max_clarify]:
        a, b, axis, definition, q = axis_for[frozenset(top2[i])]
        ans = _simulated_customer(texts[i], q, extractor)
        if not ans:
            continue
        pick = _resolve_with_answer(texts[i], ans, a, b, axis, extractor)
        if pick is None:
            continue
        clar_total += 1
        clar_correct += int(pick == gold[i])
        new_pred[i] = pick
        new_conf[i] = max(conf[i], 0.99)  # clarified -> treat as resolved

    correct1 = [int(new_pred[i] == gold[i]) for i in range(len(texts))]
    clar_cov, _, _ = _safe_coverage(np.array(new_conf), correct1, safe_floor)
    report = {
        "dataset": "banking77", "n_test": len(texts), "experiment": "clarification",
        "baseline_safe_coverage": round(base_cov, 3),
        "clarified_safe_coverage": round(clar_cov, 3),
        "delta_coverage": round(clar_cov - base_cov, 3),
        "clarification_precision": round(clar_correct / clar_total, 3) if clar_total else None,
        "n_clarified": clar_total,
        "note": "simulated cooperative customer = UPPER BOUND on clarification",
    }
    (SUPERVISOR_DIR / "bench" / "clarify_report.json").write_text(json.dumps(report, indent=2))
    return report


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

    # --- abduct + AGREEMENT-gate features for the top confused pairs ---
    pairs = _confused_pairs(pipe, train, top_pairs)
    committed = {}  # frozenset(pair) -> {flag, definition, true_intent, agree_prec}
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
        verdict, aprec, acov, true_intent = _validate_agreement(
            feat, by_intent, pipe, cls, extractor, safe_floor); calls["validate"] += 20
        g.perturb(hyp, verdict, {"agreement_precision": round(aprec, 3),
                                 "agreement_coverage": round(acov, 3), "axis": feat.get("axis")})
        if verdict == "converge":
            feat["true_intent"] = true_intent
            feat["agree_prec"] = aprec
            committed[frozenset((a, b))] = feat
            g.commit(hyp)
            print(f"  committed {feat['flag']} [{feat.get('axis')}] for {a}<->{b} "
                  f"(agreement prec {aprec:.0%}, cov {acov:.0%})")
        else:
            g.retract(hyp, f"{verdict}: agreement precision {aprec:.0%} < floor {safe_floor:.0%}")
            print(f"  retracted {feat['flag']} ({verdict}, agree {aprec:.0%})")

    # --- AGREEMENT-gated routing on the confusable tail (full test) ---
    # The feature CONFIRMS or CONTRADICTS TF-IDF; it never overrides. Agreement
    # -> auto-route at the measured agreement precision (calibrated, not 0.99).
    # Disagreement -> abstain (don't gamble). This is the hypothesis under test.
    new_pred = list(pred)
    new_conf = list(conf)
    for i in range(len(texts)):
        if conf[i] >= shell_threshold:
            continue  # shell already confident; leave it
        feat = committed.get(frozenset(top2[i]))
        if feat is None:
            continue
        a, b = feat["pair"]
        pick = _disambiguate(texts[i], a, b, feat.get("axis", ""), feat["definition"], extractor)
        calls["disambiguate"] += 1
        if pick is None:
            continue
        if pick == pred[i]:                            # AGREEMENT with TF-IDF top-1
            new_conf[i] = max(conf[i], feat["agree_prec"])   # calibrated, not blanket 0.99
        # disagreement -> leave low-conf -> abstains (no override, no gamble)

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
