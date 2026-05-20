"""Vendored utilities — the small surface the supervisor needed from sweep.

Extracted so this repo stands alone. Three things: the Max-plan env-pop for
claude subprocesses, a minimal Message dataclass for HITL cards, and a tail
reader for a jsonl event log (used only by the sweep-coupled local specs,
which read ~/.sweep/events.jsonl when a sweep install is present).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def env_without_api_key() -> dict:
    """os.environ minus ANTHROPIC_API_KEY, so the `claude` CLI uses the
    OAuth/Max-plan path instead of billing API credits. (See the sweep
    billing-gemba incident: a stray key in the inherited env silently routed
    every subprocess to metered API spend.)"""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    return env


@dataclass
class Message:
    """One HITL card. Minimal copy of sweep's Message — only the fields the
    supervisor sets when emitting to the operator inbox."""
    msg_id: str
    sender: str
    intent: str
    repo: str | None = None
    pr: int | None = None
    branch: str | None = None
    payload: dict = field(default_factory=dict)
    ts: str = ""
    ledger: list[str] = field(default_factory=list)


# Default event log location. The sweep-coupled local specs (switch/remit/
# compose) read this; the gh-corpus specs (contributor/actions/respond) do
# not touch it. Override with SUPERVISOR_EVENTS_LOG if your substrate writes
# elsewhere.
EVENTS_LOG = Path(
    os.environ.get("SUPERVISOR_EVENTS_LOG", str(Path.home() / ".sweep" / "events.jsonl"))
)


def events_recent(limit: int = 50, kind: str | None = None) -> list[dict]:
    """Tail of the jsonl event log, newest first, optionally filtered by
    `kind`. O(file size) — fine for an offline pass, not a hot path."""
    if not EVENTS_LOG.exists():
        return []
    try:
        lines = EVENTS_LOG.read_text().splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind and r.get("kind") != kind:
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out
