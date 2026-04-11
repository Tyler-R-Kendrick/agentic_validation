# Formal checking reference

Use this reference when the task narrows to validating one or more explicit claims.

## Target selection

### Choose `smt` when the claim is about

- arithmetic relationships
- bounds or invariants
- satisfiability or contradiction checks
- entailment from explicit assumptions
- counterexample-driven validation

### Choose `lean` when the claim is about

- theorem-like propositions
- proof obligations where premises matter
- a proposition that benefits from theorem syntax rather than solver constraints

### Choose neither when

- the claim is empirical, vague, or missing definitions
- the user has not supplied the assumptions required to make the claim checkable

## SMT constraints

The repository's SMT checker intentionally accepts only a small safe subset of pySMT constructors.

Allowed names:

- constructors: `Symbol`, `Int`, `Real`, `Bool`
- arithmetic: `Plus`, `Minus`, `Times`
- comparisons: `Equals`, `GE`, `GT`, `LE`, `LT`
- booleans: `And`, `Or`, `Not`, `Implies`
- constants and sorts: `TRUE`, `FALSE`, `INT`, `REAL`, `BOOL`

Do not use:

- imports
- attribute access
- subscripts
- helper variables outside the expression
- arbitrary Python code

If a claim does not fit this subset cleanly, treat it as not suitable for SMT instead of forcing an unsafe formalization.

## Lean conventions

The Lean checker builds a theorem from:

- a sanitized claim id
- rendered assumptions as premises
- the target proposition as the theorem body

Good Lean-targeted claims are:

- compact
- explicit about assumptions
- theorem-shaped rather than narrative

The checker uses lightweight proof strategies first. A claim is not verified unless the checker actually succeeds.

## Result interpretation

- `passed` — the checker verified the claim
- `failed` — the checker rejected the claim or found a counterexample
- `unknown` — the environment or claim quality prevented a trustworthy decision

Prefer `unknown` over a guessed pass.

## Bundled script inputs

`scripts/run_formal_check.py` accepts either:

- `--claim-json /path/to/claim.json`
- explicit CLI fields such as `--claim-id`, `--claim-text`, `--target`, and `--expression`

Optional repeated flags:

- `--assumption "..."`
- `--step-json /path/to/supporting-steps.json`

The `--step-json` file should contain a JSON array (`[...]`) of `ReasoningStep` objects when you want checker context to include supporting steps.
