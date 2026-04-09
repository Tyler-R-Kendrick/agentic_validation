# agentic_validation
A collection of composite patterns for validation of agent/ai outputs and reasoning traces implemented as an agent and agent skills.

## Included skills

The repository now ships Anthropic-style skills in `./skills`:

- `agentic-validation` - run the full structured reasoning, critique, formalization, checking, repair, and gating workflow.
- `formal-claim-checking` - turn candidate claims into safe SMT or Lean checks and interpret the results.

For local agent discovery inside this repo, `.agents/skills/` contains symlinks to those same skill folders.

## Install skills and agents

### Claude / Agent Skills installs

From the repository root, install one or both skills by symlinking them into your user or project skill directory:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
mkdir -p ~/.claude/skills
ln -s "$REPO_ROOT/skills/agentic-validation" ~/.claude/skills/agentic-validation
ln -s "$REPO_ROOT/skills/formal-claim-checking" ~/.claude/skills/formal-claim-checking
```

For a project-local install, symlink the same folders into `.claude/skills/` in the target repo instead of `~/.claude/skills/`.

### Agent discovery inside a repo

Use `.claude/skills/` when you want Claude's built-in skill loader to discover the skills for a user or project. Use `.agents/skills/` when your agent runner scans repository-local agent assets. This repository already includes the `.agents/skills/` layout, with symlinks pointing back to the canonical copies under `skills/`. To reproduce the pattern elsewhere:

```bash
mkdir -p .agents/skills
ln -s ../../skills/agentic-validation .agents/skills/agentic-validation
ln -s ../../skills/formal-claim-checking .agents/skills/formal-claim-checking
```

### Python package usage

If you want to call the packaged agent directly instead of loading the skills into another tool:

```bash
python -m pip install -e ".[dev]"
# Run a small inline Python example from the shell.
python - <<'PY'
from agentic_validation import TaskInput, run_agent

result = run_agent(TaskInput(task_id="demo", goal="Verify a reasoning trace"))
print(result.model_dump())
PY
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
