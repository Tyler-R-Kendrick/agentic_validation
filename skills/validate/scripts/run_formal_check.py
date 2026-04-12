#!/usr/bin/env python3
"""Run the repository's SMT or Lean checker on a formal claim."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from agentic_validation import FormalClaim, ReasoningStep  # noqa: E402
from agentic_validation.checkers import LeanChecker, SMTChecker  # noqa: E402


def _load_claim(args: argparse.Namespace) -> FormalClaim:
    if args.claim_json:
        payload = json.loads(Path(args.claim_json).read_text())
        return FormalClaim.model_validate(payload)

    if not all([args.claim_id, args.claim_text, args.target]):
        raise SystemExit(
            "Provide --claim-json or all of --claim-id, --claim-text, and --target."
        )

    payload: dict[str, Any] = {
        "claim_id": args.claim_id,
        "source_step_id": args.source_step_id or args.claim_id,
        "claim_text": args.claim_text,
        "formalization_target": args.target,
        "formal_expression": args.expression,
    }
    return FormalClaim.model_validate(payload)


def _load_steps(step_json_path: str | None) -> list[ReasoningStep]:
    if not step_json_path:
        return []
    payload = json.loads(Path(step_json_path).read_text())
    return [ReasoningStep.model_validate(item) for item in payload]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claim-json", help="Path to a JSON file containing a FormalClaim payload")
    parser.add_argument("--claim-id", help="Claim identifier")
    parser.add_argument("--source-step-id", help="Optional source step identifier")
    parser.add_argument("--claim-text", help="Human-readable claim text")
    parser.add_argument(
        "--target",
        choices=["smt", "lean"],
        help="Formalization target when not using --claim-json",
    )
    parser.add_argument("--expression", help="Formal expression for the claim")
    parser.add_argument("--assumption", action="append", help="Repeatable assumption string")
    parser.add_argument("--step-json", help="Path to a JSON array of supporting ReasoningStep payloads")
    parser.add_argument("--output", help="Optional path to write the CheckerResult JSON")
    args = parser.parse_args()

    claim = _load_claim(args)
    steps = _load_steps(args.step_json)
    assumptions = args.assumption or []

    if claim.formalization_target == "smt":
        result = SMTChecker().check(claim, assumptions, steps)
    elif claim.formalization_target == "lean":
        result = LeanChecker().check(claim, assumptions, steps)
    else:
        raise SystemExit("formalization_target must be 'smt' or 'lean' to run a checker.")

    rendered = json.dumps(result.model_dump(), indent=2)
    if args.output:
        Path(args.output).write_text(rendered + "\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
