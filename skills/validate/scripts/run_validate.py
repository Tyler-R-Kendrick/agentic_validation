#!/usr/bin/env python3
"""Run the repository's end-to-end validation workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = REPO_ROOT / "src"
# Allow the bundled script to import the local package before editable install.
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from agentic_validation import TaskInput, run_agent  # noqa: E402


def _load_task(args: argparse.Namespace) -> TaskInput:
    if args.task_json:
        payload = json.loads(Path(args.task_json).read_text())
        return TaskInput.model_validate(payload)

    if not args.goal:
        raise SystemExit("Either --task-json or --goal is required.")

    payload: dict[str, Any] = {
        "task_id": args.task_id or "validate-task",
        "goal": args.goal,
        "context": {"notes": args.context} if args.context else {},
        "constraints": args.constraint or [],
        "evidence": [{"text": item} for item in (args.evidence or [])],
        "require_formal_proof": args.require_formal_proof,
        "require_symbolic_checking": args.require_symbolic_checking,
        "max_iterations": args.max_iterations,
        "max_branches": args.max_branches,
    }
    return TaskInput.model_validate(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-json", help="Path to a JSON file containing a TaskInput payload")
    parser.add_argument("--task-id", help="Task identifier used when building TaskInput from flags")
    parser.add_argument("--goal", help="Goal string used when building TaskInput from flags")
    parser.add_argument("--context", help="Optional context string")
    parser.add_argument("--constraint", action="append", help="Repeatable task constraint")
    parser.add_argument("--evidence", action="append", help="Repeatable evidence item")
    parser.add_argument(
        "--require-formal-proof",
        action="store_true",
        help="Require Lean-style proof obligations",
    )
    parser.add_argument(
        "--require-symbolic-checking",
        action="store_true",
        help="Require SMT/Lean symbolic checking",
    )
    parser.add_argument("--max-iterations", type=int, default=3, help="Maximum repair iterations")
    parser.add_argument("--max-branches", type=int, default=2, help="Maximum escalation branches")
    parser.add_argument("--output", help="Optional path to write the AgentResult JSON")
    args = parser.parse_args()

    task = _load_task(args)
    result = run_agent(task)
    rendered = json.dumps(result.model_dump(), indent=2)

    if args.output:
        Path(args.output).write_text(rendered + "\n")
    else:
        print(rendered)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
