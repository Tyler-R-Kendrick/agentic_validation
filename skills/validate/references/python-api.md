# Python API reference

Use these repository modules instead of rebuilding the validation workflow.

## Install or import path

From the repository root:

```bash
python -m pip install -e "."
```

If the package is not installed yet, the bundled scripts automatically add `src/` to `sys.path` so they can still import the local package.

## Public entry points

### End-to-end validation

- `agentic_validation.TaskInput`
- `agentic_validation.run_agent`
- `agentic_validation.AgentResult`

`run_agent(task: TaskInput) -> AgentResult` runs the repository's full loop:

1. generate trace
2. critique steps and global consistency
3. formalize claims
4. run SMT and Lean checks
5. repair failing regions
6. gate the final answer with a verification status

### Reusable schemas

Import from `agentic_validation` or `agentic_validation.schemas` when you need structured payloads:

- `TaskInput`
- `ReasoningTrace`
- `ReasoningStep`
- `FormalClaim`
- `CheckerResult`
- `SummaryState`
- `AgentResult`

### Direct checker access

Import from `agentic_validation.checkers`:

- `SMTChecker`
- `LeanChecker`

Both expose:

```python
checker.check(claim, assumptions, steps)
```

Where:

- `claim` is a `FormalClaim`
- `assumptions` is a list of strings
- `steps` is a list of supporting `ReasoningStep` objects

## Internal modules worth reusing

These are useful when the caller needs repository-native components rather than a custom rewrite:

- `agentic_validation.modules.GeneratorModule`
- `agentic_validation.modules.CriticModule`
- `agentic_validation.modules.FormalizerModule`
- `agentic_validation.modules.RepairModule`
- `agentic_validation.modules.AggregatorModule`
- `agentic_validation.modules.GateModule`

## Bundled scripts

### Run the full validator

```bash
python skills/validate/scripts/run_validate.py \
  --task-id demo \
  --goal "Validate that x > 5 implies x + 1 > 6" \
  --require-symbolic-checking
```

Or pass a JSON file containing a `TaskInput` payload:

```bash
python skills/validate/scripts/run_validate.py --task-json /path/to/task.json
```

### Run a single formal check

```bash
python skills/validate/scripts/run_formal_check.py \
  --claim-id claim-1 \
  --claim-text "x > 5 implies x + 1 > 6" \
  --target smt \
  --expression "Implies(GT(Symbol('x', INT), Int(5)), GT(Plus(Symbol('x', INT), Int(1)), Int(6)))"
```

## Result handling

### `AgentResult`

Important fields to surface:

- `verification_status`
- `final_answer`
- `accepted_steps`
- `failed_steps`
- `checker_artifacts`
- `repair_history`
- `summary_state`

### `CheckerResult`

Important fields to surface:

- `status`
- `checker_type`
- `message`
- `counterexample`
- `artifacts`
