---
name: validate
description: Use this skill for high-assurance validation of reasoning, claims, and proof sketches with the repository's full workflow or direct SMT/Lean checks.
---

# Validate

Use this skill when the user wants high-assurance validation rather than an unchecked answer.

## Pick the narrowest path that fits

- Use the **full workflow** when the task needs trace generation, critique, formalization, objective checks, repair, and a final verification status.
- Use the **checker-only path** when the user already has a specific claim and only needs SMT or Lean validation.
- Reuse the Python package in this repository instead of recreating the workflow manually.

## Bundled resources

Read only what you need:

- `references/python-api.md` — package entry points, schemas, reusable modules, and CLI patterns.
- `references/formal-checking.md` — SMT and Lean targeting rules, safe expression constraints, and result interpretation.
- `scripts/run_validate.py` — run the repository's end-to-end validator from JSON or CLI flags.
- `scripts/run_formal_check.py` — run `SMTChecker` or `LeanChecker` directly on a formal claim.

## Full workflow

1. Capture the task as a `TaskInput`.
2. Run the repository implementation, preferably through `run_agent(task)` or `scripts/run_validate.py`.
3. Report the returned `verification_status` conservatively.
4. Surface the structured artifacts that matter: accepted steps, failed steps, checker artifacts, repair history, and summary state.
5. If the result is weak or rejected, use the failure artifacts to guide the next repair rather than restarting from scratch.

## Checker-only workflow

1. Choose `smt` for arithmetic, constraints, entailment, invariants, and counterexample-friendly claims.
2. Choose `lean` for proof-oriented propositions where theorem structure matters.
3. Prefer `unknown` over an overstated pass when the claim is underspecified or the environment cannot verify it.
4. Preserve replayable artifacts from the checker output.

## Output requirements

- Always make the final confidence level explicit with the repository's verification or checker status.
- Keep assumptions visible.
- Distinguish reasoning problems from formalization problems and from tooling limitations.
- When the user wants the full structured artifact, mirror the package's `AgentResult` shape.
