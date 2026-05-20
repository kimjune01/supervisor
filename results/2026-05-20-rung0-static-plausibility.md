# Rung 0 — static patch plausibility (no execution)

*2026-05-20. Cheapest rung of the BOOTSTRAP ladder: API-only, no clone, no Docker,
no tests. Licenses "patch looks plausible", NOT a resolved rate.*

## Setup
3 of the 52 SOTA-failed Lite instances (pure-Python, skipped the already-solved
12171). Sonnet generated a candidate patch from `problem_statement` alone (gold
withheld), self-rated. codex (gpt-5.5) then rated plausibility + recall-smell
independently, also gold-blind. Gold consulted only after, for comparison.

| instance | created | plausible (codex) | recall smell | vs gold |
|---|---|---|---|---|
| django-11019 | 2019 | high | med-high | same approach (toposort + dep graph, `merge(*lists)`); missed parallel `_css` rewrite |
| sympy-13146 | 2017 | med-low | low | wrong location (numbers.py vs gold's operations.py `_aresame` early-return) |
| flask-5063 | 2023 | high | high | near-identical; candidate admitted reasoning from "the patched version" |

## Finding
Rung 0 separated the two confident-correct-shaped patches from the speculative
miss without executing anything — cheap triage works. But it also surfaced the
contamination problem in miniature: **the two "high plausible" patches are exactly
the ones that reek of recall** (flask-5063 literally admitted it), and the lone
"low recall smell" patch is the one that's *wrong*. On contaminated Lite,
plausibility and recall are entangled — you cannot tell diagnosis from memory at
this rung. That entanglement is precisely why BOOTSTRAP gates the whole quest on
post-cutoff instances (rungs 5–6). Rung 0's job here is to confirm the engine
emits well-shaped patches and to make the contamination signal legible — both done.

Full transcript (with patches + gold): was at `/tmp/swebench-abduction/rung0_results.md` (ephemeral).
