# agentic_validation
A collection of composite patterns for validation of agent/ai outputs and reasoning traces implemented as an agent and agent skills.

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
