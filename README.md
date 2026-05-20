# supervisor

The encoding loop as a higher-order function. **Supplement an expert system and
resolve its residue via LLM calls — train no weights.**

`supervise(spec)` reads a target's attention channels (andon events, operator
inbox) or a public corpus, clusters recurring `(state, action)` patterns,
runs a four-case switch — **expert > agent > supervisor > human** — via a stock
model, replay-gates the deterministic hoists against the labeled decision
history (with the agent **blinded** from the recorded action), and stages
**propose-only** artifacts plus human-in-the-loop cards. Nothing is auto-applied
and no source is edited.

Properties (of the method): no weight training; online; adapts old policies and
creates new ones; no catastrophic forgetting (idempotence-wall regression
against history); no decay/learning-rate knobs (subsumption by specificity);
reversible + auditable per artifact; per-change alignment moderation; cheap
(inference-only, no GPU); convergent (monoidal composition).

## Install

```sh
uv sync           # or: pip install -e .
```

Requires the `claude` and `gh` CLIs on PATH (used via subprocess; the model runs
on your existing Claude plan, `gh` on your existing GitHub auth).

## Run

```sh
# public-corpus specs (any GitHub contributor):
supervisor run actions-<login>     # their review verdicts vs PR features
supervisor run respond-<login>     # their author-response trajectories
supervisor run corpus-<login>      # their review-comment register
supervisor run respond-<login> --limit 150   # bump the sample for coverage

# sweep-coupled local specs (require a sweep substrate's ~/.sweep logs):
supervisor run switch
supervisor run remit --outcomes    # add the regret/outcome channel

supervisor list                    # staged proposals
supervisor show <name>             # one proposal
supervisor archive <name>          # after you apply or reject it
```

State lives under `~/.supervisor/` (override with `SUPERVISOR_HOME`):
proposals, reject cache, residue log, and the HITL inbox. The sweep-coupled
local specs read `~/.sweep/events.jsonl` (override `SUPERVISOR_EVENTS_LOG`).

## Layout

- `supervisor/core.py` — the `supervise(spec)` loop, the four-case switch, the
  blinded replay gate, propose-only emission. The generalizable harness.
- `supervisor/specs.py` — instantiations. Local (switch/remit/compose, read
  sweep logs) and corpus (contributor/actions/respond, read `gh`), plus the
  regret/outcome channel.
- `supervisor/_deps.py` — the small surface vendored out of sweep (Max-plan
  env-pop, a minimal Message, a jsonl tail reader).
- `supervisor/cli.py` — `supervisor run|list|show|archive`.
