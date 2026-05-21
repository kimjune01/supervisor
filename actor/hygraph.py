"""Hypothesis graph — semantic memory for the abductive debugger.

Nodes:
  observation — a failing test + compiler output that triggered an investigation
  hypothesis  — a candidate root cause, staged for perturbation
  rule        — a committed encoding: survived perturbation, ready to fire on match

Edges (Peirce's triangle):
  abductive   observation -> hypothesis   (LLM proposed this cause)
  deductive   hypothesis  -> prediction   (if this rule, these tests pass)
  inductive   experiment  -> verdict      (oracle judged it)
  supersedes  rule -> rule
  depends_on  rule -> rule

Each committed rule carries:
  signature   — keyword/pattern extracted from the observation that triggers it
  hypothesis  — the natural-language root cause claim
  diff/files  — the concrete fix that worked
  provenance  — source trace, depth, confidence

Storage: actor/data/hygraph/ (append-only log + materialized view).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

ACTOR = Path(__file__).resolve().parent
HYGRAPH_DIR = ACTOR / "data" / "hygraph"
LOG_PATH    = HYGRAPH_DIR / "log.jsonl"
VIEW_PATH   = HYGRAPH_DIR / "view.json"
ARCHIVE_PATH = HYGRAPH_DIR / "archive.jsonl"
RUST_NOISE = {
    "cargo",
    "test",
    "running",
    "passed",
    "failed",
    "finished",
    "error",
    "warning",
}
TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

VERDICTS = {
    "converge":  "fix confirmed — no regressions",
    "diverge":   "wrong direction — compiler/test rejected",
    "oscillate": "fixes target but breaks regression",
    "chaos":     "unstable / apply failed",
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _nid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in TOKEN_RE.findall(text)
        if len(tok) >= 5 and tok.lower() not in RUST_NOISE
    }


@dataclass
class Node:
    id: str
    type: str        # observation | hypothesis | rule
    content: dict
    status: str = "open"   # open | staged | committed | quarantined | retracted | superseded
    provenance: dict = field(default_factory=dict)
    verdict: str | None = None
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)


class Hygraph:
    def __init__(self, hygraph_dir: Path = HYGRAPH_DIR):
        self.dir = hygraph_dir
        self.nodes: dict[str, Node] = {}
        self.edges: list[dict] = []
        self._load()

    def _load(self) -> None:
        view = self.dir / "view.json"
        if view.exists():
            try:
                v = json.loads(view.read_text())
                self.nodes = {n["id"]: Node(**n) for n in v.get("nodes", [])}
                self.edges = v.get("edges", [])
            except Exception:
                self.nodes, self.edges = {}, []

    def _emit(self, event: str, **payload) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "log.jsonl", "a") as f:
            f.write(json.dumps({"ts": _now(), "event": event, **payload}) + "\n")

    def _flush(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "view.json").write_text(json.dumps({
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": self.edges,
        }, indent=2))

    def _link(self, src: str, dst: str, kind: str) -> None:
        self.edges.append({"src": src, "dst": dst, "kind": kind, "ts": _now()})

    # ---- node ops ----

    def observe(self, content: dict, spawned_by: str | None = None) -> str:
        n = Node(id=_nid("obs"), type="observation", content=content,
                 provenance={"spawned_by": spawned_by})
        self.nodes[n.id] = n
        self._emit("observe", id=n.id, content=content)
        self._flush()
        return n.id

    def stage(self, content: dict, *, observation: str, source: str = "llm") -> str:
        n = Node(id=_nid("hyp"), type="hypothesis", content=content, status="staged",
                 provenance={"observation": observation, "source": source})
        self.nodes[n.id] = n
        self._link(observation, n.id, "abductive")
        self._emit("stage", id=n.id, observation=observation, content=content)
        self._flush()
        return n.id

    def perturb(self, hyp_id: str, verdict: str, evidence: dict) -> None:
        assert verdict in VERDICTS, f"unknown verdict {verdict!r}"
        n = self.nodes[hyp_id]
        n.verdict = verdict
        n.provenance["perturbation"] = {"verdict": verdict, "evidence": evidence, "ts": _now()}
        n.updated = _now()
        self._emit("perturb", id=hyp_id, verdict=verdict, evidence=evidence)
        self._flush()

    def commit(self, hyp_id: str, *, supersedes: str | None = None) -> str:
        n = self.nodes[hyp_id]
        n.type = "rule"
        n.status = "committed"
        n.content["replay_successes"] = 0
        n.content["replay_failures"] = 0
        n.updated = _now()
        if supersedes and supersedes in self.nodes:
            self.nodes[supersedes].status = "superseded"
            self._link(hyp_id, supersedes, "supersedes")
        self._emit("commit", id=hyp_id, supersedes=supersedes)
        self._flush()
        return hyp_id

    def retract(self, hyp_id: str, reason: str) -> None:
        n = self.nodes[hyp_id]
        n.status = "retracted"
        n.provenance["retract_reason"] = reason
        n.updated = _now()
        self._emit("retract", id=hyp_id, reason=reason)
        self._flush()

    def _rule_observation_text(self, rule: Node) -> str:
        candidates = [
            rule.provenance.get("observation"),
            rule.provenance.get("source_trace"),
            rule.content.get("source_trace"),
        ]
        for obs_id in candidates:
            if not isinstance(obs_id, str) or not obs_id:
                continue
            obs = self.nodes.get(obs_id)
            if obs and obs.type == "observation":
                text = obs.content.get("text", "")
                if isinstance(text, str) and text:
                    return text

        for edge in self.edges:
            if edge.get("dst") != rule.id or edge.get("kind") != "abductive":
                continue
            obs = self.nodes.get(str(edge.get("src", "")))
            if obs and obs.type == "observation":
                text = obs.content.get("text", "")
                if isinstance(text, str) and text:
                    return text

        text = rule.content.get("text", "")
        return text if isinstance(text, str) else ""

    def tighten_rule(self, rule_id: str, false_positive_obs_text: str) -> list[str]:
        """Specialize a rule's signatures using a false-positive observation."""
        n = self.nodes[rule_id]
        if n.type != "rule":
            raise ValueError(f"cannot tighten non-rule node {rule_id!r}")

        signatures = list(n.content.get("signatures", []))
        original_text = self._rule_observation_text(n)
        original_tokens = _tokens(original_text)
        false_positive_tokens = _tokens(false_positive_obs_text)
        existing = {str(sig).lower() for sig in signatures}
        discriminative = [
            tok
            for tok in original_tokens - false_positive_tokens
            if tok not in existing
        ]
        discriminative.sort(key=lambda tok: (-len(tok), tok))
        additions = discriminative[:2]
        if not additions:
            return signatures

        signatures.extend(additions)
        n.content["signatures"] = signatures
        if not n.content.get("signature") and signatures:
            n.content["signature"] = signatures[0]
        n.updated = _now()
        self._emit("tighten", rule_id=rule_id, added=additions, signatures=signatures)
        self._flush()
        self.render()
        return signatures

    def record_replay(self, rule_id: str, success: bool, obs_text: str = "") -> None:
        n = self.nodes[rule_id]
        if n.type != "rule":
            raise ValueError(f"cannot record replay for non-rule node {rule_id!r}")

        field = "replay_successes" if success else "replay_failures"
        n.content[field] = int(n.content.get(field, 0)) + 1
        if int(n.content.get("replay_failures", 0)) >= 2:
            signatures_before = list(n.content.get("signatures", []))
            signatures_after = self.tighten_rule(rule_id, obs_text)
            if len(signatures_after) > len(signatures_before):
                n.content["replay_failures"] = 0
                n.status = "committed"
            else:
                n.status = "quarantined"
        n.updated = _now()
        self._emit(
            "replay",
            rule_id=rule_id,
            success=success,
            replay_successes=n.content.get("replay_successes", 0),
            replay_failures=n.content.get("replay_failures", 0),
            status=n.status,
        )
        self._flush()
        self.render()

    # ---- queries ----

    def committed_rules(self, include_quarantined: bool = False) -> list[Node]:
        statuses = {"committed"}
        if include_quarantined:
            statuses.add("quarantined")
        return [n for n in self.nodes.values() if n.type == "rule" and n.status in statuses]

    def already_tried(self, signature: str) -> Node | None:
        """Reject-cache: skip re-proposing a retracted hypothesis with this signature."""
        for n in self.nodes.values():
            if n.content.get("signature") == signature and n.status == "retracted":
                return n
        return None

    def match(self, observation_text: str) -> Node | None:
        """Tier-1 lookup: return a committed rule whose required signatures all appear."""
        obs_lower = observation_text.lower()
        for rule in self.committed_rules(include_quarantined=False):
            signatures = [str(sig).lower() for sig in rule.content.get("signatures", []) if sig]
            if signatures and all(sig in obs_lower for sig in signatures):
                return rule
        return None

    def to_markdown(self) -> str:
        rules = self.committed_rules()
        quarantined = [n for n in self.committed_rules(include_quarantined=True) if n.status == "quarantined"]
        retracted = [n for n in self.nodes.values() if n.status == "retracted"]
        out = ["# Abductive Debugger — Hypothesis Graph", ""]
        out.append(
            f"_committed rules: {len(rules)} · quarantined: {len(quarantined)} · "
            f"retracted: {len(retracted)}_\n"
        )
        out.append("## Committed rules\n")
        for r in rules:
            sigs = ", ".join(f"`{s}`" for s in r.content.get("signatures", []))
            out.append(f"- **{r.content.get('signature', r.id)}** — {sigs}")
            out.append(f"  - hypothesis: {r.content.get('hypothesis', '')[:120]}")
            out.append(
                "  - replay: "
                f"{r.content.get('replay_successes', 0)} successes, "
                f"{r.content.get('replay_failures', 0)} failures"
            )
            src = r.provenance.get("source_trace", "")
            if src:
                out.append(f"  - source: {src}")
        out.append("\n## Quarantined rules\n")
        for r in quarantined:
            sigs = ", ".join(f"`{s}`" for s in r.content.get("signatures", []))
            out.append(f"- **{r.content.get('signature', r.id)}** — {sigs}")
            out.append(f"  - hypothesis: {r.content.get('hypothesis', '')[:120]}")
            out.append(
                "  - replay: "
                f"{r.content.get('replay_successes', 0)} successes, "
                f"{r.content.get('replay_failures', 0)} failures"
            )
        out.append("\n## Retracted (dead branches)\n")
        for n in retracted:
            out.append(f"- {n.content.get('signature', n.id)} — {n.provenance.get('retract_reason', '')}")
        return "\n".join(out) + "\n"

    def render(self, path: Path | None = None) -> Path:
        path = path or (self.dir / "hygraph.md")
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown())
        return path

    def archive(self, keep: int = 20) -> int:
        cold = [n for n in self.nodes.values() if n.status in ("retracted", "superseded")]
        cold.sort(key=lambda n: n.updated)
        to_archive = cold[:-keep] if len(cold) > keep else []
        if to_archive:
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / "archive.jsonl", "a") as f:
                for n in to_archive:
                    f.write(json.dumps(asdict(n)) + "\n")
                    del self.nodes[n.id]
            self._flush()
        return len(to_archive)
