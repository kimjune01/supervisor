"""hygraph — the hypothesis graph, the supervisor's semantic memory (SMEM).

Knowledge is a graph with a frontier (june.kim/hypothesis-graph). Nodes are what
was learned; edges are open questions (hypotheses) pointing at experiments. Here:

  nodes:
    observation — a surprising failure (a confused intent pair, a misroute)
    hypothesis  — a candidate rule/feature, staged, not yet committed
    rule        — a committed encoding (survived perturbation)
  edges (Peirce's triangle + bookkeeping):
    abductive   observation -> hypothesis   (the diff suggested this)
    deductive   hypothesis  -> prediction   (if this rule, then these routings)
    inductive   experiment  -> verdict      (tested; the four-bin shape)
    supersedes  rule -> rule                (a better rule replaced an older)
    depends_on  rule -> rule                (B fixed a confusion A introduced)

Every node carries provenance: who spawned it, which abduction kind (bi/tri),
the boundary examples diffed, the perturbation verdict, commit/retract history.
That makes `why(rule)` answerable and the whole reasoning auditable — the thing
SOAR's chunking never had (no version control on learned productions).

Persistence is an append-only event log (the git-style history) plus a
materialized view. The log IS the graph's edges; the view is the queryable cache.
A frozen corpus keeps the cache coherent; `archive()` is the broom that keeps it
legible (FINDINGS #37).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

from supervisor.core import SUPERVISOR_DIR

HYGRAPH_DIR = SUPERVISOR_DIR / "hygraph"
LOG_PATH = HYGRAPH_DIR / "log.jsonl"        # append-only edge/event log
VIEW_PATH = HYGRAPH_DIR / "view.json"       # materialized node view
ARCHIVE_PATH = HYGRAPH_DIR / "archive.jsonl"

NODE_TYPES = ("observation", "hypothesis", "rule")
# Four-bin perturbation verdict (june.kim/hypothesis-graph), each names a next move.
VERDICTS = {
    "converge":  "absorbed cleanly, no past-correct case flipped -> commit",
    "diverge":   "cascades; breaks other routings -> test dependents, don't commit",
    "oscillate": "fixes X but breaks Y -> abduct a disambiguator at the interface",
    "chaos":     "extraction/routing unstable -> re-decompose (feature too vague)",
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _nid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class Node:
    id: str
    type: str                       # observation | hypothesis | rule
    content: dict                   # the payload (the confusion, the rule, ...)
    status: str = "open"            # open | staged | committed | retracted | superseded
    provenance: dict = field(default_factory=dict)   # spawned_by, abduction kind, examples
    verdict: str | None = None      # one of VERDICTS once perturbed
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)


class Hygraph:
    """The SMEM. Append-only log + materialized node view + edge list."""

    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.edges: list[dict] = []           # {src, dst, kind, ts}
        self._load()

    # ---- persistence ----
    def _load(self) -> None:
        if VIEW_PATH.exists():
            try:
                v = json.loads(VIEW_PATH.read_text())
                self.nodes = {n["id"]: Node(**n) for n in v.get("nodes", [])}
                self.edges = v.get("edges", [])
            except (json.JSONDecodeError, OSError, TypeError):
                self.nodes, self.edges = {}, []

    def _emit(self, event: str, **payload) -> None:
        HYGRAPH_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps({"ts": _now(), "event": event, **payload}) + "\n")

    def _flush(self) -> None:
        HYGRAPH_DIR.mkdir(parents=True, exist_ok=True)
        VIEW_PATH.write_text(json.dumps({
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": self.edges,
        }, indent=2))

    def _link(self, src: str, dst: str, kind: str) -> None:
        self.edges.append({"src": src, "dst": dst, "kind": kind, "ts": _now()})

    # ---- node ops ----
    def observe(self, content: dict, spawned_by: str | None = None) -> str:
        """Record a surprising failure (a confused pair, a misroute) as a
        frontier observation node."""
        n = Node(id=_nid("obs"), type="observation", content=content,
                 provenance={"spawned_by": spawned_by})
        self.nodes[n.id] = n
        self._emit("observe", id=n.id, content=content)
        self._flush()
        return n.id

    def stage(self, content: dict, *, observation: str, kind: str,
              examples: list | None = None) -> str:
        """Stage a candidate hypothesis (rule/feature) abduced from an
        observation. `kind` in {bi, tri}; `examples` are the diffed boundary."""
        n = Node(id=_nid("hyp"), type="hypothesis", content=content, status="staged",
                 provenance={"observation": observation, "abduction": kind,
                             "examples": examples or []})
        self.nodes[n.id] = n
        self._link(observation, n.id, "abductive")
        self._emit("stage", id=n.id, observation=observation, kind=kind, content=content)
        self._flush()
        return n.id

    def perturb(self, hyp_id: str, verdict: str, evidence: dict) -> None:
        """Record the four-bin perturbation verdict on a staged hypothesis
        (the inductive edge: experiment -> shape)."""
        assert verdict in VERDICTS, f"unknown verdict {verdict}"
        n = self.nodes[hyp_id]
        n.verdict = verdict
        n.provenance["perturbation"] = {"verdict": verdict, "evidence": evidence, "ts": _now()}
        n.updated = _now()
        self._emit("perturb", id=hyp_id, verdict=verdict, evidence=evidence)
        self._flush()

    def commit(self, hyp_id: str, *, supersedes: str | None = None,
               depends_on: list[str] | None = None) -> str:
        """Promote a staged hypothesis to a committed rule (it converged)."""
        n = self.nodes[hyp_id]
        n.type = "rule"
        n.status = "committed"
        n.updated = _now()
        if supersedes and supersedes in self.nodes:
            self.nodes[supersedes].status = "superseded"
            self._link(hyp_id, supersedes, "supersedes")
        for dep in (depends_on or []):
            self._link(hyp_id, dep, "depends_on")
        self._emit("commit", id=hyp_id, supersedes=supersedes, depends_on=depends_on or [])
        self._flush()
        return hyp_id

    def retract(self, hyp_id: str, reason: str) -> None:
        """Discard a staged hypothesis (it diverged/oscillated/chaos'd). The
        reason is kept so the next abduction routes around this dead branch."""
        n = self.nodes[hyp_id]
        n.status = "retracted"
        n.provenance["retract_reason"] = reason
        n.updated = _now()
        self._emit("retract", id=hyp_id, reason=reason)
        self._flush()

    # ---- queries ----
    def committed_rules(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.status == "committed"]

    def frontier(self) -> list[Node]:
        """Open observations with no committed rule addressing them yet — the
        unexplored edges, i.e. what to inquire into next."""
        addressed = set()
        for n in self.nodes.values():
            if n.status == "committed":
                obs = n.provenance.get("observation")
                if obs:
                    addressed.add(obs)
        return [n for n in self.nodes.values()
                if n.type == "observation" and n.id not in addressed]

    def retracted(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.status == "retracted"]

    def why(self, rule_id: str) -> dict:
        """Provenance for a committed rule: the observation that spawned it, the
        abduction kind, the boundary it diffed, the perturbation verdict, and
        what it supersedes / depends on."""
        n = self.nodes.get(rule_id)
        if n is None:
            return {"error": f"no node {rule_id}"}
        deps = [e["dst"] for e in self.edges if e["src"] == rule_id and e["kind"] == "depends_on"]
        sup = [e["dst"] for e in self.edges if e["src"] == rule_id and e["kind"] == "supersedes"]
        return {
            "id": rule_id, "status": n.status, "content": n.content,
            "spawned_by_observation": n.provenance.get("observation"),
            "abduction": n.provenance.get("abduction"),
            "boundary_examples": n.provenance.get("examples", [])[:6],
            "perturbation": n.provenance.get("perturbation"),
            "supersedes": sup, "depends_on": deps,
        }

    def already_tried(self, signature: str) -> Node | None:
        """Cache check: has a hypothesis with this signature been retracted? If
        so the caller skips re-abducting it (the enriched reject-cache)."""
        for n in self.nodes.values():
            if n.content.get("signature") == signature and n.status == "retracted":
                return n
        return None

    def to_markdown(self) -> str:
        """Render the graph as a legible markdown view — the human/LLM-native
        projection of the structured store. The JSON is for free code queries;
        this is for eyes and for prompt context. (Your instinct that markdown is
        the right SMEM surface is correct; this keeps it, and adds the queries.)"""
        rules = self.committed_rules()
        frontier = self.frontier()
        retracted = self.retracted()
        out = ["# Hypothesis graph (SMEM)", ""]
        out.append(f"_committed: {len(rules)} · frontier: {len(frontier)} · "
                   f"retracted: {len(retracted)}_\n")
        out.append("## Committed rules\n")
        for n in rules:
            w = self.why(n.id)
            out.append(f"- **{n.content.get('signature', n.id)}** "
                       f"({n.provenance.get('abduction','?')}-abduction, "
                       f"verdict={n.verdict})")
            out.append(f"  - why: from observation `{w['spawned_by_observation']}`; "
                       f"{n.content.get('predicate','')}")
            if w["depends_on"]:
                out.append(f"  - depends_on: {w['depends_on']}")
        out.append("\n## Frontier (open, un-encoded)\n")
        for n in frontier:
            out.append(f"- `{n.id}` {n.content.get('signature', n.content)}")
        out.append("\n## Retracted (dead branches — don't re-abduct)\n")
        for n in retracted:
            out.append(f"- {n.content.get('signature', n.id)} — "
                       f"{n.provenance.get('retract_reason','')}")
        return "\n".join(out) + "\n"

    def render(self, path: Path | None = None) -> Path:
        path = path or (HYGRAPH_DIR / "hygraph.md")
        HYGRAPH_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown())
        return path

    def archive(self, keep_recent_retracts: int = 20) -> int:
        """Broom: move old retracted/superseded nodes to a cold log so the live
        view stays legible (FINDINGS #37). Returns count archived."""
        cold = [n for n in self.nodes.values()
                if n.status in ("retracted", "superseded")]
        cold.sort(key=lambda n: n.updated)
        to_archive = cold[:-keep_recent_retracts] if len(cold) > keep_recent_retracts else []
        if to_archive:
            HYGRAPH_DIR.mkdir(parents=True, exist_ok=True)
            with open(ARCHIVE_PATH, "a") as f:
                for n in to_archive:
                    f.write(json.dumps(asdict(n)) + "\n")
                    del self.nodes[n.id]
            self._flush()
        return len(to_archive)
