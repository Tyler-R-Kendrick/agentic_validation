"""Tests for Pydantic schemas."""

import pytest
from pydantic import ValidationError

from agentic_validation.schemas import (
    AgentResult,
    CheckerResult,
    CritiqueLabel,
    FormalClaim,
    ReasoningStep,
    ReasoningTrace,
    SummaryState,
    TaskInput,
)


class TestTaskInput:
    def test_minimal_task_input(self):
        task = TaskInput(task_id="t1", goal="Is 2+2=4?")
        assert task.task_id == "t1"
        assert task.goal == "Is 2+2=4?"
        assert task.max_iterations == 6
        assert task.require_symbolic_checking is True

    def test_full_task_input(self):
        task = TaskInput(
            task_id="t2",
            goal="Prove P=NP",
            context={"domain": "cs"},
            constraints=["must be polynomial"],
            evidence=[{"source": "paper", "text": "..."}],
            require_formal_proof=True,
            require_symbolic_checking=True,
            max_iterations=3,
            max_branches=2,
        )
        assert task.require_formal_proof is True
        assert task.max_branches == 2


class TestFormalClaim:
    def test_default_status(self):
        claim = FormalClaim(
            claim_id="c1",
            source_step_id="s1",
            claim_text="x > 0",
            formalization_target="smt",
        )
        assert claim.status == "pending"
        assert claim.formal_expression is None

    def test_invalid_target_rejected(self):
        with pytest.raises(ValidationError):
            FormalClaim(
                claim_id="c2",
                source_step_id="s1",
                claim_text="blah",
                formalization_target="coq",  # not allowed
            )

    def test_all_statuses(self):
        for status in ("pending", "passed", "failed", "not_applicable"):
            claim = FormalClaim(
                claim_id="c3",
                source_step_id="s1",
                claim_text="x > 0",
                formalization_target="none",
                status=status,
            )
            assert claim.status == status


class TestCritiqueLabel:
    def test_valid_label(self):
        label = CritiqueLabel(
            label="missing_premise",
            severity="high",
            rationale="The premise P is not stated.",
        )
        assert label.severity == "high"

    def test_invalid_label(self):
        with pytest.raises(ValidationError):
            CritiqueLabel(label="bad_label", severity="low", rationale="x")

    def test_invalid_severity(self):
        with pytest.raises(ValidationError):
            CritiqueLabel(
                label="contradiction",
                severity="critical",  # not allowed
                rationale="x",
            )


class TestCheckerResult:
    def test_smt_result(self):
        r = CheckerResult(
            checker_type="smt",
            status="passed",
            message="Entailed.",
        )
        assert r.counterexample is None
        assert r.artifact_ref is None

    def test_with_counterexample(self):
        r = CheckerResult(
            checker_type="smt",
            status="failed",
            message="Not entailed.",
            counterexample={"x": "0"},
        )
        assert r.counterexample == {"x": "0"}

    def test_invalid_checker_type(self):
        with pytest.raises(ValidationError):
            CheckerResult(checker_type="z3", status="passed", message="ok")


class TestReasoningStep:
    def test_defaults(self):
        step = ReasoningStep(step_id="s1", text="Step one.")
        assert step.status == "pending"
        assert step.depends_on == []
        assert step.formalizable is False

    def test_all_statuses(self):
        for status in ("pending", "accepted", "failed", "repaired", "discarded"):
            step = ReasoningStep(step_id="s1", text="x", status=status)
            assert step.status == status


class TestReasoningTrace:
    def test_empty_trace(self):
        trace = ReasoningTrace(task_id="t1", goal="G")
        assert trace.steps == []
        assert isinstance(trace.summary_state, SummaryState)

    def test_trace_with_steps(self):
        step = ReasoningStep(step_id="s1", text="First step.")
        trace = ReasoningTrace(task_id="t1", goal="G", steps=[step])
        assert len(trace.steps) == 1


class TestSummaryState:
    def test_defaults(self):
        state = SummaryState()
        assert state.accepted_facts == []
        assert state.open_obligations == []


class TestAgentResult:
    def test_agent_result(self):
        step = ReasoningStep(step_id="s1", text="Done.", status="accepted")
        result = AgentResult(
            task_id="t1",
            final_answer="Yes",
            verification_status="soft_verified",
            accepted_steps=[step],
            failed_steps=[],
            checker_artifacts=[],
            repair_history=[],
            summary_state={},
        )
        assert result.verification_status == "soft_verified"
        assert result.final_answer == "Yes"

    def test_rejected_status(self):
        result = AgentResult(
            task_id="t1",
            final_answer=None,
            verification_status="rejected",
            accepted_steps=[],
            failed_steps=[],
            checker_artifacts=[],
            repair_history=[],
            summary_state={},
        )
        assert result.final_answer is None
        assert result.verification_status == "rejected"
