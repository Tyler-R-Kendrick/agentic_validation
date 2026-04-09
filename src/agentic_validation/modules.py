"""DSPy module definitions for the structured reasoning system.

Each Signature describes inputs/outputs; the corresponding Module wraps it
with a dspy.Predict (or dspy.ChainOfThought) call and parses the JSON
response into the appropriate Pydantic schema.

When no LM is configured (e.g., in tests), the modules fall back to
deterministic stub behaviour so the control-flow can be exercised without
a live model.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import dspy

from .schemas import (
    CritiqueLabel,
    FormalClaim,
    ReasoningStep,
    ReasoningTrace,
    SummaryState,
    TaskInput,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DSPy Signatures
# ---------------------------------------------------------------------------


class GenerateTrace(dspy.Signature):
    """Generate a structured reasoning trace for the task.

    Return a JSON object matching the ReasoningTrace schema:
    {
      "task_id": "...",
      "goal": "...",
      "assumptions": ["..."],
      "steps": [
        {
          "step_id": "step-1",
          "text": "...",
          "depends_on": [],
          "evidence_refs": [],
          "formalizable": false
        }
      ],
      "formal_claims": []
    }

    Rules:
    - Produce a concise structured derivation, NOT prose.
    - Enumerate all assumptions explicitly.
    - Make inter-step dependencies explicit via depends_on.
    - Avoid rhetorical filler.
    - Flag claims that need objective checking (formalizable=true).
    - Keep each step atomic and checkable.
    """

    task_description: str = dspy.InputField(desc="Full task description as JSON")
    trace_json: str = dspy.OutputField(desc="ReasoningTrace as a JSON string")


class CritiqueStep(dspy.Signature):
    """Critique one reasoning step using the allowed rubric labels.

    Return a JSON array of CritiqueLabel objects:
    [{"label": "...", "severity": "low|medium|high", "rationale": "..."}]

    Allowed labels:
      unsupported_inference, missing_premise, contradiction,
      invalid_calculation, malformed_formalization,
      incomplete_case_analysis, policy_violation,
      unverifiable_claim, irrelevant_step

    Rules:
    - Evaluate this step independently.
    - Identify the exact local failure.
    - Do NOT rewrite other steps.
    - Recommend the smallest repair span.
    - Return [] if the step is sound.
    """

    step_json: str = dspy.InputField(desc="ReasoningStep as JSON")
    context_json: str = dspy.InputField(desc="Accepted prior steps and assumptions as JSON")
    critique_json: str = dspy.OutputField(desc="JSON array of CritiqueLabel objects")


class CritiqueTrace(dspy.Signature):
    """Evaluate global consistency and unresolved obligations of the full trace.

    Return a JSON object:
    {
      "global_issues": [{"label": "...", "severity": "...", "rationale": "..."}],
      "open_obligations": ["..."]
    }
    """

    trace_json: str = dspy.InputField(desc="Full ReasoningTrace as JSON")
    global_critique_json: str = dspy.OutputField(
        desc="JSON object with global_issues and open_obligations"
    )


class FormalizeClaim(dspy.Signature):
    """Convert a formalizable reasoning step claim into SMT, Lean, or none.

    Return a JSON object:
    {
      "claim_id": "...",
      "source_step_id": "...",
      "claim_text": "...",
      "formalization_target": "smt|lean|none",
      "formal_expression": "..."
    }

    Rules:
    - Use 'smt' for arithmetic, constraints, state invariants, consistency.
    - Use 'lean' only when a formal proof structure is needed.
    - Use 'none' when the claim cannot be formalized.
    - Keep formal_expression as a compact symbolic form.
    """

    step_json: str = dspy.InputField(desc="ReasoningStep to formalize")
    goal: str = dspy.InputField(desc="Overall task goal for context")
    claim_json: str = dspy.OutputField(desc="FormalClaim as JSON")


class RepairRegion(dspy.Signature):
    """Repair only the failing local region using critique and checker feedback.

    Return a JSON object:
    {
      "repaired_steps": [...],
      "updated_formal_claims": [...],
      "local_justification": "..."
    }

    Rules:
    - Modify ONLY the failed step(s).
    - Preserve all accepted upstream steps.
    - Use checker feedback directly.
    - Do NOT invent new unsupported assumptions.
    - Prefer minimal diffs.
    - Output updated depends_on, evidence_refs as needed.
    """

    failed_steps_json: str = dspy.InputField(desc="Failed ReasoningSteps as JSON")
    accepted_context_json: str = dspy.InputField(
        desc="Accepted upstream steps and assumptions as JSON"
    )
    checker_feedback_json: str = dspy.InputField(
        desc="CheckerResult and CritiqueLabel feedback as JSON"
    )
    summary_state_json: str = dspy.InputField(desc="Current SummaryState as JSON")
    local_objective: str = dspy.InputField(desc="What the repaired region must achieve")
    repair_json: str = dspy.OutputField(desc="Repair result as JSON")


class AggregateAttempts(dspy.Signature):
    """Merge compatible validated partial traces into a better trace.

    Return a JSON object matching ReasoningTrace schema.

    Rules:
    - Merge only compatible partial solutions.
    - Preserve objectively validated segments.
    - Drop contradictory branches.
    - Never treat a merely popular step as verified.
    - Produce a new coherent trace.
    """

    partial_traces_json: str = dspy.InputField(
        desc="List of partial ReasoningTrace JSON objects"
    )
    summary_state_json: str = dspy.InputField(desc="Current SummaryState as JSON")
    merged_trace_json: str = dspy.OutputField(desc="Merged ReasoningTrace as JSON")


class GateAnswer(dspy.Signature):
    """Assign final verification status and produce the external answer.

    Return a JSON object:
    {
      "final_answer": "...",
      "verification_status": "hard_verified|soft_verified|corrected|unverified|rejected",
      "rationale": "..."
    }

    Status rules:
    - hard_verified: all critical claims passed objective checks.
    - corrected: failed regions repaired, all critical claims now pass.
    - soft_verified: no contradiction, rubric acceptable, not all objectively checked.
    - unverified: answer exists but critical gaps remain.
    - rejected: unresolved high-severity contradictions remain.
    """

    trace_json: str = dspy.InputField(desc="Final ReasoningTrace as JSON")
    summary_state_json: str = dspy.InputField(desc="Current SummaryState as JSON")
    gate_json: str = dspy.OutputField(desc="Gate result as JSON")


# ---------------------------------------------------------------------------
# DSPy Modules
# ---------------------------------------------------------------------------


class GeneratorModule(dspy.Module):
    """Generates a structured ReasoningTrace from a TaskInput."""

    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict(GenerateTrace)

    def forward(self, task: TaskInput) -> ReasoningTrace:
        task_description = json.dumps(task.model_dump(), default=str)
        try:
            result = self.predict(task_description=task_description)
            raw = _extract_json(result.trace_json)
            raw.setdefault("task_id", task.task_id)
            raw.setdefault("goal", task.goal)
            return ReasoningTrace.model_validate(raw)
        except Exception as exc:
            logger.warning("GeneratorModule fallback due to: %s", exc)
            return _stub_trace(task)


class CriticModule(dspy.Module):
    """Critiques individual steps and the global trace."""

    def __init__(self) -> None:
        super().__init__()
        self.predict_step = dspy.Predict(CritiqueStep)
        self.predict_trace = dspy.Predict(CritiqueTrace)

    def critique_step(
        self, step: ReasoningStep, accepted_steps: list[ReasoningStep], assumptions: list[str]
    ) -> list[CritiqueLabel]:
        context = {"accepted_steps": [s.model_dump() for s in accepted_steps], "assumptions": assumptions}
        try:
            result = self.predict_step(
                step_json=json.dumps(step.model_dump()),
                context_json=json.dumps(context),
            )
            raw = _extract_json(result.critique_json)
            if isinstance(raw, list):
                return [CritiqueLabel.model_validate(c) for c in raw]
            return []
        except Exception as exc:
            logger.warning("CriticModule.critique_step fallback: %s", exc)
            return []

    def critique_trace(self, trace: ReasoningTrace) -> dict:
        try:
            result = self.predict_trace(trace_json=json.dumps(trace.model_dump()))
            return _extract_json(result.global_critique_json)
        except Exception as exc:
            logger.warning("CriticModule.critique_trace fallback: %s", exc)
            return {"global_issues": [], "open_obligations": []}


class FormalizerModule(dspy.Module):
    """Converts formalizable steps into FormalClaim objects."""

    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict(FormalizeClaim)

    def formalize(self, step: ReasoningStep, goal: str) -> FormalClaim:
        try:
            result = self.predict(
                step_json=json.dumps(step.model_dump()),
                goal=goal,
            )
            raw = _extract_json(result.claim_json)
            raw.setdefault("claim_id", f"claim-{step.step_id}")
            raw.setdefault("source_step_id", step.step_id)
            raw.setdefault("claim_text", step.text)
            raw.setdefault("formalization_target", "none")
            return FormalClaim.model_validate(raw)
        except Exception as exc:
            logger.warning("FormalizerModule fallback: %s", exc)
            return FormalClaim(
                claim_id=f"claim-{step.step_id}",
                source_step_id=step.step_id,
                claim_text=step.text,
                formalization_target="none",
                status="not_applicable",
            )


class RepairModule(dspy.Module):
    """Repairs a failing region of the trace."""

    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict(RepairRegion)

    def repair(
        self,
        failed_steps: list[ReasoningStep],
        accepted_steps: list[ReasoningStep],
        assumptions: list[str],
        checker_feedback: list[Any],
        summary_state: SummaryState,
        local_objective: str,
    ) -> tuple[list[ReasoningStep], list[FormalClaim]]:
        """Repair the *failed_steps* region.

        Returns
        -------
        tuple[list[ReasoningStep], list[FormalClaim]]
            A pair of (repaired_steps, updated_formal_claims).  The caller is
            responsible for splicing the repaired steps back into the trace and
            replacing any stale FormalClaim objects with the returned ones.
        """
        accepted_context = {
            "accepted_steps": [s.model_dump() for s in accepted_steps],
            "assumptions": assumptions,
        }
        try:
            result = self.predict(
                failed_steps_json=json.dumps([s.model_dump() for s in failed_steps]),
                accepted_context_json=json.dumps(accepted_context),
                checker_feedback_json=json.dumps(checker_feedback, default=str),
                summary_state_json=json.dumps(summary_state.model_dump()),
                local_objective=local_objective,
            )
            raw = _extract_json(result.repair_json)
            repaired_raw = raw.get("repaired_steps", [])
            steps = []
            for orig, rep in zip(failed_steps, repaired_raw):
                merged = orig.model_dump()
                merged.update(rep)
                merged["status"] = "repaired"
                steps.append(ReasoningStep.model_validate(merged))
            # Preserve original (still-failed) steps if the LM returned fewer
            for orig in failed_steps[len(repaired_raw):]:
                d = orig.model_dump()
                d["status"] = "failed"
                steps.append(ReasoningStep.model_validate(d))

            # Consume updated_formal_claims if the LM produced any
            claims: list[FormalClaim] = []
            for raw_claim in raw.get("updated_formal_claims", []):
                try:
                    claims.append(FormalClaim.model_validate(raw_claim))
                except Exception as claim_exc:
                    logger.debug("Skipping malformed updated_formal_claim: %s", claim_exc)

            return steps, claims
        except Exception as exc:
            logger.warning("RepairModule fallback: %s", exc)
            result_steps = []
            for s in failed_steps:
                d = s.model_dump()
                d["status"] = "failed"
                result_steps.append(ReasoningStep.model_validate(d))
            return result_steps, []


class AggregatorModule(dspy.Module):
    """Merges compatible partial traces into a better trace."""

    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict(AggregateAttempts)

    def aggregate(
        self, partial_traces: list[ReasoningTrace], summary_state: SummaryState
    ) -> ReasoningTrace:
        try:
            result = self.predict(
                partial_traces_json=json.dumps(
                    [t.model_dump() for t in partial_traces]
                ),
                summary_state_json=json.dumps(summary_state.model_dump()),
            )
            raw = _extract_json(result.merged_trace_json)
            return ReasoningTrace.model_validate(raw)
        except Exception as exc:
            logger.warning("AggregatorModule fallback: %s", exc)
            # Return the trace with the most accepted steps
            return max(
                partial_traces,
                key=lambda t: sum(1 for s in t.steps if s.status == "accepted"),
                default=partial_traces[0],
            )


class GateModule(dspy.Module):
    """Assigns the final verification status."""

    def __init__(self) -> None:
        super().__init__()
        self.predict = dspy.Predict(GateAnswer)

    def gate(self, trace: ReasoningTrace, summary_state: SummaryState) -> dict:
        try:
            result = self.predict(
                trace_json=json.dumps(trace.model_dump()),
                summary_state_json=json.dumps(summary_state.model_dump()),
            )
            return _extract_json(result.gate_json)
        except Exception as exc:
            logger.warning("GateModule fallback: %s", exc)
            return _stub_gate(trace)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_json(raw: str) -> Any:
    """Extract the first valid JSON value from a (possibly prose-wrapped) string.

    Uses ``JSONDecoder.raw_decode`` starting at the first ``{`` or ``[`` so
    that only the first complete JSON value is consumed, even when the model
    output contains multiple objects or trailing prose.
    """
    raw = raw.strip()
    # Try direct parse first (fast path for clean output)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for idx, char in enumerate(raw):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(raw, idx)
            return value
        except json.JSONDecodeError:
            continue

    raise ValueError(f"No JSON found in: {raw!r}")


def _stub_trace(task: TaskInput) -> ReasoningTrace:
    """Return a minimal plausible trace without an LM."""
    return ReasoningTrace(
        task_id=task.task_id,
        goal=task.goal,
        assumptions=[f"No LM configured; stub trace for task {task.task_id}"],
        steps=[
            ReasoningStep(
                step_id="step-1",
                text=f"Stub derivation for goal: {task.goal}",
                formalizable=False,
                status="pending",
            )
        ],
    )


def _stub_gate(trace: ReasoningTrace) -> dict:
    """Return a conservative gate result without an LM."""
    all_steps = trace.steps
    has_failed = any(s.status == "failed" for s in all_steps)
    has_accepted = any(s.status in ("accepted", "repaired") for s in all_steps)
    if has_failed and not has_accepted:
        status = "rejected"
    elif has_failed:
        status = "unverified"
    else:
        status = "soft_verified"
    return {
        "final_answer": trace.goal,
        "verification_status": status,
        "rationale": "Stub gate: no LM configured.",
    }
