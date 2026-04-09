---
name: agentic-validation
description: Run a structured reasoning-validation workflow that decomposes a task into trace steps, critiques each step, formalizes objective claims, checks them with SMT or Lean when appropriate, repairs failing regions, and returns a gated answer with verification status. Use this whenever the user wants high-assurance reasoning, wants an answer audited step-by-step, asks to validate a chain of thought or reasoning trace, wants contradiction detection or repair, or needs a final answer labeled as hard_verified, soft_verified, corrected, unverified, or rejected.
---

# Agentic Validation

Use this skill to apply the repository's full validation loop instead of giving an unchecked answer.

## Goals

- Break the task into a compact `ReasoningTrace`.
- Critique local steps and global consistency.
- Formalize objective claims for SMT or Lean only when that adds real value.
- Repair the smallest failing region instead of rewriting everything.
- Gate the final answer with an explicit verification status.

## Workflow

### 1. Capture the task as structured input

Start from the repository's `TaskInput` shape:

- `task_id`
- `goal`
- optional `context`
- optional `constraints`
- optional `evidence`
- `require_formal_proof`
- `require_symbolic_checking`
- `max_iterations`
- `max_branches`

If the user did not provide all of these, infer sensible defaults and state any important assumptions.

### 2. Generate a reasoning trace

Produce a `ReasoningTrace` with:

- explicit assumptions
- atomic steps
- explicit `depends_on` links
- `formalizable=true` only on claims worth checking objectively

Keep the trace concise. Prefer checkable steps over polished prose.

### 3. Critique before trusting

Review each step independently and use only rubric labels that match the repository:

- `unsupported_inference`
- `missing_premise`
- `contradiction`
- `invalid_calculation`
- `malformed_formalization`
- `incomplete_case_analysis`
- `policy_violation`
- `unverifiable_claim`
- `irrelevant_step`

Also track global issues and open obligations.

### 4. Formalize only the right claims

Choose the formalization target deliberately:

- `smt` for arithmetic, constraints, invariants, consistency checks, or counterexample-driven validation
- `lean` for theorem-style proof obligations
- `none` when the claim is not realistically formalizable

Do not force every step into a formal system.

### 5. Run objective checks

For each formal claim, report one of:

- `passed`
- `failed`
- `unknown`

Keep checker output replayable. If a check fails, preserve the checker message and any counterexample or artifact details.

### 6. Repair locally

When a region fails:

- preserve accepted upstream steps
- modify only the failed local region
- use critique and checker feedback directly
- prefer the smallest fix that clears the failure

If local repair stalls, branch and compare alternatives instead of repeatedly restating the same bad reasoning.

### 7. Gate the final answer

Return a final answer only after assigning one of the repository's verification statuses:

- `hard_verified`
- `soft_verified`
- `corrected`
- `unverified`
- `rejected`

Be conservative. If critical gaps remain, do not overstate confidence.

## Output expectations

When the user wants the full artifact, mirror the package's `AgentResult` shape:

- `task_id`
- `final_answer`
- `verification_status`
- `accepted_steps`
- `failed_steps`
- `checker_artifacts`
- `repair_history`
- `summary_state`

When the user only wants a normal response, still use the workflow internally and surface the final verification status clearly.

## When the Python package is available

If you are operating in this repository or `agentic_validation` is installed, prefer the package implementation over recreating the loop manually. The public entry point is `run_agent(task: TaskInput) -> AgentResult`.
