"""Lean checker adapter backed by a local Lean 4 toolchain."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from ..schemas import CheckerResult, FormalClaim, ReasoningStep

logger = logging.getLogger(__name__)


class LeanChecker:
    """Attempts Lean 4 proof checking for FormalClaim objects."""

    def __init__(
        self,
        command: Sequence[str] | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.command = list(command) if command is not None else None
        self.timeout_seconds = timeout_seconds

    def check(
        self,
        claim: FormalClaim,
        assumptions: list[str],
        steps: list[ReasoningStep],
    ) -> CheckerResult:
        """Check *claim* via a local Lean 4 executable."""
        if claim.formalization_target != "lean":
            return CheckerResult(
                checker_type="lean",
                status="unknown",
                message="Claim is not targeted at Lean.",
            )

        if not claim.formal_expression:
            return CheckerResult(
                checker_type="lean",
                status="unknown",
                message="No formal_expression provided; cannot generate Lean theorem.",
            )

        theorem_statement = self._build_theorem(claim, assumptions, steps)
        return self._invoke_lean(claim, theorem_statement)

    def _build_theorem(
        self,
        claim: FormalClaim,
        assumptions: list[str],
        steps: list[ReasoningStep],
    ) -> str:
        """Render a Lean 4 theorem statement from the claim and its context."""
        del steps

        premise_lines: list[str] = []
        hypothesis_names: list[str] = []
        for index, assumption in enumerate(assumptions):
            stripped = assumption.strip()
            if _looks_like_binder(stripped):
                premise_lines.append(f"  ({stripped})")
                continue
            hypothesis_name = f"h{index}"
            premise_lines.append(f"  ({hypothesis_name} : {stripped})")
            hypothesis_names.append(hypothesis_name)

        safe_id = _sanitize_identifier(claim.claim_id)
        theorem_header = [
            "set_option autoImplicit false",
            "",
            f"theorem claim_{safe_id}",
            *premise_lines,
            f"  : {claim.formal_expression} := by",
        ]
        theorem_header.extend(self._proof_candidates(hypothesis_names))
        theorem_header.append("")
        return "\n".join(theorem_header)

    def _invoke_lean(self, claim: FormalClaim, theorem_statement: str) -> CheckerResult:
        """Submit the theorem to Lean and return the result."""
        command = self._resolve_command()
        if command is None:
            return CheckerResult(
                checker_type="lean",
                status="unknown",
                message="Lean executable is not available in this environment.",
            )

        try:
            with tempfile.TemporaryDirectory(prefix="agentic-validation-lean-") as temp_dir:
                safe_filename = _sanitize_identifier(claim.claim_id)
                theorem_path = Path(temp_dir) / f"{safe_filename}.lean"
                theorem_path.write_text(theorem_statement, encoding="utf-8")
                completed = subprocess.run(
                    [*command, str(theorem_path)],
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=self.timeout_seconds,
                )
        except subprocess.TimeoutExpired as exc:
            return CheckerResult(
                checker_type="lean",
                status="unknown",
                message=f"Lean proof check timed out after {self.timeout_seconds} seconds.",
                artifact_ref=_serialize_artifact(
                    command=command,
                    theorem_statement=theorem_statement,
                    returncode=None,
                    stdout=exc.stdout,
                    stderr=exc.stderr,
                ),
            )
        except OSError as exc:
            logger.warning("Lean invocation failed for claim %s: %s", claim.claim_id, exc)
            return CheckerResult(
                checker_type="lean",
                status="unknown",
                message=f"Lean invocation failed: {exc}",
                artifact_ref=_serialize_artifact(
                    command=command,
                    theorem_statement=theorem_statement,
                    returncode=None,
                    stdout=None,
                    stderr=str(exc),
                ),
            )

        artifact = _serialize_artifact(
            command=command,
            theorem_statement=theorem_statement,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        combined_output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part and part.strip()
        )

        if completed.returncode == 0:
            return CheckerResult(
                checker_type="lean",
                status="passed",
                message="Lean verified the claim successfully.",
                artifact_ref=artifact,
            )

        failure_message = combined_output or "Lean rejected the generated theorem."
        return CheckerResult(
            checker_type="lean",
            status="failed",
            message=failure_message,
            artifact_ref=artifact,
        )

    def _proof_candidates(self, hypothesis_names: list[str]) -> list[str]:
        lines = ["  first"]
        for hypothesis_name in hypothesis_names:
            lines.append(f"  | exact {hypothesis_name}")
            lines.append(f"  | simpa using {hypothesis_name}")
        lines.extend(
            [
                "  | rfl",
                "  | simp",
                "  | trivial",
            ]
        )
        return lines

    def _resolve_command(self) -> list[str] | None:
        """Return the best available Lean command."""
        if self.command is not None:
            return list(self.command)
        if shutil.which("lake") and _has_lake_project_file():
            return ["lake", "env", "lean"]
        if shutil.which("lean"):
            return ["lean"]
        return None


def _looks_like_binder(assumption: str) -> bool:
    if ":" not in assumption:
        return False
    head, _, _ = assumption.partition(":")
    head = head.strip()
    return bool(head) and all(part.isidentifier() for part in head.split())


def _sanitize_identifier(raw: str) -> str:
    """Return a string safe for use as a Lean identifier and filename component.

    Replaces non-alphanumeric/underscore characters with underscores,
    collapses runs of underscores, and strips leading/trailing underscores.
    Falls back to ``"anonymous"`` if nothing remains.
    """
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "anonymous"


def _has_lake_project_file() -> bool:
    """Return True when the current directory is inside a Lake project."""
    cwd = Path.cwd()
    return any((cwd / name).is_file() for name in ("lakefile.lean", "lakefile.toml"))


def _serialize_artifact(
    *,
    command: Sequence[str] | None,
    theorem_statement: str,
    returncode: int | None,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> str:
    return json.dumps(
        {
            "command": list(command) if command is not None else None,
            "returncode": returncode,
            "theorem": theorem_statement,
            "stdout": _normalize_output(stdout),
            "stderr": _normalize_output(stderr),
        },
        ensure_ascii=False,
    )


def _normalize_output(output: str | bytes | None) -> str | None:
    if output is None:
        return None
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output
