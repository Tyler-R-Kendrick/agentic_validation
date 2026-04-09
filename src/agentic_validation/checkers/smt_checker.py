"""SMT checker adapter using pySMT / Z3.

The adapter compiles a FormalClaim's formal_expression into a pySMT formula
and runs it through Z3 to determine satisfiability.

Design notes
------------
* Claims whose formal_expression is None or whose formalization_target is not
  "smt" are returned immediately with status "unknown".
* The formal_expression is parsed via the Python AST before execution to ensure
  it consists only of safe, whitelisted pySMT constructor calls and literals.
  This prevents arbitrary code execution from LM-generated expressions.
* Assumptions are rendered as additional pySMT assertions.
* The exact solver query is stored in the returned CheckerResult so every call
  is replayable.
"""

from __future__ import annotations

import ast
import logging
from typing import Any

from ..schemas import CheckerResult, FormalClaim, ReasoningStep

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed identifiers in SMT expressions (whitelist)
# ---------------------------------------------------------------------------

_ALLOWED_NAMES = frozenset(
    {
        # Constructors
        "Symbol", "Int", "Real", "Bool",
        # Arithmetic
        "Plus", "Minus", "Times",
        # Comparison
        "Equals", "GE", "GT", "LE", "LT",
        # Boolean
        "And", "Or", "Not", "Implies",
        # Constants
        "TRUE", "FALSE",
        # Types
        "INT", "REAL", "BOOL",
    }
)

# ---------------------------------------------------------------------------
# AST-based expression validator
# ---------------------------------------------------------------------------


def _validate_expression(expr: str) -> bool:
    """Return True iff *expr* consists only of whitelisted pySMT identifiers.

    Allowed nodes: function calls, names in _ALLOWED_NAMES, integer literals,
    float literals, string literals (for Symbol names), and tuples/lists of
    the above.  Any other construct (attribute access, subscript, import,
    exec, etc.) causes rejection.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Expression):
            continue
        if isinstance(node, ast.Call):
            # Function must be a bare name in the whitelist
            if not isinstance(node.func, ast.Name):
                return False
            if node.func.id not in _ALLOWED_NAMES:
                return False
        elif isinstance(node, ast.Name):
            if node.id not in _ALLOWED_NAMES:
                return False
        elif isinstance(node, ast.Constant):
            # int, float, str literals are fine
            if not isinstance(node.value, (int, float, str, bool)):
                return False
        elif isinstance(node, (ast.Tuple, ast.List)):
            continue  # children will be visited
        elif isinstance(node, (ast.Load, ast.Store, ast.Del)):
            continue  # context nodes
        else:
            return False
    return True


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

        return dict(
            Symbol=Symbol, Int=Int, Real=Real, Bool=Bool,
            Plus=Plus, Minus=Minus, Times=Times,
            Equals=Equals, GE=GE, GT=GT, LE=LE, LT=LT,
            And=And, Or=Or, Not=Not, Implies=Implies,
            Solver=Solver, get_model=get_model,
            is_sat=is_sat, is_unsat=is_unsat,
            TRUE=TRUE, FALSE=FALSE,
            INT=INT, REAL=REAL, BOOL=BOOL,
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

        # Validate expression against whitelist before execution
        if not _validate_expression(claim.formal_expression):
            return CheckerResult(
                checker_type="smt",
                status="unknown",
                message=(
                    "formal_expression contains disallowed constructs; "
                    "only whitelisted pySMT identifiers are permitted."
                ),
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
        # Build a restricted sandbox: only whitelisted pySMT names, no builtins
        sandbox: dict[str, Any] = {k: pysmt[k] for k in _ALLOWED_NAMES if k in pysmt}
        sandbox["__builtins__"] = {}

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

        # Evaluate and collect assumption formulae
        assumption_formulae = []
        for asm in assumptions:
            if not _validate_expression(asm):
                logger.debug("Skipping assumption with disallowed constructs: %r", asm)
                continue
            try:
                f = eval(asm, sandbox)  # noqa: S307
                assumption_formulae.append(f)
            except Exception as exc:
                logger.debug("Skipping assumption %r: %s", asm, exc)

        # Build the query
        And_ = pysmt["And"]
        Not_ = pysmt["Not"]
        is_unsat_ = pysmt["is_unsat"]
        get_model_ = pysmt["get_model"]

        full_context = And_(*assumption_formulae) if assumption_formulae else pysmt["TRUE"]

        # Check entailment: assumptions => claim (i.e., assumptions /\ NOT claim is unsat)
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
        artifact = _serialize_query(claim.formal_expression, assumptions)

        if entailed:
            return CheckerResult(
                checker_type="smt",
                status="passed",
                message="Claim is entailed by the given assumptions (SMT: unsat of negation).",
                artifact_ref=artifact,
            )

        # Check for outright contradiction (claim is unsatisfiable with context)
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

        # SAT but not entailed: a counterexample exists
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
