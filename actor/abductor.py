"""SupervisorAbductor — three-tier dispatch for the abductive loop.

Tier 1 — committed rule lookup (hygraph.match):
  If the observation text contains a known signature, fire the committed rule.
  Zero LLM cost. Oracle still verifies — the rule is not auto-applied.

Tier 2 — (future) embedding/perceptron ranking over near-miss rules.
  Placeholder: falls through to tier 3 for now.

Tier 3 — LLM fallback (Claude/Sonnet via `claude` CLI):
  Full generation cost. Produces a novel hypothesis + patch.
  On confirmation, the caller should commit the result as a new rule.

Usage in rung6:
  abductor = SupervisorAbductor(repo=repo_path)
  # or with explicit hygraph and fallback:
  abductor = SupervisorAbductor(repo=repo_path, hygraph=my_hygraph, fallback=CodexAbductor(repo))
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any

ACTOR = Path(__file__).resolve().parent

from .hygraph import Hygraph, HYGRAPH_DIR
from .epmem import Epmem
from .commit import extract_signatures


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _observation_text(observation: dict[str, Any]) -> str:
    """Flatten an observation dict to a single string for pattern matching."""
    parts: list[str] = []
    for key in ("cargo_test_all", "cargo_test_target"):
        v = observation.get(key)
        if isinstance(v, dict):
            parts.append(v.get("stderr", ""))
            parts.append(v.get("stdout", ""))
        elif isinstance(v, str):
            parts.append(v)
    # Also include raw string if present
    raw = observation.get("raw", "")
    if isinstance(raw, str):
        parts.append(raw)
    return "\n".join(p for p in parts if p)


def _extract_json(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            val, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(val, dict):
            candidates.append(val)
    return candidates[-1] if candidates else None


def _episode_source(repo: Path, observation: dict[str, Any]) -> str:
    source = observation.get("source") or observation.get("run") or observation.get("run_dir")
    if isinstance(source, str) and source:
        return Path(source).name
    if repo.name == "worktree" and repo.parent.name:
        return repo.parent.name
    return repo.name


def _epmem_context(episodes: list[dict[str, Any]]) -> str:
    lines = []
    for episode in episodes:
        source = episode.get("source", "")
        tier = episode.get("tier_used", "")
        verdict = episode.get("verdict", "")
        hypothesis = str(episode.get("hypothesis", "")).replace("\n", " ")[:80]
        lines.append(f"[{source}] tier{tier} -> {verdict}: {hypothesis}")
    return "\n".join(lines)


def _epmem_lt_context(entries: list[dict[str, Any]]) -> str:
    parts = []
    for entry in entries:
        token = entry.get("token", "")
        total = int(entry.get("total", 0))
        converge_rate = float(entry.get("converge_rate", 0.5))
        parts.append(f"{token}={converge_rate:.0%}conv ({total} seen)")
    return "Prior patterns: " + ", ".join(parts)


# ---------------------------------------------------------------------------
# Proposal dataclass (mirrors rung6.Proposal — kept local to avoid circular import)
# ---------------------------------------------------------------------------

class Proposal:
    def __init__(self, hypothesis: str, diff: str = "", files: dict[str, str] | None = None):
        self.hypothesis = hypothesis
        self.diff = diff
        self.files = files


# ---------------------------------------------------------------------------
# Tier 3 — Claude (Sonnet) fallback
# ---------------------------------------------------------------------------

class ClaudeAbductor:
    """Calls `claude -p <prompt>` as the LLM fallback abductor."""

    def __init__(self, repo: Path):
        self.repo = repo

    def propose(self, observation: dict[str, Any], graph_context: list[dict[str, Any]]) -> Proposal:
        prompt = textwrap.dedent(f"""
            You are the abduction step in an instrumented Rust bug-fixing loop.
            Given the raw observation and graph context, propose exactly one root
            cause hypothesis and one minimal file-content change. Do not apply it.

            Prefer returning complete new file contents for every file you would edit.
            You have read access to the repository at {self.repo}.
            Read the original files first, then return full replacement content.
            Only use a unified diff if full file contents are not practical.

            Return strict JSON:
            {{"hypothesis": "...", "files": {{"src/lib.rs": "full new file contents"}}}}

            Fallback JSON if needed:
            {{"hypothesis": "...", "diff": "diff --git ..."}}

            Observation:
            {json.dumps(observation, indent=2)}

            Graph context (prior hypotheses tried):
            {json.dumps(graph_context, indent=2)}
        """).strip()

        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text",
             "--allowedTools", "Read,Bash"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(self.repo),
            env={**os.environ},
        )
        if proc.returncode != 0:
            raise RuntimeError(f"claude failed (exit {proc.returncode}):\n{proc.stderr[:500]}")

        data = _extract_json(proc.stdout)
        if data is None:
            raise RuntimeError(f"claude did not return JSON:\n{proc.stdout[:500]}")

        return Proposal(
            hypothesis=data.get("hypothesis", ""),
            diff=data.get("diff", ""),
            files=data.get("files"),
        )


# ---------------------------------------------------------------------------
# Tier 1 + 3 — SupervisorAbductor
# ---------------------------------------------------------------------------

class SupervisorAbductor:
    """Three-tier abductor: rule lookup → (future ranker) → LLM fallback.

    After the caller confirms a fix (trajectory == convergent and test passes),
    call `record_outcome(proposal, observation, confirmed=True)` to commit the
    winning hypothesis as a new rule.
    """

    def __init__(
        self,
        repo: Path,
        hygraph: Hygraph | None = None,
        fallback: Any | None = None,
        epmem: Epmem | None = None,
    ):
        self.repo = repo
        self.hygraph = hygraph or Hygraph()
        self.fallback = fallback or ClaudeAbductor(repo)
        self.epmem = epmem or Epmem()
        self._last_obs_id: str | None = None
        self._last_hyp_id: str | None = None
        self._used_rule: bool = False
        self._pending_episode: dict[str, Any] | None = None
        self._last_episode_id: str | None = None
        self._consecutive_divergences: int = 0
        self._last_obs_text: str = ""

    def propose(self, observation: dict[str, Any], graph_context: list[dict[str, Any]]) -> Proposal:
        obs_text = _observation_text(observation)
        self._last_obs_text = obs_text
        source = _episode_source(self.repo, observation)
        self._pending_episode = None

        # Tier 1: committed rule lookup
        rule = self.hygraph.match(obs_text)
        if rule:
            self._used_rule = True
            self._last_obs_id = None
            self._last_hyp_id = rule.id
            self._pending_episode = {
                "observation_text": obs_text,
                "tier_used": 1,
                "hypothesis": rule.content.get("hypothesis", ""),
                "source": source,
                "inquiry_mode": "abduction",
            }
            return Proposal(
                hypothesis=rule.content.get("hypothesis", ""),
                diff=rule.content.get("diff", ""),
                files=rule.content.get("files"),
            )

        # Tier 2: placeholder — fall through
        self._used_rule = False

        # Tier 3: LLM fallback
        obs_id = self.hygraph.observe(
            {"text": obs_text[:2000], "test_vector": observation.get("test_vector", {})},
        )
        self._last_obs_id = obs_id

        recall = self.epmem.retrieve(obs_text, k=3, source=source)
        priors = self.epmem.retrieve_lt(obs_text, k=5)
        fallback_context = list(graph_context)
        if recall:
            fallback_context.insert(
                0,
                {
                    "type": "episodic_memory",
                    "text": _epmem_context(recall),
                },
            )
        if priors:
            fallback_context.insert(
                1 if recall else 0,
                {
                    "type": "episodic_prior_patterns",
                    "text": _epmem_lt_context(priors),
                },
            )
        proposal = self.fallback.propose(observation, fallback_context)

        hyp_id = self.hygraph.stage(
            {
                "hypothesis": proposal.hypothesis,
                "diff": proposal.diff,
                "files": proposal.files,
            },
            observation=obs_id,
            source="llm",
        )
        self._last_hyp_id = hyp_id
        self._pending_episode = {
            "observation_text": obs_text,
            "tier_used": 3,
            "hypothesis": proposal.hypothesis,
            "source": source,
            "inquiry_mode": "abduction",
        }
        return proposal

    def propose_ranked(
        self,
        observation: dict[str, Any],
        graph_context: list[dict[str, Any]],
        k: int = 3,
    ) -> list[str]:
        """Return ranked root-cause hypothesis texts only.

        This is the tier-2 contract: diagnostics only, no patch/diff/files.
        The current tier-2 ranker is not wired yet, so this dispatches committed
        rules first and falls back to the existing LLM abductor while discarding
        any patch material it returns.
        """
        if k <= 0:
            return []

        obs_text = _observation_text(observation)
        source = _episode_source(self.repo, observation)

        # Tier 1: committed rule lookup
        rule = self.hygraph.match(obs_text)
        if rule:
            hypothesis = (rule.content.get("hypothesis") or "").strip()
            return [hypothesis][:k] if hypothesis else []

        # Tier 2: placeholder — trained ranker will return up to k strings here.

        # Tier 3: LLM fallback, but keep only the diagnosis text.
        recall = self.epmem.retrieve(obs_text, k=3, source=source)
        priors = self.epmem.retrieve_lt(obs_text, k=5)
        fallback_context = list(graph_context)
        if recall:
            fallback_context.insert(
                0,
                {
                    "type": "episodic_memory",
                    "text": _epmem_context(recall),
                },
            )
        if priors:
            fallback_context.insert(
                1 if recall else 0,
                {
                    "type": "episodic_prior_patterns",
                    "text": _epmem_lt_context(priors),
                },
            )
        proposal = self.fallback.propose(observation, fallback_context)
        hypothesis = (proposal.hypothesis or "").strip()
        return [hypothesis][:k] if hypothesis else []

    def record_outcome(self, verdict: str, evidence: dict | None = None) -> None:
        """Record the oracle verdict for the last proposal.

        verdict: one of 'converge', 'diverge', 'oscillate', 'chaos'
        Call with 'converge' when the fix is confirmed; the hypothesis is
        promoted to a committed rule.
        """
        if verdict == "converge":
            self._consecutive_divergences = 0
        else:
            self._consecutive_divergences += 1

        if self._last_hyp_id is None:
            return
        if self._used_rule:
            pending = self._pending_episode
            obs_text = ""
            if pending:
                obs_text = pending.get("observation_text", "")
            success = verdict == "converge"
            self.hygraph.record_replay(self._last_hyp_id, success=success, obs_text=obs_text)
            if not success:
                pairs_path = ACTOR / "data" / "pairs.jsonl"
                if pairs_path.exists() and pending:
                    neg = {
                        "source": pending.get("source", "replay"),
                        "depth": -1,
                        "failing_test": "",
                        "observation": pending.get("observation_text", "")[:4000],
                        "test_vector": {},
                        "hypothesis": pending.get("hypothesis", ""),
                        "trajectory": "divergent",
                        "confirmed": False,
                        "origin": "replay_failure",
                    }
                    with pairs_path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(neg, ensure_ascii=False) + "\n")
            if pending:
                self._last_episode_id = self.epmem.record(
                    pending["observation_text"],
                    pending["tier_used"],
                    pending["hypothesis"],
                    verdict,
                    durable_change_made=False,
                    source=pending.get("source", ""),
                    inquiry_mode="induction",
                )
                self._pending_episode = None
            return

        pending = self._pending_episode
        self.hygraph.perturb(self._last_hyp_id, verdict, evidence or {})
        if verdict == "converge":
            if self._last_obs_id and self._last_obs_id in self.hygraph.nodes:
                obs_node = self.hygraph.nodes[self._last_obs_id]
                obs_text = obs_node.content.get("text", "")
            else:
                obs_text = ""
            sigs = extract_signatures(obs_text)
            if sigs:
                node = self.hygraph.nodes[self._last_hyp_id]
                node.content["signatures"] = sigs
                node.content["signature"] = sigs[0]
            self.hygraph.commit(self._last_hyp_id)
        else:
            reason = (evidence or {}).get("summary", verdict)
            self.hygraph.retract(self._last_hyp_id, reason)
        if pending:
            self._last_episode_id = self.epmem.record(
                pending["observation_text"],
                pending["tier_used"],
                pending["hypothesis"],
                verdict,
                durable_change_made=(verdict == "converge"),
                source=pending.get("source", ""),
                inquiry_mode="induction",
            )
            self._pending_episode = None

    def record_deduction(self, diff: str, files: dict | None = None) -> None:
        """Record the derived perturbation before the oracle evaluates it."""
        pending = self._pending_episode
        if not pending:
            return

        self.epmem.record(
            pending.get("observation_text", ""),
            int(pending.get("tier_used", 0)),
            pending.get("hypothesis", ""),
            "pending",
            durable_change_made=False,
            source=pending.get("source", ""),
            inquiry_mode="deduction",
            extra={
                "diff_size": len(diff),
                "has_files": files is not None,
            },
        )

    @property
    def economy_of_research(self) -> dict:
        summary = self.epmem.summary()
        by_tier = summary.get("by_tier", {})
        by_verdict = summary.get("by_verdict", {})
        total = summary.get("total", 0)
        tier1 = int(by_tier.get("1", 0))
        tier3 = int(by_tier.get("3", 0))
        converge = int(by_verdict.get("converge", 0))
        return {
            "tier1_rate": tier1 / total if total else 0.0,
            "tier3_rate": tier3 / total if total else 0.0,
            "convergence_rate": converge / total if total else 0.0,
            "total_episodes": total,
        }

    @property
    def confidence_score(self) -> float:
        """Estimate of actor's ability to resolve the current problem.

        Starts at 1.0. Decreases with consecutive divergent steps, tier-3-only
        history, and long-term prior patterns with low historical convergence.
        """
        score = 1.0
        score -= 0.16 * min(self._consecutive_divergences, 5)

        economy = self.economy_of_research
        if economy["tier3_rate"] == 1.0 and economy["total_episodes"] > 2:
            score -= 0.1

        lt_priors = self.epmem.retrieve_lt(self._last_obs_text, k=5)
        if lt_priors:
            avg_converge = sum(
                float(prior.get("converge_rate", 0.5)) for prior in lt_priors
            ) / len(lt_priors)
            if avg_converge < 0.3:
                score -= 0.15

        return max(0.0, score)

    def should_give_up(self, threshold: float = 0.25) -> bool:
        """Return True when confidence is too low to justify another attempt."""
        return self.confidence_score < threshold

    @property
    def stats(self) -> dict:
        rules = self.hygraph.committed_rules()
        retracted = [n for n in self.hygraph.nodes.values() if n.status == "retracted"]
        return {
            "committed_rules": len(rules),
            "retracted": len(retracted),
            "last_used_rule": self._used_rule,
            "open_episodes": len(self.epmem.open_episodes()),
            "confidence_score": self.confidence_score,
            "consecutive_divergences": self._consecutive_divergences,
        }
