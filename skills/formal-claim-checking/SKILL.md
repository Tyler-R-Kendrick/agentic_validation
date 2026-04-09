---
name: formal-claim-checking
description: Convert candidate claims into safe SMT or Lean checks, choose the right formalization target, and report passed, failed, or unknown results conservatively.
---

# Formal Claim Checking

Use this skill when a user needs objective validation for a specific claim instead of a full end-to-end reasoning workflow.

## Choose the target carefully

- Use **SMT** for arithmetic relationships, bounds, invariants, satisfiability, and entailment questions.
- Use **Lean** for theorem-like propositions where proof structure matters.
- Use **none** when the statement is too vague, empirical, or underspecified to formalize honestly.

## SMT conventions

The repository's SMT checker is intentionally restrictive.

- Expect pySMT-style constructor calls, not arbitrary Python.
- Keep expressions limited to the whitelisted identifiers used by the checker:
  - constructors: `Symbol`, `Int`, `Real`, `Bool`
  - arithmetic: `Plus`, `Minus`, `Times`
  - comparison: `Equals`, `GE`, `GT`, `LE`, `LT`
  - boolean: `And`, `Or`, `Not`, `Implies`
  - constants and types: `TRUE`, `FALSE`, `INT`, `REAL`, `BOOL`
- Avoid attributes, subscripts, imports, helper variables, or any syntax outside that safe subset.

If an expression cannot fit that subset cleanly, mark it as not suitable for SMT instead of inventing unsafe syntax.

## Lean conventions

The repository's Lean checker builds a theorem from:

- a sanitized claim id
- assumptions rendered as premises
- the target proposition as the theorem body

When writing Lean-targeted claims:

- keep the proposition compact and explicit
- preserve assumption text cleanly so it can become premises
- expect the checker to try lightweight proof strategies first (`exact`, `simpa`, `rfl`, `simp`, `trivial`)

Do not promise that a Lean theorem will verify unless the checker actually succeeds.

## Reporting results

Report checker outcomes with the same semantics as the package:

- `passed` when the checker verified the claim
- `failed` when the checker found a real rejection or counterexample
- `unknown` when the environment, expression quality, or tooling prevents a trustworthy result

Unknown is a valid outcome. Prefer `unknown` over a guessed pass.

## Safe operating rules

- Never execute arbitrary code while formalizing a claim.
- Preserve replayable artifacts when possible.
- If assumptions are required, state them explicitly.
- If a claim fails, explain whether the issue is with the reasoning, the formalization, or missing context.

## When the Python package is available

If you are inside this repository or the package is installed, prefer the existing checker implementations instead of re-creating them manually:

- `agentic_validation.checkers.SMTChecker`
- `agentic_validation.checkers.LeanChecker`
