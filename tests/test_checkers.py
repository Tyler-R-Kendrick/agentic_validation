"""Tests for the SMT and Lean checker adapters."""

import subprocess
from types import SimpleNamespace

from agentic_validation.checkers import LeanChecker, SMTChecker
from agentic_validation.checkers.smt_checker import _validate_expression
from agentic_validation.schemas import CheckerResult, FormalClaim, ReasoningStep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claim(
    *,
    claim_id: str = "c1",
    source_step_id: str = "s1",
    claim_text: str = "test",
    target: str = "smt",
    expression: str | None = None,
    status: str = "pending",
) -> FormalClaim:
    return FormalClaim(
        claim_id=claim_id,
        source_step_id=source_step_id,
        claim_text=claim_text,
        formalization_target=target,
        formal_expression=expression,
        status=status,
    )


def _step(step_id: str = "s1", text: str = "x", status: str = "accepted") -> ReasoningStep:
    return ReasoningStep(step_id=step_id, text=text, status=status)


# ---------------------------------------------------------------------------
# SMTChecker tests
# ---------------------------------------------------------------------------

class TestSMTChecker:
    def setup_method(self):
        self.checker = SMTChecker()

    def test_non_smt_claim_returns_unknown(self):
        claim = _claim(target="lean")
        result = self.checker.check(claim, [], [])
        assert result.checker_type == "smt"
        assert result.status == "unknown"

    def test_missing_expression_returns_unknown(self):
        claim = _claim(target="smt", expression=None)
        result = self.checker.check(claim, [], [])
        assert result.status == "unknown"

    def test_tautology_passed(self):
        """GT(Int(1), Int(0)) is always true — should be entailed."""
        claim = _claim(
            target="smt",
            expression="GT(Int(1), Int(0))",
        )
        result = self.checker.check(claim, [], [])
        # Either passed (if pySMT+Z3 available) or unknown (if not)
        assert result.status in ("passed", "unknown"), result.message

    def test_contradiction_failed(self):
        """Claim that 1 > 2 is a contradiction."""
        claim = _claim(
            target="smt",
            expression="GT(Int(1), Int(2))",
        )
        result = self.checker.check(claim, [], [])
        # Either failed (if pySMT+Z3 available) or unknown (if not)
        assert result.status in ("failed", "unknown"), result.message

    def test_invalid_expression_returns_unknown(self):
        """A malformed expression should not raise; returns unknown."""
        claim = _claim(
            target="smt",
            expression="this is not valid python or smt",
        )
        result = self.checker.check(claim, [], [])
        assert result.status == "unknown"

    def test_disallowed_expression_returns_unknown(self):
        """Expressions with disallowed constructs must be rejected."""
        claim = _claim(
            target="smt",
            expression="__import__('os').system('echo pwned')",
        )
        result = self.checker.check(claim, [], [])
        assert result.status == "unknown"
        assert "disallowed" in result.message.lower()

    def test_result_type(self):
        claim = _claim(target="smt", expression="GT(Int(1), Int(0))")
        result = self.checker.check(claim, [], [])
        assert isinstance(result, CheckerResult)
        assert result.checker_type == "smt"

    def test_with_assumption_entailment(self):
        """Given assumption x > 0, claim x >= 0 should be entailed."""
        claim = _claim(
            target="smt",
            expression="GE(Symbol('x', INT), Int(0))",
        )
        assumptions = ["GT(Symbol('x', INT), Int(0))"]
        result = self.checker.check(claim, assumptions, [])
        assert result.status in ("passed", "unknown")


# ---------------------------------------------------------------------------
# Expression validator tests
# ---------------------------------------------------------------------------

class TestValidateExpression:
    def test_simple_comparison_valid(self):
        assert _validate_expression("GT(Int(1), Int(0))") is True

    def test_nested_expression_valid(self):
        assert _validate_expression("And(GT(Int(2), Int(1)), LE(Int(0), Int(5)))") is True

    def test_symbol_with_type_valid(self):
        assert _validate_expression("Symbol('x', INT)") is True

    def test_import_disallowed(self):
        assert _validate_expression("__import__('os')") is False

    def test_attribute_access_disallowed(self):
        assert _validate_expression("os.system('echo x')") is False

    def test_unknown_name_disallowed(self):
        assert _validate_expression("FakeFunc(Int(1))") is False

    def test_empty_string_invalid(self):
        assert _validate_expression("") is False

    def test_bytes_literal_disallowed(self):
        assert _validate_expression("b'hello'") is False


# ---------------------------------------------------------------------------
# LeanChecker tests
# ---------------------------------------------------------------------------

class TestLeanChecker:
    def setup_method(self):
        self.checker = LeanChecker()

    def test_non_lean_claim_returns_unknown(self):
        claim = _claim(target="smt")
        result = self.checker.check(claim, [], [])
        assert result.checker_type == "lean"
        assert result.status == "unknown"

    def test_missing_expression_returns_unknown(self):
        claim = _claim(target="lean", expression=None)
        result = self.checker.check(claim, [], [])
        assert result.status == "unknown"

    def test_missing_binary_returns_unknown(self, monkeypatch):
        claim = _claim(
            target="lean",
            expression="∀ n : ℕ, n + 0 = n",
        )
        monkeypatch.setattr(self.checker, "_resolve_command", lambda: None)
        result = self.checker.check(claim, ["n : ℕ"], [])
        assert result.status == "unknown"
        assert "not available" in result.message.lower()

    def test_result_type(self):
        claim = _claim(target="lean", expression="True")
        result = self.checker.check(claim, [], [])
        assert isinstance(result, CheckerResult)
        assert result.checker_type == "lean"

    def test_theorem_generation(self):
        """_build_theorem should produce a non-empty string."""
        claim = _claim(target="lean", expression="n + 0 = n")
        theorem = self.checker._build_theorem(claim, ["n : ℕ"], [])
        assert "theorem" in theorem
        assert "n + 0 = n" in theorem
        assert "(n : ℕ)" in theorem
        assert "first" in theorem
        assert "simp" in theorem

    def test_successful_lean_run_returns_passed(self, monkeypatch):
        claim = _claim(target="lean", expression="True")
        monkeypatch.setattr(self.checker, "_resolve_command", lambda: ["lean"])
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="ok", stderr=""),
        )

        result = self.checker.check(claim, [], [])

        assert result.status == "passed"
        assert "verified" in result.message.lower()
        assert "lean" in (result.artifact_ref or "").lower()

    def test_failed_lean_run_returns_failed(self, monkeypatch):
        claim = _claim(target="lean", expression="False")
        monkeypatch.setattr(self.checker, "_resolve_command", lambda: ["lean"])
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="unsolved goals",
            ),
        )

        result = self.checker.check(claim, [], [])

        assert result.status == "failed"
        assert "unsolved goals" in result.message
        assert "returncode" in (result.artifact_ref or "")

    def test_timeout_returns_unknown(self, monkeypatch):
        claim = _claim(target="lean", expression="True")
        monkeypatch.setattr(self.checker, "_resolve_command", lambda: ["lean"])

        def _raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=["lean"], timeout=1)

        monkeypatch.setattr(subprocess, "run", _raise_timeout)

        result = self.checker.check(claim, [], [])

        assert result.status == "unknown"
        assert "timed out" in result.message.lower()

    def test_resolve_command_prefers_lake(self, monkeypatch):
        def _which(name):
            return f"/usr/bin/{name}" if name == "lake" else None

        monkeypatch.setattr("agentic_validation.checkers.lean_checker.shutil.which", _which)

        assert self.checker._resolve_command() == ["lake", "env", "lean"]

    def test_subclass_override(self):
        """Subclassing and overriding _invoke_lean should work correctly."""

        class FakeLean(LeanChecker):
            def _invoke_lean(self, claim, theorem_statement):
                return CheckerResult(
                    checker_type="lean",
                    status="passed",
                    message="Proof found.",
                )

        checker = FakeLean()
        claim = _claim(target="lean", expression="True")
        result = checker.check(claim, [], [])
        assert result.status == "passed"
