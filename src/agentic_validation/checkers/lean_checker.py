"""Lean checker interface stub.

The LeanChecker contract is kept in place so that the Lean integration can be
wired without changing any control-flow code.  Until Lean 4 / LeanDojo is
available in the environment, every call returns ``status="unknown"``.

When Lean is available, the adapter should:

1. Generate a Lean 4 theorem statement from ``claim.formal_expression``.
2. Invoke LeanDojo (or a local ``lake build`` subprocess) to attempt the proof.
3. Capture the proof state or error artifact.
4. Return the appropriate ``CheckerResult``.

The interface mirrors SMTChecker so that checker selection is uniform.
"""

from __future__ import annotations

import logging

from ..schemas import CheckerResult, FormalClaim, ReasoningStep

logger = logging.getLogger(__name__)


class LeanChecker:
    """Attempts Lean 4 proof checking for FormalClaim objects.

    Currently returns ``status="unknown"`` for all claims because LeanDojo
    is not wired.  Subclass and override ``_invoke_lean`` to provide a real
    implementation.
    """

    def check(
        self,
        claim: FormalClaim,
        assumptions: list[str],
        steps: list[ReasoningStep],
    ) -> CheckerResult:
        """Check *claim* via Lean 4 / LeanDojo.

        Parameters
        ----------
        claim:
            The FormalClaim to verify (``formalization_target`` should be
            ``"lean"``).
        assumptions:
            List of assumption strings that act as premises.
        steps:
            Accepted ReasoningSteps whose content may be referenced.

        Returns
        -------
        CheckerResult
            ``status`` is ``"unknown"`` until Lean is wired.
        """
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

    # ------------------------------------------------------------------
    # Extension points
    # ------------------------------------------------------------------

    def _build_theorem(
        self,
        claim: FormalClaim,
        assumptions: list[str],
        steps: list[ReasoningStep],
    ) -> str:
        """Render a Lean 4 theorem statement from the claim and its context.

        Override to customise theorem generation.
        """
        premises = "\n".join(f"  (h{i} : {a})" for i, a in enumerate(assumptions))
        return (
            f"theorem claim_{claim.claim_id.replace('-', '_')}\n"
            f"{premises}\n"
            f"  : {claim.formal_expression} := by\n"
            f"  sorry\n"
        )

    def _invoke_lean(self, claim: FormalClaim, theorem_statement: str) -> CheckerResult:
        """Submit the theorem to Lean and return the result.

        Override with a real LeanDojo invocation.  The stub always returns
        ``status="unknown"``.
        """
        logger.info(
            "LeanChecker stub: would check claim %s with statement:\n%s",
            claim.claim_id,
            theorem_statement,
        )
        return CheckerResult(
            checker_type="lean",
            status="unknown",
            message=(
                "Lean checker is not yet wired (stub). "
                "Override LeanChecker._invoke_lean to provide a real implementation."
            ),
            artifact_ref=None,
        )
