# Agentic Validation

High-assurance validation of agent/AI outputs and reasoning traces, delivered as a **GitHub Copilot Plugin**, consumable **skills**, and a Python package.

This project utilizes state-of-the-art techniques to enhance reasoning traces with explicit validation steps for llms and agents.

## Quick start: consume the plugin or skill

### GitHub Copilot Plugin

This repository is published as a GitHub Copilot Plugin.  The plugin manifest lives at [`plugin.json`](plugin.json) and the marketplace entry is at [`.github/plugin/marketplace.json`](.github/plugin/marketplace.json).

Install via the Copilot CLI:

```bash
gh copilot plugin install https://github.com/Tyler-R-Kendrick/agentic_validation
```

Once installed, the `validate` skill is available to any Copilot-powered agent session in your environment.

### Skills (Claude / Copilot agent)

The repository ships a `validate` skill in `./skills/validate`.  Install it by symlinking it into your agent's skill directory:

```bash
# User-wide install
REPO_ROOT="$(git rev-parse --show-toplevel)"
mkdir -p ~/.claude/skills
ln -s "$REPO_ROOT/skills/validate" ~/.claude/skills/validate

# Project-local install (alternative)
mkdir -p .claude/skills
ln -s "$REPO_ROOT/skills/validate" .claude/skills/validate
```

The skill exposes these capabilities to your agent:

| Path | Purpose |
|---|---|
| `SKILL.md` | Entry-point: usage rules and workflow selection |
| `references/python-api.md` | Package schemas, entry points, and CLI patterns |
| `references/formal-checking.md` | SMT / Lean expression rules and result interpretation |
| `scripts/run_validate.py` | CLI wrapper for the end-to-end workflow |
| `scripts/run_formal_check.py` | CLI wrapper for single-claim SMT/Lean checking |

### Agent discovery inside a repo

Use `.claude/skills/` for Claude's built-in skill loader.  Use `.agents/skills/` for agent runners that scan repository-local assets.  This repository already includes the `.agents/skills/` layout with a symlink back to `skills/`.  To reproduce the pattern:

```bash
mkdir -p .agents/skills
ln -s ../../skills/validate .agents/skills/validate
```

---

## Running examples (notebooks)

The [`notebooks/`](notebooks/) directory contains self-contained Jupyter notebooks:

| Notebook | What it shows |
|---|---|
| [`notebooks/validate_example.ipynb`](notebooks/validate_example.ipynb) | End-to-end `run_agent` workflow |
| [`notebooks/checker_only_example.ipynb`](notebooks/checker_only_example.ipynb) | Direct `SMTChecker` / `LeanChecker` usage |

Install dependencies and open:

```bash
python -m pip install -e ".[dev]" jupyter
jupyter notebook notebooks/
```

---

## Python package

If you need the package directly instead of a skill or plugin:

```bash
python -m pip install -e .
python - <<'PY'
from agentic_validation import TaskInput, run_agent

result = run_agent(TaskInput(task_id="demo", goal="Validate that x > 5 implies x + 1 > 6"))
print(result.verification_status)
print(result.final_answer)
PY
```

Skill scripts also work standalone:

```bash
python skills/validate/scripts/run_validate.py \
  --goal "Validate that x > 5 implies x + 1 > 6" \
  --require-symbolic-checking

python skills/validate/scripts/run_formal_check.py \
  --claim-id claim-1 \
  --claim-text "x > 5 implies x + 1 > 6" \
  --target smt \
  --expression "Implies(GT(Symbol('x', INT), Int(5)), GT(Plus(Symbol('x', INT), Int(1)), Int(6)))"
```

---

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
