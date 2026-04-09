"""Tests for the SMT and Lean checker adapters."""

import builtins
import json
import subprocess
from types import SimpleNamespace

from agentic_validation.checkers import LeanChecker, SMTChecker
import agentic_validation.checkers.smt_checker as smt_checker_module
from agentic_validation.checkers.smt_checker import (
    _get_pysmt,
    _model_to_dict,
    _serialize_query,
    _try_import_pysmt,
    _validate_expression,
)
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

    def test_missing_pysmt_returns_unknown(self, monkeypatch):
        claim = _claim(target="smt", expression="TRUE()")
        monkeypatch.setattr(smt_checker_module, "_get_pysmt", lambda: None)

        result = self.checker.check(claim, [], [])

        assert result.status == "unknown"
        assert "not available" in result.message.lower()

    def test_run_check_returns_failed_with_counterexample(self):
        result = self.checker._run_check(
            _claim(target="smt", expression="TRUE"),
            assumptions=["__import__('os')", "TRUE"],
            steps=[],
            pysmt={
                "And": lambda *args: ("and", args),
                "Not": lambda expr: ("not", expr),
                "TRUE": "TRUE",
                "is_unsat": lambda expr: False,
                "get_model": lambda expr: {"x": 0},
            },
        )

        assert result.status == "failed"
        assert result.counterexample == {"x": "0"}

    def test_run_check_returns_failed_for_unsat_claim(self):
        calls = []

        def _is_unsat(expr):
            calls.append(expr)
            return len(calls) == 2

        result = self.checker._run_check(
            _claim(target="smt", expression="TRUE"),
            assumptions=[],
            steps=[],
            pysmt={
                "And": lambda *args: ("and", args),
                "Not": lambda expr: ("not", expr),
                "TRUE": "TRUE",
                "is_unsat": _is_unsat,
                "get_model": lambda expr: None,
            },
        )

        assert result.status == "failed"
        assert "contradiction" in result.message.lower()

    def test_run_check_returns_unknown_when_solver_errors(self):
        result = self.checker._run_check(
            _claim(target="smt", expression="TRUE"),
            assumptions=[],
            steps=[],
            pysmt={
                "And": lambda *args: ("and", args),
                "Not": lambda expr: ("not", expr),
                "TRUE": "TRUE",
                "is_unsat": lambda expr: (_ for _ in ()).throw(RuntimeError("solver broke")),
                "get_model": lambda expr: None,
            },
        )

        assert result.status == "unknown"
        assert "solver broke" in result.message

    def test_run_check_skips_bad_assumptions_that_fail_eval(self):
        result = self.checker._run_check(
            _claim(target="smt", expression="TRUE"),
            assumptions=["Symbol('x', INT)"],
            steps=[],
            pysmt={
                "And": lambda *args: ("and", args),
                "Not": lambda expr: ("not", expr),
                "TRUE": "TRUE",
                "INT": "INT",
                "Symbol": lambda name, typ: (_ for _ in ()).throw(RuntimeError("bad assumption")),
                "is_unsat": lambda expr: True,
                "get_model": lambda expr: None,
            },
        )

        assert result.status == "passed"

    def test_run_check_returns_unknown_when_consistency_check_errors(self):
        calls = []

        def _is_unsat(expr):
            calls.append(expr)
            if len(calls) == 1:
                return False
            raise RuntimeError("consistency broke")

        result = self.checker._run_check(
            _claim(target="smt", expression="TRUE"),
            assumptions=[],
            steps=[],
            pysmt={
                "And": lambda *args: ("and", args),
                "Not": lambda expr: ("not", expr),
                "TRUE": "TRUE",
                "is_unsat": _is_unsat,
                "get_model": lambda expr: None,
            },
        )

        assert result.status == "unknown"
        assert "consistency broke" in result.message

    def test_run_check_handles_counterexample_lookup_failure(self):
        result = self.checker._run_check(
            _claim(target="smt", expression="TRUE"),
            assumptions=[],
            steps=[],
            pysmt={
                "And": lambda *args: ("and", args),
                "Not": lambda expr: ("not", expr),
                "TRUE": "TRUE",
                "is_unsat": lambda expr: False,
                "get_model": lambda expr: (_ for _ in ()).throw(RuntimeError("no model")),
            },
        )

        assert result.status == "failed"
        assert result.counterexample is None


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

    def test_plain_unknown_name_disallowed(self):
        assert _validate_expression("x") is False

    def test_empty_string_invalid(self):
        assert _validate_expression("") is False

    def test_bytes_literal_disallowed(self):
        assert _validate_expression("b'hello'") is False

    def test_list_literal_is_allowed_container(self):
        assert _validate_expression("['x', 'y']") is True

    def test_keyword_argument_disallowed(self):
        assert _validate_expression("Symbol(name='x', typename=INT)") is False

    def test_subscript_disallowed(self):
        assert _validate_expression("['x'][0]") is False

    def test_binary_operation_disallowed(self):
        assert _validate_expression("1 + 2") is False


class TestSMTHelpers:
    def test_try_import_pysmt_returns_none_on_import_error(self, monkeypatch):
        original_import = builtins.__import__

        def _raising_import(name, *args, **kwargs):
            if name.startswith("pysmt"):
                raise ImportError("missing pysmt")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _raising_import)

        assert _try_import_pysmt() is None

    def test_get_pysmt_caches_result(self, monkeypatch):
        monkeypatch.setattr(smt_checker_module, "_PYSMT", None)
        monkeypatch.setattr(smt_checker_module, "_try_import_pysmt", lambda: {"fake": True})

        assert _get_pysmt() == {"fake": True}
        assert _get_pysmt() == {"fake": True}

    def test_serialize_query_and_model_to_dict(self):
        artifact = _serialize_query("GT(Int(1), Int(0))", ["A", "B"])
        assert "# Claim: GT(Int(1), Int(0))" in artifact
        assert "# Assumption 2: B" in artifact

        class Model:
            def __iter__(self):
                return iter(["x"])

            def __getitem__(self, item):
                return 1

        assert _model_to_dict(Model()) == {"x": "1"}

    def test_model_to_dict_falls_back_to_raw_string(self):
        class Model:
            def __iter__(self):
                raise RuntimeError("boom")

            def __str__(self):
                return "raw-model"

        assert _model_to_dict(Model()) == {"raw": "raw-model"}


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

    def test_theorem_generation_with_hypothesis_uses_named_proofs(self):
        claim = _claim(target="lean", expression="p")

        theorem = self.checker._build_theorem(claim, ["p"], [])

        assert "(h0 : p)" in theorem
        assert "exact h0" in theorem
        assert "simpa using h0" in theorem

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

        artifact = json.loads(result.artifact_ref)
        assert artifact["returncode"] is None

    def test_resolve_command_prefers_lake(self, monkeypatch):
        def _which(name):
            return f"/usr/bin/{name}" if name == "lake" else None

        monkeypatch.setattr("agentic_validation.checkers.lean_checker.shutil.which", _which)
        monkeypatch.setattr(
            "agentic_validation.checkers.lean_checker._has_lake_project_file", lambda: True
        )

        assert self.checker._resolve_command() == ["lake", "env", "lean"]

    def test_resolve_command_skips_lake_without_project_file(self, monkeypatch):
        def _which(name):
            return f"/usr/bin/{name}"

        monkeypatch.setattr("agentic_validation.checkers.lean_checker.shutil.which", _which)
        monkeypatch.setattr(
            "agentic_validation.checkers.lean_checker._has_lake_project_file", lambda: False
        )

        assert self.checker._resolve_command() == ["lean"]

    def test_resolve_command_uses_explicit_command(self):
        checker = LeanChecker(command=["custom", "lean"])

        assert checker._resolve_command() == ["custom", "lean"]

    def test_resolve_command_falls_back_to_lean_binary(self, monkeypatch):
        monkeypatch.setattr(
            "agentic_validation.checkers.lean_checker.shutil.which",
            lambda name: "/usr/bin/lean" if name == "lean" else None,
        )

        assert self.checker._resolve_command() == ["lean"]

    def test_os_error_returns_unknown(self, monkeypatch):
        claim = _claim(target="lean", expression="True")
        monkeypatch.setattr(self.checker, "_resolve_command", lambda: ["lean"])
        monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")))

        result = self.checker.check(claim, [], [])

        assert result.status == "unknown"
        assert "boom" in result.message
        artifact = json.loads(result.artifact_ref)
        assert artifact["command"] == ["lean"]
        assert artifact["stderr"] == "boom"

    def test_normalize_bytes_and_binder_detection(self):
        artifact = smt_checker_module  # keep import usage local for lint
        del artifact
        from agentic_validation.checkers.lean_checker import _looks_like_binder, _normalize_output

        assert _looks_like_binder("n : ℕ") is True
        assert _looks_like_binder("plain proposition") is False
        assert _normalize_output(b"\xe2\x9c\x93") == "✓"

    def test_sanitize_identifier_strips_unsafe_chars(self):
        from agentic_validation.checkers.lean_checker import _sanitize_identifier

        assert _sanitize_identifier("c-1") == "c_1"
        assert _sanitize_identifier("../../etc/passwd") == "etc_passwd"
        assert _sanitize_identifier("a b c") == "a_b_c"
        assert _sanitize_identifier("---") == "anonymous"
        assert _sanitize_identifier("") == "anonymous"
        assert _sanitize_identifier("valid_id") == "valid_id"

    def test_has_lake_project_file(self, tmp_path, monkeypatch):
        from agentic_validation.checkers.lean_checker import _has_lake_project_file

        monkeypatch.chdir(tmp_path)
        assert _has_lake_project_file() is False

        (tmp_path / "lakefile.lean").write_text("")
        assert _has_lake_project_file() is True

    def test_theorem_sanitizes_claim_id(self):
        claim = _claim(target="lean", claim_id="../../evil", expression="True")
        theorem = self.checker._build_theorem(claim, [], [])
        assert "claim_evil" in theorem
        assert ".." not in theorem

    def test_invoke_lean_sanitizes_filename(self, monkeypatch):
        """Ensure the .lean file uses the sanitized claim_id, not the raw one."""
        claim = _claim(target="lean", claim_id="../escape/attempt", expression="True")
        monkeypatch.setattr(self.checker, "_resolve_command", lambda: ["lean"])

        invoked_args: list[list[str]] = []

        def _fake_run(*args, **kwargs):
            invoked_args.append(list(args[0]))
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        result = self.checker.check(claim, [], [])
        assert result.status == "passed"
        # The file path in the subprocess call must use the sanitized name
        lean_path = invoked_args[0][-1]
        assert ".." not in lean_path
        assert lean_path.endswith("escape_attempt.lean")

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
