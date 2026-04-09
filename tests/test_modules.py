"""Tests for DSPy-facing modules and their helper functions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentic_validation.modules import (
    AggregatorModule,
    CriticModule,
    FormalizerModule,
    GateModule,
    GeneratorModule,
    RepairModule,
    _extract_json,
    _stub_gate,
    _stub_trace,
)
from agentic_validation.schemas import (
    CritiqueLabel,
    ReasoningStep,
    ReasoningTrace,
    SummaryState,
    TaskInput,
)


def _task() -> TaskInput:
    return TaskInput(task_id="task-1", goal="Goal")


def _step(step_id: str = "s1", **kwargs) -> ReasoningStep:
    data = {"step_id": step_id, "text": f"step-{step_id}"}
    data.update(kwargs)
    return ReasoningStep(**data)


class TestGeneratorModule:
    def test_forward_validates_predict_output(self):
        module = GeneratorModule()
        module.predict = lambda **_: SimpleNamespace(trace_json='{"steps": []}')

        trace = module.forward(_task())

        assert trace.task_id == "task-1"
        assert trace.goal == "Goal"

    def test_forward_falls_back_to_stub_trace(self):
        module = GeneratorModule()
        module.predict = lambda **_: (_ for _ in ()).throw(ValueError("boom"))

        trace = module.forward(_task())

        assert trace.steps[0].text == "Stub derivation for goal: Goal"


class TestCriticModule:
    def test_critique_step_parses_labels(self):
        module = CriticModule()
        module.predict_step = lambda **_: SimpleNamespace(
            critique_json='[{"label":"missing_premise","severity":"high","rationale":"x"}]'
        )

        labels = module.critique_step(_step(), [], [])

        assert labels == [
            CritiqueLabel(label="missing_premise", severity="high", rationale="x")
        ]

    def test_critique_step_returns_empty_for_non_list_payload(self):
        module = CriticModule()
        module.predict_step = lambda **_: SimpleNamespace(critique_json='{"label":"missing_premise"}')

        assert module.critique_step(_step(), [], []) == []

    def test_critique_step_falls_back_on_error(self):
        module = CriticModule()
        module.predict_step = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))

        assert module.critique_step(_step(), [], []) == []

    def test_critique_trace_parses_json(self):
        module = CriticModule()
        module.predict_trace = lambda **_: SimpleNamespace(
            global_critique_json='{"global_issues":[],"open_obligations":["prove it"]}'
        )

        critique = module.critique_trace(ReasoningTrace(task_id="t", goal="g"))

        assert critique["open_obligations"] == ["prove it"]

    def test_critique_trace_falls_back_on_error(self):
        module = CriticModule()
        module.predict_trace = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))

        assert module.critique_trace(ReasoningTrace(task_id="t", goal="g")) == {
            "global_issues": [],
            "open_obligations": [],
        }


class TestFormalizerModule:
    def test_formalize_uses_defaults_when_missing(self):
        module = FormalizerModule()
        module.predict = lambda **_: SimpleNamespace(claim_json='{"status":"pending"}')

        claim = module.formalize(_step(formalizable=True), "goal")

        assert claim.claim_id == "claim-s1"
        assert claim.source_step_id == "s1"
        assert claim.claim_text == "step-s1"
        assert claim.formalization_target == "none"

    def test_formalize_falls_back_when_predict_fails(self):
        module = FormalizerModule()
        module.predict = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))

        claim = module.formalize(_step(formalizable=True), "goal")

        assert claim.status == "not_applicable"


class TestRepairModule:
    def test_repair_merges_steps_and_claims(self):
        module = RepairModule()
        module.predict = lambda **_: SimpleNamespace(
            repair_json="""
            {
              "repaired_steps": [{"text": "fixed"}],
              "updated_formal_claims": [
                {
                  "claim_id": "c1",
                  "source_step_id": "s1",
                  "claim_text": "fixed",
                  "formalization_target": "smt",
                  "formal_expression": "TRUE()"
                },
                {"claim_id": "bad"}
              ]
            }
            """
        )

        steps, claims = module.repair(
            failed_steps=[_step("s1", status="failed"), _step("s2", status="failed")],
            accepted_steps=[_step("a1", status="accepted")],
            assumptions=["A"],
            checker_feedback=[{"status": "failed"}],
            summary_state=SummaryState(),
            local_objective="fix",
        )

        assert [step.status for step in steps] == ["repaired", "failed"]
        assert steps[0].text == "fixed"
        assert len(claims) == 1
        assert claims[0].claim_id == "c1"

    def test_repair_falls_back_on_error(self):
        module = RepairModule()
        module.predict = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))

        steps, claims = module.repair(
            failed_steps=[_step(status="failed")],
            accepted_steps=[],
            assumptions=[],
            checker_feedback=[],
            summary_state=SummaryState(),
            local_objective="fix",
        )

        assert steps[0].status == "failed"
        assert claims == []


class TestAggregatorModule:
    def test_aggregate_returns_validated_trace(self):
        module = AggregatorModule()
        module.predict = lambda **_: SimpleNamespace(
            merged_trace_json='{"task_id":"t","goal":"g","steps":[]}'
        )

        trace = module.aggregate([ReasoningTrace(task_id="a", goal="b")], SummaryState())

        assert trace.task_id == "t"

    def test_aggregate_falls_back_to_most_accepted_trace(self):
        module = AggregatorModule()
        module.predict = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))
        traces = [
            ReasoningTrace(task_id="t1", goal="g", steps=[_step("s1", status="failed")]),
            ReasoningTrace(task_id="t2", goal="g", steps=[_step("s2", status="accepted")]),
        ]

        trace = module.aggregate(traces, SummaryState())

        assert trace.task_id == "t2"


class TestGateModule:
    def test_gate_returns_model_output(self):
        module = GateModule()
        module.predict = lambda **_: SimpleNamespace(
            gate_json='{"final_answer":"done","verification_status":"soft_verified"}'
        )

        result = module.gate(ReasoningTrace(task_id="t", goal="g"), SummaryState())

        assert result["final_answer"] == "done"

    def test_gate_falls_back(self):
        module = GateModule()
        module.predict = lambda **_: (_ for _ in ()).throw(RuntimeError("boom"))

        result = module.gate(
            ReasoningTrace(task_id="t", goal="g", steps=[_step(status="failed")]),
            SummaryState(),
        )

        assert result["verification_status"] == "rejected"


class TestModuleHelpers:
    def test_extract_json_accepts_wrapped_json(self):
        assert _extract_json("prefix {\"ok\": true} suffix") == {"ok": True}

    def test_extract_json_accepts_arrays(self):
        assert _extract_json("noise [1, 2, 3] end") == [1, 2, 3]

    def test_extract_json_skips_invalid_candidate_before_valid_json(self):
        payload = "prefix {not-json} then {\"ok\": true}"

        assert _extract_json(payload) == {"ok": True}

    def test_extract_json_raises_when_absent(self):
        with pytest.raises(ValueError):
            _extract_json("no json here")

    def test_stub_trace_contains_single_pending_step(self):
        trace = _stub_trace(_task())

        assert trace.steps[0].status == "pending"

    @pytest.mark.parametrize(
        ("steps", "status"),
        [
            ([ReasoningStep(step_id="s1", text="x", status="failed")], "rejected"),
            (
                [
                    ReasoningStep(step_id="s1", text="x", status="accepted"),
                    ReasoningStep(step_id="s2", text="y", status="failed"),
                ],
                "unverified",
            ),
            ([ReasoningStep(step_id="s1", text="x", status="accepted")], "soft_verified"),
        ],
    )
    def test_stub_gate_statuses(self, steps, status):
        trace = ReasoningTrace(task_id="t", goal="g", steps=steps)

        assert _stub_gate(trace)["verification_status"] == status
