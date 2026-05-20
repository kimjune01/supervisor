# supervisor

Companion code to the trilogy:

1. [**Encoding Expertise**](https://june.kim/encoding-expertise) — one classifier, five strata, an LLM in the residual cell.
2. [**Supervisor**](https://june.kim/supervisor) — the encoding loop one level up, automated.
3. [**Asymptote Learning**](https://june.kim/asymptote-learning) — bootstrap it from a public decision corpus.

**The thesis, in one line:** *supplement an expert system and resolve its residue
via LLM calls — train no weights.* `supervise(spec)` reads a target's attention
channels (or a public corpus), clusters recurring `(state, action)` patterns,
runs a four-case switch — **expert > agent > supervisor > human** — via a stock
model, replay-gates the deterministic hoists against the labeled decision history
(with the agent **blinded** from the recorded action), and stages **propose-only**
artifacts plus human-in-the-loop cards. No gradient step anywhere; nothing
auto-applied; no source edited.

See [`docs/FINDINGS.md`](docs/FINDINGS.md) for the thesis + the load-bearing
findings, and [`REPRODUCE.md`](REPRODUCE.md) to re-run the experiments yourself
(it's a re-executable benchmark, not a prereg — see finding #25).

## Reading this with the trilogy

Every concept in the posts has a single home in the code:

| trilogy concept | post | where in code |
|---|---|---|
| the higher-order loop `supervise(spec)` | Supervisor | `core.py` `supervise()` |
| spec = goal + channels + history (parameterization) | Supervisor | `core.py` `SupervisorSpec` |
| Identity / precondition (N≥3, dedup by case) | Encoding Expertise | `core.py` `supervise()` clustering + `_support()` |
| Legal moves / postcondition (the enum wall) | Encoding Expertise | `core.py` `CASE_ENUM`, enum check in `supervise()` |
| Live state / CLI tool (deterministic facts) | Encoding Expertise | `specs.py` gather callables (`gh`), `_gh_pr_outcome` |
| Repeats / cache (don't re-propose a reject) | Encoding Expertise | `core.py` `REJECT_CACHE`, `_load_rejects` |
| Residue / LLM nucleus | Encoding Expertise | `core.py` `_ask_sonnet`, `_classify_cluster` |
| four-case switch (expert>agent>supervisor>human) | Supervisor | `core.py` `CASE_ENUM` + dispatch in `supervise()` |
| inside vs outside clamp (cli-tool vs pre/post) | Supervisor | `core.py` `STRATA` |
| idempotence wall, **blinded** (writer-naive-of-verifier) | Supervisor | `core.py` `_replay_gate` |
| human-attention principle (HITL cards) | Encoding Expertise | `core.py` `_emit_hitl_card` |
| expert grows to subsume (convergence over passes) | Asymptote | reject-cache + `max_clusters` |
| regret = reward = (before, action, **outcome**) | (new; see FINDINGS #1–2) | `specs.py` `with_outcomes`, `_regret_gather`, `_SURPRISING` |
| corpus bootstrap (any GitHub contributor) | Asymptote | `specs.py` `contributor_spec` / `review_action_spec` / `author_response_spec` |

## Install

```sh
uv sync           # or: pip install -e .
```

Requires the `claude` and `gh` CLIs on PATH (used via subprocess; the model runs
on your existing Claude plan, `gh` on your existing GitHub auth). The only Python
dependency is `typer`.

## Run

```sh
# public-corpus specs — any GitHub contributor, no substrate needed:
supervisor run actions-<login>              # their review verdicts vs PR features
supervisor run respond-<login> --limit 150  # their author-response trajectories
supervisor run corpus-<login>               # their review-comment register

# sweep-coupled local specs — require a sweep substrate's ~/.sweep logs:
supervisor run remit --outcomes             # adds the regret/outcome channel

supervisor list / show <name> / archive <name>
```

State lives under `~/.supervisor/` (override `SUPERVISOR_HOME`): proposals,
reject cache, residue log, HITL inbox. Local specs read `~/.sweep/events.jsonl`
(override `SUPERVISOR_EVENTS_LOG`).

## What it is — and is NOT

Demonstrated (properties of the **method**): no weight training; online; adapts
and creates policies; no catastrophic forgetting (idempotence-wall regression);
no decay/learning-rate knobs (subsumption by specificity); reversible + auditable
per artifact; per-change alignment moderation; cheap (inference-only); convergent
(monoidal composition).

**Not** demonstrated: that the encoded policy is *good*. This is propose-only —
the replay gate checks **faithfulness** (matches past actions), not **goodness**
(good outcomes). Efficacy needs the loop closed (apply → run → measure via the
regret channel). See the caveat in `docs/FINDINGS.md`.

## Layout

- `supervisor/core.py` — the `supervise(spec)` loop, four-case switch, blinded
  replay gate, propose-only emission. The generalizable harness.
- `supervisor/specs.py` — instantiations: local (sweep) + corpus (`gh`), regret channel.
- `supervisor/_deps.py` — the small surface vendored out of sweep.
- `supervisor/cli.py` — `supervisor run|list|show|archive`.

## License

[AGPL-3.0-or-later](LICENSE). Copyleft, including over a network: if you run a
modified supervisor as a service, you must offer its source. The encoded
artifacts a supervisor produces are yours; the loop that produces them stays
open.
