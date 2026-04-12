# agentic_validation
A collection of composite patterns for validation of agent/ai outputs and reasoning traces implemented as an agent and agent skills.

## Included skills

The repository now ships an Anthropic-style skill in `./skills`:

- `validate` - run the full structured reasoning, critique, formalization, checking, repair, gating, and direct SMT/Lean claim-checking workflow.

For local agent discovery inside this repo, `.agents/skills/` contains a symlink to that same skill folder.

## Install skills and agents

### Claude / Agent Skills installs

From the repository root, install the skill by symlinking it into your user or project skill directory:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
mkdir -p ~/.claude/skills
ln -s "$REPO_ROOT/skills/validate" ~/.claude/skills/validate
```

For a project-local install, symlink the same folder into `.claude/skills/` in the target repo instead of `~/.claude/skills/`.

### Agent discovery inside a repo

Use `.claude/skills/` when you want Claude's built-in skill loader to discover the skills for a user or project. Use `.agents/skills/` when your agent runner scans repository-local agent assets. This repository already includes the `.agents/skills/` layout, with a symlink pointing back to the canonical copy under `skills/`. To reproduce the pattern elsewhere:

```bash
mkdir -p .agents/skills
ln -s ../../skills/validate .agents/skills/validate
```

### Python package usage

If you want to call the packaged agent directly instead of loading the skill into another tool:

```bash
python -m pip install -e .
# Run a small inline Python example from the shell.
python - <<'PY'
from agentic_validation import TaskInput, run_agent

# Other TaskInput fields are optional here and fall back to package defaults,
# including context, constraints, evidence, require_formal_proof,
# require_symbolic_checking, max_iterations, and max_branches; see
# src/agentic_validation/schemas.py for the current defaults.
result = run_agent(TaskInput(task_id="demo", goal="Validate that x > 5 implies x + 1 > 6"))
print(result.verification_status)
print(result.final_answer)
print(result.model_dump())
PY
```

### Bundled skill scripts

The merged skill includes scripts that reuse the repository's Python package modules directly:

```bash
python skills/validate/scripts/run_validate.py --goal "Validate that x > 5 implies x + 1 > 6" --require-symbolic-checking
python skills/validate/scripts/run_formal_check.py \
  --claim-id claim-1 \
  --claim-text "x > 5 implies x + 1 > 6" \
  --target smt \
  --expression "Implies(GT(Symbol('x', INT), Int(5)), GT(Plus(Symbol('x', INT), Int(1)), Int(6)))"
```

## Development setup

```bash
python -m pip install -e ".[dev]"
```

## Validation

```bash
python -m pytest tests/
ruff check .
```

The repository includes `.github/workflows/copilot-setup-steps.yml` so GitHub Copilot's coding agent installs the Python toolchain, dev dependencies, and a Lean 4 toolchain before it starts work.
