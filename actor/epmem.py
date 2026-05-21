"""Episodic memory for recent abductive debugging steps.

Hygraph stores durable semantic rules. Epmem stores the bounded tape of recent
specific episodes so tier-3 abduction can recall similar past attempts.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

ACTOR = Path(__file__).resolve().parent
EPMEM_PATH = ACTOR / "data" / "epmem" / "tape.jsonl"
LONGTERM_PATH = ACTOR / "data" / "epmem" / "longterm.jsonl"
LT_SUMMARY_MIN_COUNT = 5

VERDICTS = {"converge", "diverge", "oscillate", "chaos", "pending"}
INQUIRY_MODES = {"abduction", "deduction", "induction"}
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


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _eid() -> str:
    return f"ep-{uuid.uuid4().hex[:8]}"


def _tokens(text: str) -> set[str]:
    return {
        tok.lower()
        for tok in TOKEN_RE.findall(text)
        if len(tok) >= 5 and tok.lower() not in RUST_NOISE
    }


def _entropy(entry: dict[str, Any]) -> float:
    converge = int(entry.get("converge", 0))
    diverge = int(entry.get("diverge", 0))
    denom = converge + diverge
    if denom <= 0:
        return 1.0
    p = converge / denom
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


def _converge_rate(entry: dict[str, Any]) -> float:
    converge = int(entry.get("converge", 0))
    diverge = int(entry.get("diverge", 0))
    denom = converge + diverge
    if denom <= 0:
        return 0.5
    return converge / denom


class Epmem:
    def __init__(
        self,
        path: Path = EPMEM_PATH,
        max_episodes: int = 200,
        max_lt_tokens: int = 2000,
    ):
        self.path = path
        self.longterm_path = path.parent / LONGTERM_PATH.name
        self.max_episodes = max_episodes
        self.max_lt_tokens = max_lt_tokens
        self.episodes: list[dict[str, Any]] = []
        self.longterm: dict[str, dict[str, Any]] = {}
        self._load_longterm()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return

        episodes: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                episodes.append(item)
        evicted = episodes[:-self.max_episodes] if self.max_episodes > 0 else episodes
        for episode in evicted:
            self._evict_to_longterm(episode)
        self.episodes = episodes[-self.max_episodes :] if self.max_episodes > 0 else []
        if len(episodes) > self.max_episodes:
            self._rewrite()

    def _load_longterm(self) -> None:
        if not self.longterm_path.exists():
            return

        longterm: dict[str, dict[str, Any]] = {}
        for line in self.longterm_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(item, dict):
                continue
            token = item.get("token")
            if not isinstance(token, str) or not token:
                continue
            longterm[token] = {
                "token": token,
                "total": int(item.get("total", 0)),
                "converge": int(item.get("converge", 0)),
                "diverge": int(item.get("diverge", 0)),
                "other": int(item.get("other", 0)),
                "last_seen": str(item.get("last_seen", "")),
            }
        self.longterm = longterm
        self._trim_longterm()

    def _append(self, episode: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(episode, sort_keys=True) + "\n")

    def _rewrite(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            for episode in self.episodes:
                f.write(json.dumps(episode, sort_keys=True) + "\n")

    def _flush_longterm(self) -> None:
        self.longterm_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.longterm_path, "w", encoding="utf-8") as f:
            for token in sorted(self.longterm):
                f.write(json.dumps(self.longterm[token], sort_keys=True) + "\n")

    def _trim_longterm(self) -> None:
        changed = False
        while len(self.longterm) > self.max_lt_tokens:
            token = sorted(
                self.longterm,
                key=lambda tok: (
                    -_entropy(self.longterm[tok]),
                    str(self.longterm[tok].get("last_seen", "")),
                    tok,
                ),
            )[0]
            del self.longterm[token]
            changed = True
        if changed:
            self._flush_longterm()

    def _evict_to_longterm(self, episode: dict) -> None:
        """Fold an evicted short-term episode into long-term token counters."""
        verdict = str(episode.get("verdict", "unknown"))
        bucket = verdict if verdict in {"converge", "diverge"} else "other"
        seen = _now()

        for token in _tokens(str(episode.get("observation_text", ""))):
            entry = self.longterm.setdefault(
                token,
                {
                    "token": token,
                    "total": 0,
                    "converge": 0,
                    "diverge": 0,
                    "other": 0,
                    "last_seen": seen,
                },
            )
            entry["total"] = int(entry.get("total", 0)) + 1
            entry[bucket] = int(entry.get(bucket, 0)) + 1
            entry["last_seen"] = seen

        self._trim_longterm()
        self._flush_longterm()

    def record(
        self,
        observation_text: str,
        tier_used: int,
        hypothesis: str,
        verdict: str,
        durable_change_made: bool = False,
        source: str = "",
        inquiry_mode: str = "abduction",
        extra: dict[str, Any] | None = None,
    ) -> str:
        """Append episode, trim to max_episodes, return episode id."""
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict {verdict!r}")
        if inquiry_mode not in INQUIRY_MODES:
            raise ValueError(f"unknown inquiry mode {inquiry_mode!r}")

        episode = {
            "id": _eid(),
            "ts": _now(),
            "source": source,
            "observation_text": observation_text[:1000],
            "tier_used": tier_used,
            "hypothesis": hypothesis,
            "verdict": verdict,
            "inquiry_mode": inquiry_mode,
            "durable_change_made": durable_change_made,
            "open": verdict != "converge" and not durable_change_made,
        }
        if extra:
            episode.update(extra)
        self.episodes.append(episode)
        self._append(episode)
        if len(self.episodes) > self.max_episodes:
            evicted = (
                self.episodes[:-self.max_episodes]
                if self.max_episodes > 0
                else self.episodes
            )
            for old_episode in evicted:
                self._evict_to_longterm(old_episode)
            self.episodes = self.episodes[-self.max_episodes :] if self.max_episodes > 0 else []
            self._rewrite()
        return episode["id"]

    def resolve(self, episode_id: str) -> None:
        """Mark an open episode as resolved (durable change was made after the fact)."""
        changed = False
        for episode in self.episodes:
            if episode.get("id") == episode_id:
                episode["open"] = False
                episode["durable_change_made"] = True
                changed = True
                break
        if changed:
            self._rewrite()

    def retrieve(self, observation_text: str, k: int = 3, source: str = "") -> list[dict]:
        """Return k most relevant past episodes for this observation.

        Relevance is the count of shared significant tokens between observation
        texts. Significant tokens are alphanumeric words >= 5 chars, excluding
        common Rust test-output noise.
        """
        if k <= 0:
            return []

        query_tokens = _tokens(observation_text)
        if not query_tokens:
            return []

        scored: list[tuple[int, int, dict[str, Any]]] = []
        for idx, episode in enumerate(self.episodes):
            if source and episode.get("source") == source:
                continue
            overlap = len(query_tokens & _tokens(str(episode.get("observation_text", ""))))
            if overlap:
                scored.append((overlap, idx, episode))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [episode for _, _, episode in scored[:k]]

    def lt_summary(self) -> dict:
        """Return the most predictive long-term token patterns."""
        candidates = [
            {**entry, "converge_rate": _converge_rate(entry)}
            for entry in self.longterm.values()
            if int(entry.get("total", 0)) >= LT_SUMMARY_MIN_COUNT
        ]
        top_converge = sorted(
            candidates,
            key=lambda entry: (
                entry["converge_rate"],
                int(entry.get("total", 0)),
                str(entry.get("last_seen", "")),
            ),
            reverse=True,
        )[:5]
        top_diverge = sorted(
            candidates,
            key=lambda entry: (
                1.0 - entry["converge_rate"],
                int(entry.get("total", 0)),
                str(entry.get("last_seen", "")),
            ),
            reverse=True,
        )[:5]
        return {
            "total_tokens": len(self.longterm),
            "top_converge": top_converge,
            "top_diverge": top_diverge,
        }

    def retrieve_lt(self, observation_text: str, k: int = 5, min_count: int = 3) -> list[dict]:
        """Return discriminative long-term token priors present in observation_text."""
        if k <= 0:
            return []

        query_tokens = _tokens(observation_text)
        entries = []
        for token in query_tokens:
            entry = self.longterm.get(token)
            if entry is None:
                continue
            if int(entry.get("total", 0)) < min_count:
                continue
            converge_rate = _converge_rate(entry)
            entries.append({**entry, "converge_rate": converge_rate})

        entries.sort(
            key=lambda entry: (
                abs(float(entry["converge_rate"]) - 0.5),
                int(entry.get("total", 0)),
                str(entry.get("last_seen", "")),
            ),
            reverse=True,
        )
        return entries[:k]

    def open_episodes(self) -> list[dict]:
        """Return all episodes where open=True — unresolved fails needing durable change."""
        return [episode for episode in self.episodes if episode.get("open") is True]

    def summary(self) -> dict:
        """Return {total, open, by_verdict, by_tier, by_mode} counts."""
        by_verdict = Counter(str(ep.get("verdict", "")) for ep in self.episodes)
        by_tier = Counter(str(ep.get("tier_used", "")) for ep in self.episodes)
        by_mode = Counter(str(ep.get("inquiry_mode", "abduction")) for ep in self.episodes)
        return {
            "total": len(self.episodes),
            "open": len(self.open_episodes()),
            "by_verdict": dict(by_verdict),
            "by_tier": dict(by_tier),
            "by_mode": dict(by_mode),
        }
