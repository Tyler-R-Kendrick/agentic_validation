"""Tests for agent orchestration helpers and repair-loop control flow."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import agentic_validation.agent as agent_module
from agentic_validation.agent import (
    _apply_updated_claims,
    _collect_checker_feedback,
    _critique_all,
    _escalate,
    _find_failing_regions,
    _find_step,
    _find_step_obj,
    _formalize_all,
    _region_improved,
    _run_checks,
    _splice_steps,
    _unresolved_critical_failures,
    _update_summary_state,
    run_agent,
)
from agentic_validation.persistence import init_db
from agentic_validation.schemas import (
    CheckerResult,
    CritiqueLabel,
    FormalClaim,
    ReasoningStep,
    ReasoningTrace,
    TaskInput,
)


def _label(severity: str = "high") -> CritiqueLabel:
    return CritiqueLabel(label="missing_premise", severity=severity, rationale="x")


def _step(step_id: str, **kwargs) -> ReasoningStep:
    data = {"step_id": step_id, "text": f"step-{step_id}"}
    data.update(kwargs)
    return ReasoningStep(**data)


def _claim(step_id: str, target: str = "smt", **kwargs) -> FormalClaim:
    data = {
        "claim_id": f"claim-{step_id}",
        "source_step_id": step_id,
        "claim_text": f"claim-{step_id}",
        "formalization_target": target,
        "formal_expression": "TRUE()",
    }
    data.update(kwargs)
    return FormalClaim(**data)


class DummyCritic:
    def critique_step(self, step, accepted_steps, assumptions):
        del accepted_steps, assumptions
        if step.step_id == "s1":
            return []
        if step.step_id == "s2":
            return [_label("medium")]
        return [_label("high")]

    def critique_trace(self, trace):
        del trace
        return {"global_issues": [], "open_obligations": ["obligation"]}


class DummyFormalizer:
    def formalize(self, step, goal):
        del goal
        return _claim(step.step_id, target="lean" if step.step_id == "s2" else "smt")


class RecordingChecker:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def check(self, claim, assumptions, steps):
        self.calls.append((claim.claim_id, tuple(assumptions), tuple(step.step_id for step in steps)))
        return self.result


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    db = tmp_path / "agent.db"
    monkeypatch.setattr(agent_module, "_DB_PATH", db)
    init_db(db)
    yield


class TestAgentHelpers:
    def test_critique_all_updates_statuses_and_obligations(self):
        trace = ReasoningTrace(
            task_id="t",
            goal="g",
            assumptions=["A"],
            steps=[
                _step("s1"),
                _step("s2"),
                _step("s3"),
                _step("s4", status="discarded"),
            ],
        )

        result = _critique_all(trace, DummyCritic(), "run-1")

        assert [step.status for step in result.steps] == ["accepted", "pending", "failed", "discarded"]
        assert result.summary_state.open_obligations == ["obligation"]

    def test_formalize_all_preserves_external_claims(self):
        trace = ReasoningTrace(
            task_id="t",
            goal="g",
            steps=[_step("s1", formalizable=True), _step("s2", formalizable=False)],
            formal_claims=[_claim("external", source_step_id="external")],
        )

        result = _formalize_all(trace, DummyFormalizer(), TaskInput(task_id="t", goal="g"), "run-1")

        assert {claim.source_step_id for claim in result.formal_claims} == {"external", "s1"}

    def test_run_checks_routes_and_updates_steps(self):
        trace = ReasoningTrace(
            task_id="t",
            goal="g",
            assumptions=["A"],
            steps=[
                _step("s1", status="pending"),
                _step("s2", status="pending"),
                _step("s3", status="repaired", checker_results=[CheckerResult(checker_type="smt", status="failed", message="old")]),
            ],
            formal_claims=[
                _claim("s1", target="smt"),
                _claim("s2", target="lean"),
                _claim("s3", target="smt", status="passed"),
                _claim("skip", target="none", status="failed"),
                _claim("s4", target="none", status="pending"),
            ],
        )
        smt_checker = RecordingChecker(
            CheckerResult(checker_type="smt", status="passed", message="ok", artifact_ref="smt-artifact")
        )
        lean_checker = RecordingChecker(
            CheckerResult(checker_type="lean", status="failed", message="bad", artifact_ref="lean-artifact")
        )
        task = TaskInput(
            task_id="t",
            goal="g",
            require_symbolic_checking=True,
            require_formal_proof=True,
        )

        checked_trace, artifacts = _run_checks(trace, smt_checker, lean_checker, task, "run-1")

        assert checked_trace.steps[0].status == "accepted"
        assert checked_trace.steps[1].status == "failed"
        assert checked_trace.steps[2].checker_results[0].status == "passed"
        assert {artifact["claim_id"] for artifact in artifacts} == {
            "claim-s1",
            "claim-s2",
            "claim-s3",
            "claim-s4",
        }
        assert next(artifact for artifact in artifacts if artifact["claim_id"] == "claim-s4")["checker_type"] == "rubric"

    def test_apply_updated_claims_replaces_and_appends(self):
        trace = ReasoningTrace(
            task_id="t",
            goal="g",
            formal_claims=[_claim("s1"), _claim("s2")],
        )

        _apply_updated_claims(trace, [_claim("s2", formal_expression="FALSE()"), _claim("s3")])

        assert [claim.source_step_id for claim in trace.formal_claims] == ["s1", "s2", "s3"]
        assert trace.formal_claims[1].formal_expression == "FALSE()"

    def test_find_failing_regions_propagates_failed_dependencies(self):
        trace = ReasoningTrace(
            task_id="t",
            goal="g",
            steps=[
                _step("s1", status="failed"),
                _step("s2", depends_on=["s1"]),
                _step("s3", status="discarded", depends_on=["s2"]),
            ],
        )

        failing = _find_failing_regions(trace)

        assert [step.step_id for step in failing] == ["s1", "s2"]
        assert trace.steps[1].status == "failed"

    def test_region_improved_checks_status_and_label_count(self):
        old_trace = ReasoningTrace(task_id="t", goal="g", steps=[_step("s1", status="failed", critique_labels=[_label("high"), _label("high")])])
        new_trace = ReasoningTrace(task_id="t", goal="g", steps=[_step("s1", status="pending", critique_labels=[_label("high")])])

        assert _region_improved(old_trace, new_trace, old_trace.steps[0]) is True
        assert _region_improved(old_trace, ReasoningTrace(task_id="t", goal="g"), old_trace.steps[0]) is False

    def test_splice_steps_and_find_helpers(self):
        trace = ReasoningTrace(task_id="t", goal="g", steps=[_step("s1"), _step("s2")])

        result = _splice_steps(trace, [trace.steps[0]], [_step("sx", status="repaired")])

        assert [step.step_id for step in result.steps] == ["sx", "s2"]
        assert _find_step(result, "missing") == "discarded"
        assert _find_step_obj(result, "sx").step_id == "sx"
        assert _find_step_obj(result, "missing") is None

    def test_collect_checker_feedback_and_summary_state(self):
        step = _step(
            "s1",
            status="accepted",
            checker_results=[CheckerResult(checker_type="smt", status="passed", message="ok")],
            critique_labels=[_label("medium")],
        )
        trace = ReasoningTrace(task_id="t", goal="g", steps=[step, _step("s2", status="failed")])

        feedback = _collect_checker_feedback(step)
        _update_summary_state(trace)

        assert len(feedback) == 2
        assert trace.summary_state.accepted_facts == ["step-s1"]
        assert trace.summary_state.failed_regions == ["s2"]
        assert trace.summary_state.best_partial_solutions == ["step-s1"]

    def test_escalate_returns_original_trace_when_no_new_branches(self):
        trace = ReasoningTrace(task_id="t", goal="g")
        task = TaskInput(task_id="t", goal="g", max_branches=1)

        result = _escalate(
            trace,
            task,
            generator=SimpleNamespace(forward=lambda task: trace),
            critic=DummyCritic(),
            formalizer=DummyFormalizer(),
            smt_checker=RecordingChecker(CheckerResult(checker_type="smt", status="passed", message="ok")),
            lean_checker=RecordingChecker(CheckerResult(checker_type="lean", status="passed", message="ok")),
            aggregator=SimpleNamespace(aggregate=lambda branches, summary_state: branches[-1]),
            run_id="run-1",
        )

        assert result is trace

    def test_escalate_aggregates_generated_branches(self):
        original = ReasoningTrace(task_id="t", goal="g", steps=[_step("s0", status="accepted")])
        branch = ReasoningTrace(task_id="t", goal="g", steps=[_step("s1", status="accepted")])
        task = TaskInput(task_id="t", goal="g", max_branches=2)

        result = _escalate(
            original,
            task,
            generator=SimpleNamespace(forward=lambda task: branch),
            critic=SimpleNamespace(
                critique_step=lambda step, accepted_steps, assumptions: [],
                critique_trace=lambda trace: {"global_issues": [], "open_obligations": []},
            ),
            formalizer=SimpleNamespace(formalize=lambda step, goal: _claim(step.step_id)),
            smt_checker=RecordingChecker(CheckerResult(checker_type="smt", status="passed", message="ok")),
            lean_checker=RecordingChecker(CheckerResult(checker_type="lean", status="passed", message="ok")),
            aggregator=SimpleNamespace(aggregate=lambda branches, summary_state: branches[-1]),
            run_id="run-1",
        )

        assert result.steps[0].step_id == "s1"

    def test_escalate_skips_failed_branch_generation(self):
        original = ReasoningTrace(task_id="t", goal="g")
        task = TaskInput(task_id="t", goal="g", max_branches=2)

        result = _escalate(
            original,
            task,
            generator=SimpleNamespace(forward=lambda task: (_ for _ in ()).throw(RuntimeError("boom"))),
            critic=DummyCritic(),
            formalizer=DummyFormalizer(),
            smt_checker=RecordingChecker(CheckerResult(checker_type="smt", status="passed", message="ok")),
            lean_checker=RecordingChecker(CheckerResult(checker_type="lean", status="passed", message="ok")),
            aggregator=SimpleNamespace(aggregate=lambda branches, summary_state: branches[-1]),
            run_id="run-1",
        )

        assert result is original

    def test_unresolved_critical_failures(self):
        trace = ReasoningTrace(
            task_id="t",
            goal="g",
            steps=[
                _step("ok", status="accepted"),
                _step("s1", status="failed", critique_labels=[_label("high")]),
                _step(
                    "s2",
                    status="failed",
                    critique_labels=[_label("high")],
                    checker_results=[CheckerResult(checker_type="smt", status="passed", message="ok")],
                ),
            ],
        )

        assert _unresolved_critical_failures(trace) is True
        trace.steps[1].checker_results = [CheckerResult(checker_type="smt", status="passed", message="ok")]
        assert _unresolved_critical_failures(trace) is False


class TestRunAgentLoops:
    def test_run_agent_repairs_a_failed_region(self, monkeypatch):
        repaired_step = _step("s1", text="fixed", status="repaired")
        updated_claim = _claim("s1", formal_expression="updated")

        monkeypatch.setattr(agent_module, "GeneratorModule", lambda: SimpleNamespace(
            forward=lambda task: ReasoningTrace(task_id=task.task_id, goal=task.goal, steps=[_step("s1")])
        ))
        monkeypatch.setattr(
            agent_module,
            "CriticModule",
            lambda: SimpleNamespace(
                critique_step=lambda step, accepted_steps, assumptions: [] if step.text == "fixed" else [_label("high")],
                critique_trace=lambda trace: {"global_issues": [], "open_obligations": []},
            ),
        )
        monkeypatch.setattr(agent_module, "FormalizerModule", lambda: SimpleNamespace(formalize=lambda step, goal: _claim(step.step_id)))
        monkeypatch.setattr(
            agent_module,
            "SMTChecker",
            lambda: SimpleNamespace(check=lambda claim, assumptions, steps: CheckerResult(checker_type="smt", status="unknown", message="skip")),
        )
        monkeypatch.setattr(
            agent_module,
            "LeanChecker",
            lambda: SimpleNamespace(check=lambda claim, assumptions, steps: CheckerResult(checker_type="lean", status="unknown", message="skip")),
        )
        monkeypatch.setattr(
            agent_module,
            "RepairModule",
            lambda: SimpleNamespace(repair=lambda **kwargs: ([repaired_step], [updated_claim])),
        )
        monkeypatch.setattr(agent_module, "AggregatorModule", lambda: SimpleNamespace(aggregate=lambda branches, summary_state: branches[0]))
        monkeypatch.setattr(
            agent_module,
            "GateModule",
            lambda: SimpleNamespace(
                gate=lambda trace, summary_state: {
                    "final_answer": trace.steps[0].text,
                    "verification_status": "corrected",
                }
            ),
        )

        result = run_agent(TaskInput(task_id="repair", goal="g", max_iterations=2, max_branches=1))

        assert result.final_answer == "fixed"
        assert len(result.repair_history) == 1
        assert result.accepted_steps[0].text == "fixed"

    def test_run_agent_escalates_after_unsuccessful_repair(self, monkeypatch):
        base_trace = ReasoningTrace(task_id="escalate", goal="g", steps=[_step("s1")])

        monkeypatch.setattr(agent_module, "GeneratorModule", lambda: SimpleNamespace(forward=lambda task: base_trace.model_copy(deep=True)))
        monkeypatch.setattr(
            agent_module,
            "CriticModule",
            lambda: SimpleNamespace(
                critique_step=lambda step, accepted_steps, assumptions: [_label("high")],
                critique_trace=lambda trace: {"global_issues": [], "open_obligations": []},
            ),
        )
        monkeypatch.setattr(agent_module, "FormalizerModule", lambda: SimpleNamespace(formalize=lambda step, goal: _claim(step.step_id)))
        monkeypatch.setattr(
            agent_module,
            "SMTChecker",
            lambda: SimpleNamespace(check=lambda claim, assumptions, steps: CheckerResult(checker_type="smt", status="unknown", message="skip")),
        )
        monkeypatch.setattr(
            agent_module,
            "LeanChecker",
            lambda: SimpleNamespace(check=lambda claim, assumptions, steps: CheckerResult(checker_type="lean", status="unknown", message="skip")),
        )
        monkeypatch.setattr(
            agent_module,
            "RepairModule",
            lambda: SimpleNamespace(repair=lambda **kwargs: ([_step("s1", status="failed")], [])),
        )
        monkeypatch.setattr(
            agent_module,
            "AggregatorModule",
            lambda: SimpleNamespace(aggregate=lambda branches, summary_state: branches[0]),
        )
        monkeypatch.setattr(
            agent_module,
            "GateModule",
            lambda: SimpleNamespace(
                gate=lambda trace, summary_state: {
                    "final_answer": None,
                    "verification_status": "rejected",
                }
            ),
        )

        result = run_agent(TaskInput(task_id="escalate", goal="g", max_iterations=2, max_branches=2))

        assert result.verification_status == "rejected"
        assert result.failed_steps[0].step_id == "s1"

    def test_run_agent_stops_after_exhausting_repair_attempts(self, monkeypatch):
        monkeypatch.setattr(agent_module, "GeneratorModule", lambda: SimpleNamespace(
            forward=lambda task: ReasoningTrace(task_id=task.task_id, goal=task.goal, steps=[_step("s1")])
        ))
        monkeypatch.setattr(
            agent_module,
            "CriticModule",
            lambda: SimpleNamespace(
                critique_step=lambda step, accepted_steps, assumptions: [_label("high")],
                critique_trace=lambda trace: {"global_issues": [], "open_obligations": []},
            ),
        )
        monkeypatch.setattr(agent_module, "FormalizerModule", lambda: SimpleNamespace(formalize=lambda step, goal: _claim(step.step_id)))
        monkeypatch.setattr(
            agent_module,
            "SMTChecker",
            lambda: SimpleNamespace(check=lambda claim, assumptions, steps: CheckerResult(checker_type="smt", status="passed", message="ok")),
        )
        monkeypatch.setattr(
            agent_module,
            "LeanChecker",
            lambda: SimpleNamespace(check=lambda claim, assumptions, steps: CheckerResult(checker_type="lean", status="passed", message="ok")),
        )
        monkeypatch.setattr(
            agent_module,
            "RepairModule",
            lambda: SimpleNamespace(repair=lambda **kwargs: ([_step("s1", status="failed")], [])),
        )
        monkeypatch.setattr(
            agent_module,
            "AggregatorModule",
            lambda: SimpleNamespace(
                aggregate=lambda branches, summary_state: ReasoningTrace(
                    task_id="repair-limit",
                    goal="g",
                    steps=[_step("s1", status="failed", checker_results=[CheckerResult(checker_type="smt", status="passed", message="ok")])],
                )
            ),
        )
        monkeypatch.setattr(
            agent_module,
            "GateModule",
            lambda: SimpleNamespace(
                gate=lambda trace, summary_state: {
                    "final_answer": None,
                    "verification_status": "unverified",
                }
            ),
        )

        result = run_agent(TaskInput(task_id="repair-limit", goal="g", max_iterations=4, max_branches=2))

        assert result.verification_status == "unverified"
