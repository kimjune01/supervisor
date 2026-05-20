"""supervisor — the encoding loop as a higher-order function.

Supplement an expert system and resolve its residue via LLM calls. No weight
training: a frozen corpus + a stock model, online, auditable, propose-only.

Public surface:
    from supervisor import supervise, SupervisorSpec, Observation
"""

from supervisor.core import Observation, SupervisorSpec, supervise

__all__ = ["supervise", "SupervisorSpec", "Observation"]
