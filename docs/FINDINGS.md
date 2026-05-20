# Findings

The terse record. The canonical narrative is the trilogy:
[Encoding Expertise](https://june.kim/encoding-expertise),
[Supervisor](https://june.kim/supervisor),
[Asymptote Learning](https://june.kim/asymptote-learning). This is the
load-bearing subset of a longer experiment log; numbers (#N) are stable
references to that log.

## Thesis

**You can assemble an expert-level RL-classification policy with zero weight
training, learned online.** Same inputs a fine-tuning pipeline consumes (labeled
`(state, action)` samples from a frozen corpus), no gradient step anywhere.
Stated plainly: *supplement an expert system and resolve its residue via LLM
calls.* The expert system is primary; a stock model occupies only the residual
cell. Two ingredients, neither trained: (1) an expert system grown from the
corpus via the encoding loop, (2) a general LLM resolving the residue.

**Caveat ("if it works").** Every property below is a property of the *method*,
not yet the *result*. The replay gate checks **faithfulness** (does the rule
reproduce past actions?), not **goodness** (does the action yield a good
outcome?). This is propose-only; efficacy needs the loop closed (apply, run,
measure via the regret channel). The machine *learns* a policy cheaply, online,
auditably; whether the policy is *good* is unvalidated here.

## The method (demonstrated)

- **#1–2 — the third channel: silent regret.** Two known channels catch wrong
  answers: inbox (the agent abstained) and andon (it was sure and something
  tripped). A third is silent: confident, nothing trips, only the *outcome*
  reveals it. Requires the `(before, action, outcome)` triple. The andon is
  synchronous regret; the outcome channel is asynchronous regret. This is the
  reward signal that makes it *learning*, not just compression.
- **#3 — blinded replay (writer-naive-of-verifier).** The idempotence wall must
  not see the recorded action, or it rationalizes instead of predicting. Show it
  the before-state only, predict the action, compare in code. Held-out, not
  circular.
- **#20 — closed action space + nested classifier.** The platform (GitHub)
  defines a finite action set, which is what makes this RL-*classification*. The
  one open action, comment, sub-classifies into a finite intent set; that nested
  classifier is the same problem one level down.
- **#23 (corrected) — judgment mimicry ⊆ behavioral mimicry.** Judgment is only
  observable as behavior; there is no separate value-function channel. Judgment
  mimicry is the sample-hungriest *subset* of behavior cloning, not a different
  kind. The gap is *coverage*, not *competence*. Detectable only by the outcome,
  never by the behavioral signature.
- **#26 / #29 — online, no forgetting, no decay.** Online encoding-learning can't
  catastrophically forget (the idempotence wall is a regression test against all
  history) and needs no decay/learning-rate knobs (subsumption by specificity +
  monoidal composition, not magnitude tug-of-war). The whole online-RL
  hyperparameter surface collapses to zero knobs.
- **#31 — per-change alignment moderation.** Each update is a discrete,
  human-readable artifact through a propose-only gate, so alignment is enforced
  per-change and pre-deployment. You can veto/edit one rule. RLHF bakes values
  into weights you can't selectively revert.
- **#28 — no H100.** Inference-only (even the *learning* step is an LLM call, not
  backprop), and marginal cost *decreases*: every hoisted rule retires future
  model calls. Runs on a laptop.

## The encodability gradient (empirical, by corpus type and contributor)

- **#17 — expert PROSE encodes nothing.** A top reviewer's comments are reasoned
  judgment; the templatable part is the trivial tail. The bootstrap surfaces
  ~nothing to encode. (Asymptote post's "novelist's chapter" boundary, located
  empirically.)
- **#19 — the encodable rind rides CRYSTALLIZED PRIOR JUDGMENT.** A rule like
  `label:invalid -> reject` is encodable only because a human already triaged and
  recorded the label. The loop encodes consequences-of-recorded-judgment, never
  the live judgment. This is why KYC/claims/triage encode well (dense structured
  prior-decision fields) and raw review doesn't.
- **#32 / #38 — encodability is a property of the contributor's STYLE.** Same
  loop: `respond-ljharb` (discussion-driven) → ~0 rules; `respond-nikic`
  (action-driven bug-squasher) → ~6. The corpus *axis* (authoring vs reviewing)
  matters more than identity: reviewing is judgment for everyone (#30).
- **#35 — compound actions hide latent sub-trajectories (POMDP / options).**
  "push_commit" is not primitive; it's an option whose investigation happened
  off-camera and got compressed to one token. You can clone option-*selection*,
  never option-*execution* (a fresh per-case computation). This localizes the
  residue precisely.

## The existence proof and the convergence ablation

- **#33 — sweep's `remit` ruleset IS the thesis, in production.** A ~4-rule
  expert system whose fuzzy residue is one LLM call extracting two booleans, fed
  by `gh` facts, routing real PRs. Topology note: the LLM is an *upstream
  feature-extractor* (prose → booleans at intake), not only a bottom-of-cascade
  fallback. The operator hand-wrote it while playing **supervisor** (the
  encoder); the rule comments are the visible `(witness → artifact)` audit trail
  of a human-run encoding loop.
- **#38 — the loop re-derives the hand-built policy.** Run the supervisor over
  the operator's own author-response trajectory (`respond-kimjune01`) and it
  assembles `changes_requested -> push_commit` (= remit's `CHANGES_REQUESTED ->
  reinvestigate`) and leaves comment-content to the agent (= remit's LLM thread
  judge). Two independent encoders (a human reading andons over months, a machine
  reading a frozen corpus in an afternoon) converge on the same policy. The
  machine even proposed one rule the human hadn't (`re_request_review`) — a
  candidate improvement (unvalidated; the caveat stands).

## Methodology

- **#25 — replication subsumes prereg.** Public corpus + code + per-artifact
  provenance = re-execute and check, no pre-commitment needed. Same argument as
  "read my code" vs "trust my weights." See [REPRODUCE.md](../REPRODUCE.md).
- **#37 — corpus intake needs a legibility precondition.** The supervisor's own
  Identity/precondition stratum applies to the dataset: select only samples where
  the `(state, action)` trajectory is observable (GitHub-merge repos, clean
  timeline events). The method's data hygiene is the method.
