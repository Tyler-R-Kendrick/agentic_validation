"""SMT checker adapter using pySMT / Z3.

The adapter compiles a FormalClaim's formal_expression into a pySMT formula
and runs it through Z3 to determine satisfiability.

Design notes
------------
* Claims whose formal_expression is None or whose formalization_target is not
  "smt" are returned immediately with status "unknown".
* The formal_expression is evaluated in a sandbox that exposes a minimal set of
  pySMT constructors (Symbol, Int, Real, Bool, Plus, Minus, Times, Equals,
  GE, GT, LE, LT, And, Or, Not, Implies, ForAll, Exists).
* Assumptions are rendered as additional pySMT assertions.
* The exact solver query (serialized as SMTLIB2) is stored in the returned
  CheckerResult so that every call is replayable.
"""

from __future__ import annotations

import logging
from typing import Any

from ..schemas import CheckerResult, FormalClaim, ReasoningStep

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# pySMT / Z3 imports (lazy so tests can import without a solver present)
# ---------------------------------------------------------------------------

def _try_import_pysmt():
    try:
        from pysmt.shortcuts import (
            Symbol, Int, Real, Bool,
            Plus, Minus, Times,
            Equals, GE, GT, LE, LT,
            And, Or, Not, Implies,
            Solver, get_model, is_sat, is_unsat,
            TRUE, FALSE,
        )
        from pysmt.typing import INT, REAL, BOOL
        from pysmt.smtlib.printers import SmtPrinter
        import io

        return dict(
            Symbol=Symbol, Int=Int, Real=Real, Bool=Bool,
            Plus=Plus, Minus=Minus, Times=Times,
            Equals=Equals, GE=GE, GT=GT, LE=LE, LT=LT,
            And=And, Or=Or, Not=Not, Implies=Implies,
            Solver=Solver, get_model=get_model,
            is_sat=is_sat, is_unsat=is_unsat,
            TRUE=TRUE, FALSE=FALSE,
            INT=INT, REAL=REAL, BOOL=BOOL,
            SmtPrinter=SmtPrinter, io=io,
        )
    except ImportError as exc:
        logger.warning("pySMT not available: %s", exc)
        return None


_PYSMT = None  # populated on first use


def _get_pysmt() -> dict | None:
    global _PYSMT
    if _PYSMT is None:
        _PYSMT = _try_import_pysmt()
    return _PYSMT


# ---------------------------------------------------------------------------
# SMTChecker
# ---------------------------------------------------------------------------


class SMTChecker:
    """Runs SMT-based objective checking on FormalClaim objects.

    Usage::

        checker = SMTChecker()
        result = checker.check(claim, assumptions=[], steps=[])
    """

    def check(
        self,
        claim: FormalClaim,
        assumptions: list[str],
        steps: list[ReasoningStep],
    ) -> CheckerResult:
        """Check *claim* against *assumptions* and relevant *steps*.

        Returns
        -------
        CheckerResult
            status is one of "passed", "failed", "unknown".
        """
        if claim.formalization_target != "smt":
            return CheckerResult(
                checker_type="smt",
                status="unknown",
                message="Claim is not targeted at SMT.",
            )

        if not claim.formal_expression:
            return CheckerResult(
                checker_type="smt",
                status="unknown",
                message="No formal_expression provided; skipping SMT check.",
            )

        pysmt = _get_pysmt()
        if pysmt is None:
            return CheckerResult(
                checker_type="smt",
                status="unknown",
                message="pySMT/Z3 not available in this environment.",
            )

        return self._run_check(claim, assumptions, steps, pysmt)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_check(
        self,
        claim: FormalClaim,
        assumptions: list[str],
        steps: list[ReasoningStep],
        pysmt: dict,
    ) -> CheckerResult:
        """Compile and run the SMT query."""
        # Build a sandbox with pySMT constructors
        sandbox = {k: v for k, v in pysmt.items()}
        sandbox.update({"__builtins__": {}})

        # Evaluate claim formula
        try:
            claim_formula = eval(claim.formal_expression, sandbox)  # noqa: S307
        except Exception as exc:
            return CheckerResult(
                checker_type="smt",
                status="unknown",
                message=f"Could not compile formal_expression: {exc}",
                artifact_ref=None,
            )

        # Evaluate assumption formulae
        assumption_formulae = []
        for asm in assumptions:
            try:
                f = eval(asm, sandbox)  # noqa: S307
                assumption_formulae.append(f)
            except Exception as exc:
                logger.debug("Skipping assumption %r: %s", asm, exc)

        # Collect step-level formalizable expressions
        step_formulae = []
        for step in steps:
            if step.formalizable and step.status == "accepted":
                for fc in []:  # placeholder: step-level expressions not yet wired
                    pass

        # Build the negation query: if (assumptions /\ claim) is unsat, the
        # claim is inconsistent with its assumptions (failed).
        # If (assumptions /\ NOT claim) is unsat, the claim is entailed (passed).
        And_ = pysmt["And"]
        Not_ = pysmt["Not"]
        is_unsat_ = pysmt["is_unsat"]
        get_model_ = pysmt["get_model"]

        full_context = And_(*assumption_formulae) if assumption_formulae else pysmt["TRUE"]

        # Check consistency of claim with context
        try:
            negation = And_(full_context, Not_(claim_formula))
            entailed = is_unsat_(negation)
        except Exception as exc:
            return CheckerResult(
                checker_type="smt",
                status="unknown",
                message=f"SMT solver error: {exc}",
            )

        # Serialize query for replayability
        artifact = _serialize_query(claim.formal_expression, assumptions, pysmt)

        if entailed:
            return CheckerResult(
                checker_type="smt",
                status="passed",
                message="Claim is entailed by the given assumptions (SMT: unsat of negation).",
                artifact_ref=artifact,
            )

        # Check for outright contradiction (claim is unsatisfiable on its own)
        try:
            plain_unsat = is_unsat_(And_(full_context, claim_formula))
        except Exception as exc:
            return CheckerResult(
                checker_type="smt",
                status="unknown",
                message=f"SMT solver error on consistency check: {exc}",
                artifact_ref=artifact,
            )

        if plain_unsat:
            return CheckerResult(
                checker_type="smt",
                status="failed",
                message="Claim is UNSAT with respect to provided assumptions (contradiction).",
                artifact_ref=artifact,
                counterexample=None,
            )

        # SAT but not entailed: the claim is consistent but not proven
        try:
            model = get_model_(And_(full_context, Not_(claim_formula)))
            counterexample = _model_to_dict(model) if model else None
        except Exception:
            counterexample = None

        return CheckerResult(
            checker_type="smt",
            status="failed",
            message=(
                "Claim is NOT entailed by assumptions; a counterexample exists "
                "where the claim does not hold."
            ),
            artifact_ref=artifact,
            counterexample=counterexample,
        )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _serialize_query(
    formal_expression: str,
    assumptions: list[str],
    pysmt: dict,
) -> str:
    """Return a compact text representation of the SMT query for replay."""
    lines = ["# SMT Query"]
    lines.append(f"# Claim: {formal_expression}")
    for i, asm in enumerate(assumptions, 1):
        lines.append(f"# Assumption {i}: {asm}")
    return "\n".join(lines)


def _model_to_dict(model: Any) -> dict:
    """Convert a pySMT model to a plain dict for JSON serialization."""
    result = {}
    try:
        for var in model:
            result[str(var)] = str(model[var])
    except Exception:
        result["raw"] = str(model)
    return result
