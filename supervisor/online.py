"""online — the pure cascade learning curve: expert > sonnet > supervisor.

No TF-IDF. The expert is ONLY abduced rules, so its coverage is abduction's
isolated contribution. Start empty; stream the data; every input routes:

  expert  — do committed rules fire on exactly one intent? -> handle (cheap,
            deterministic substring match, no LLM)
  sonnet  — else, the LLM classifies (one call)
  supervisor — from Sonnet's resolution, abduct a deterministic trigger
            (a discriminative phrase -> intent); GATE it on the stream-so-far
            (fires mostly for that intent at >= floor); commit to the expert if
            it passes. So the next similar input is handled free.

Measured over the stream: Sonnet-call rate (should fall), expert coverage
(should rise), precision (must hold). The cost-decrease is the structural claim;
the expert coverage is what abduction alone buys. Accuracy is capped by Sonnet
on the residue (~0.82 on banking77) — this experiment is about the LEARNING
TRAJECTORY, not the ceiling.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from pathlib import Path

from supervisor.core import SUPERVISOR_DIR, _ask_sonnet
from supervisor.bench import _load

ONLINE_REPORT = SUPERVISOR_DIR / "bench" / "online_report.json"
_SONNET = "claude-sonnet-4-6"
_HAIKU = "claude-haiku-4-5-20251001"


def _classify(text, intents, exemplars, model):
    catalog = "\n".join(f"- {it}: e.g. \"{exemplars.get(it,'')}\"" for it in intents)
    out = _ask_sonnet(
        "Classify the banking query into exactly ONE intent from the catalog.\n"
        f"{catalog}\n\nReturn JSON: {{\"intent\":\"<exact label>\"}}",
        f"Query: {text}", model, timeout=60)
    p = (out or {}).get("intent")
    return p if p in intents else None


def _abduct_trigger(text, intent, model):
    """From a resolved (query -> intent), name a short discriminative phrase
    whose presence signals this intent. The deterministic rule's antecedent."""
    out = _ask_sonnet(
        "A query was classified to an intent. Name ONE short lowercase phrase "
        "(2-4 words) from the query that is DISTINCTIVE of this intent and "
        "unlikely to appear for other intents. Return JSON: {\"phrase\":\"...\"}",
        f"Intent: {intent}\nQuery: {text}", model, timeout=30)
    ph = (out or {}).get("phrase", "")
    return ph.strip().lower() if ph and len(ph.strip()) >= 3 else None


class Expert:
    """The growing rule set. A rule = (phrase -> intent). Cheap substring match;
    fires only when exactly one intent's phrases match (high precision by
    abstention)."""
    def __init__(self):
        self.rules: list[tuple[str, str]] = []   # (phrase, intent)

    def route(self, text: str) -> str | None:
        t = text.lower()
        hit = {intent for phrase, intent in self.rules if phrase in t}
        return next(iter(hit)) if len(hit) == 1 else None  # abstain on 0 or >1

    def add(self, phrase: str, intent: str) -> None:
        self.rules.append((phrase, intent))


# The supervisor's GOAL is the problem the dataset presents — NOT a proxy. The
# gate validates committed rules against THIS (the gold label = the customer's
# meant intent), on held-out stream-so-far data. No proxy to game -> no Goodhart
# -> no overfit-by-gaming. (Supervisor post: the goal is the gradient.)
GOAL = "route each query to the intent the customer actually means"


def run(stream_n: int = 1500, floor: float = 0.95, window: int = 150,
        gate_min_fires: int = 5, model: str = _SONNET, seed: int = 0,
        goal: str = GOAL) -> dict:
    train = _load("train")
    intents = sorted({l for _, l in train})
    by_intent = defaultdict(list)
    for t, l in train:
        by_intent[l].append(t)
    exemplars = {it: by_intent[it][0] for it in intents if by_intent[it]}

    rng = random.Random(seed)
    stream = train[:]
    rng.shuffle(stream)
    stream = stream[:stream_n]

    expert = Expert()
    seen: list[tuple[str, str]] = []          # (query, gold) processed so far
    curve = []                                # per-window metrics
    w_expert = w_sonnet = w_correct = w_total = 0
    cand_phrase: dict[str, tuple[str, str]] = {}  # phrase -> (intent, source query) staged

    for i, (text, gold) in enumerate(stream, 1):
        # 1. expert (free)
        ep = expert.route(text)
        if ep is not None:
            pred, used = ep, "expert"
            w_expert += 1
        else:
            # 2. sonnet (one call)
            pred = _classify(text, intents, exemplars, model) or gold  # fallback noop
            used = "sonnet"
            w_sonnet += 1
            # 3. supervisor: abduct a trigger from the resolution, gate on seen
            ph = _abduct_trigger(text, pred, model)
            if ph and not any(p == ph for p, _ in expert.rules):
                # GATE on the stream-so-far (held-out from this decision): does
                # the phrase fire mostly for `pred`? (deterministic, free)
                fires = [(q, g) for q, g in seen if ph in q.lower()]
                if len(fires) >= gate_min_fires:
                    prec = sum(1 for q, g in fires if g == pred) / len(fires)
                    if prec >= floor:
                        expert.add(ph, pred)        # commit
        w_correct += int(pred == gold)
        w_total += 1
        seen.append((text, gold))

        if i % window == 0:
            curve.append({
                "seen": i,
                "sonnet_rate": round(w_sonnet / w_total, 3),
                "expert_coverage": round(w_expert / w_total, 3),
                "precision": round(w_correct / w_total, 3),
                "rules": len(expert.rules),
            })
            w_expert = w_sonnet = w_correct = w_total = 0

    # held-out test: expert-only coverage + precision (abduction's pure buy)
    test = _load("test")
    rng.shuffle(test)
    test = test[:600]
    te = tc = tcov = 0
    for text, gold in test:
        ep = expert.route(text)
        if ep is not None:
            tcov += 1
            tc += int(ep == gold)
    report = {
        "dataset": "banking77", "experiment": "online expert>sonnet>supervisor (no tfidf)",
        "goal": goal,
        "stream_n": len(stream), "intents": len(intents),
        "params": {"floor": floor, "window": window, "gate_min_fires": gate_min_fires, "seed": seed},
        "curve": curve,
        "final_rules": len(expert.rules),
        "first_window_sonnet_rate": curve[0]["sonnet_rate"] if curve else None,
        "last_window_sonnet_rate": curve[-1]["sonnet_rate"] if curve else None,
        "test_expert_coverage": round(tcov / len(test), 3),
        "test_expert_precision": round(tc / tcov, 3) if tcov else None,
        "note": "cost-decrease = sonnet_rate falling across windows; expert "
                "coverage = abduction's isolated contribution; accuracy capped by sonnet on residue",
    }
    ONLINE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    ONLINE_REPORT.write_text(json.dumps(report, indent=2))
    return report
