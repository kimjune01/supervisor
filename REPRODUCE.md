# Reproduce

The experiments behind the trilogy are a **re-executable benchmark, not a
pre-registration** (finding #25): the corpus is public, the pipeline is code,
and every proposal carries its own evidence + replay log. You don't trust a
prereg; you re-run the command.

Two honest caveats on exact reproduction:
- **LLM non-determinism** — the four-case switch and the replay gate are Sonnet
  calls; verdicts vary run to run. Pin a model version + `temperature=0` for bit
  stability. The *structural* findings (below) are robust to this.
- **Corpus drift** — only **open** PRs move; closed/merged PRs are effectively
  frozen (finding #36), so a closed-PR corpus is a fixed dataset. Counts on
  squash/force-push-amend repos (e.g. LLVM) are noisy lower-bounds (#37: prefer
  GitHub-merge repos for clean trajectories).

Prereqs: `uv sync`, plus `claude` and `gh` on PATH and authenticated.

---

## 1. Encodability is a property of the contributor's STYLE (findings #32, #38)

A discussion-driven reviewer encodes ~nothing; an action-driven bug-squasher
encodes a real rind. Same loop, opposite result.

```sh
supervisor run respond-ljharb -v               # ~0 expert rules: replies are judgment
supervisor run respond-nikic --limit 100 -v    # ~6 expert rules: comment -> push_commit
```

Expected shape: `respond-ljharb` routes its recurring clusters to `agent`
(content-driven `comment_reply`); `respond-nikic` produces several `expert`
trigger->action rules (`review:commented -> push_commit`, etc.). The delta is
the finding.

## 2. Reviewing is judgment regardless of archetype (finding #30)

Even the bug-squasher's *review verdicts* don't encode — reviewing means reading
the code. The encodability lives in *authoring* responses, not reviewing.

```sh
supervisor run actions-nikic --limit 150 -v
```

Expected: `expert: 0`, and at least one proposed rule **rejected by the blinded
replay gate** with concrete conflicts (a held-out PR the rule would mispredict).
That rejection is the idempotence wall working at scale.

## 3. The convergence ablation — the machine re-derives a hand-built policy (finding #38)

The strongest test, because there's ground truth: the operator already hand-wrote
the response policy as sweep's `remit` cascade. Run the loop over the operator's
own author-response trajectory and check whether it assembles rules of the same
shape.

```sh
supervisor run respond-kimjune01 --limit 50 -v
```

Expected: an `expert` rule `review:changes_requested -> push_commit` (matches
remit's `CHANGES_REQUESTED -> reinvestigate` under the `push_commit <->
reinvestigate` option-mapping, finding #35) AND `maintainer_comment ->
comment_reply` routed to `agent` (matches remit leaving comment-content to its
LLM thread judge). Two independent encoders, one policy shape.

## 4. Prose encodes nothing; the residue is judgment (finding #17)

```sh
supervisor run corpus-ljharb -v
```

Expected: comments shatter into near-unique clusters (regex can't cluster prose,
finding #16) and nothing reaches a clean `expert` hoist. The valuable part of a
top reviewer's commentary is judgment, which is the `agent` residue by design.

## 5. The regret / outcome channel — catching silent misclassification (findings #1–2)

Requires a sweep substrate (`~/.sweep/events.jsonl`). Adds the `(before, action,
outcome)` triple: it fetches each past decision's real PR outcome and flags
actions the outcome contradicts.

```sh
supervisor run remit --outcomes -v
```

Expected: surprising `(action -> contradicting-outcome)` clusters surface as new
attention, distinct from the andon (tripped) and inbox (abstained) channels.

---

## Reading a proposal

Every staged proposal is a self-contained artifact under
`~/.supervisor/proposals/`:

```sh
supervisor list
supervisor show <name>      # frontmatter (case, stratum, replay_clean) + predicate + evidence
supervisor archive <name>   # after you apply or reject it
```

It is **propose-only**: the supervisor never edits source. The replay gate
verifies *faithfulness* (the rule reproduces past actions), not *goodness* (the
action yields good outcomes). Validating goodness requires closing the loop
(apply, run, measure via the regret channel) and is out of scope here.
