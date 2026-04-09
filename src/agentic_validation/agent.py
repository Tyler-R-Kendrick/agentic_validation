"""Main agent orchestration: run_agent(task) -> AgentResult.

Control-flow follows the pseudocode in the problem statement exactly:

    trace = generate_trace(task)
    trace = critique_trace_and_steps(trace)
    trace = formalize_claims(trace)
    trace = run_objective_checks(trace)

    while iteration < max_iterations:
        failing_regions = find_failing_regions(trace)
        if not failing_regions: break

        for region in failing_regions:
            candidate = repair_region(trace, region)
            candidate = critique_trace_and_steps(candidate)
            candidate = formalize_claims(candidate)
            candidate = run_objective_checks(candidate)
            if region_improved: trace = candidate

        update_summary_state(trace)

        if not repaired:
            trace = escalate(trace, max_branches)
            update_summary_state(trace)
            if unresolved_critical_failures(trace): break

        iteration += 1

    return gate_answer(trace)
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from .checkers import LeanChecker, SMTChecker
from .modules import (
    AggregatorModule,
    CriticModule,
    FormalizerModule,
    GateModule,
    GeneratorModule,
    RepairModule,
)
from .persistence import init_db, log_event, log_run_end, log_run_start
from .schemas import (
    AgentResult,
    CheckerResult,
    FormalClaim,
    ReasoningStep,
    ReasoningTrace,
    TaskInput,
)

logger = logging.getLogger(__name__)

_MAX_REPAIR_ATTEMPTS_PER_REGION = 3

# Default database path (can be overridden via environment)
_DB_PATH = Path("agentic_validation_traces.db")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_agent(task: TaskInput) -> AgentResult:
    """Execute the structured reasoning agent for *task*.

    Parameters
    ----------
    task:
        Fully-specified TaskInput describing the goal, constraints and
        resource limits.

    Returns
    -------
    AgentResult
        Structured result with verification status, accepted/failed steps,
        checker artifacts, repair history, and summary state.
    """
    run_id = str(uuid.uuid4())
    init_db(_DB_PATH)
    log_run_start(run_id, task.task_id, task, _DB_PATH)

    # Instantiate modules
    generator = GeneratorModule()
    critic = CriticModule()
    formalizer = FormalizerModule()
    smt_checker = SMTChecker()
    lean_checker = LeanChecker()
    repairer = RepairModule()
    aggregator = AggregatorModule()
    gater = GateModule()

    # Shared mutable state
    repair_history: list[dict] = []
    checker_artifacts: list[dict] = []
    repair_attempts: dict[str, int] = {}  # step_id -> count

    # -----------------------------------------------------------------------
    # Step 1: Generate initial trace
    # -----------------------------------------------------------------------
    trace = generator.forward(task)
    log_event(run_id, "trace_generated", trace.model_dump(), _DB_PATH)

    # -----------------------------------------------------------------------
    # Steps 2-4: Critique, formalize, check
    # -----------------------------------------------------------------------
    trace = _critique_all(trace, critic, run_id)
    trace = _formalize_all(trace, formalizer, task, run_id)
    trace, new_artifacts = _run_checks(trace, smt_checker, lean_checker, task, run_id)
    checker_artifacts.extend(new_artifacts)

    # -----------------------------------------------------------------------
    # Steps 5-8: Repair loop
    # -----------------------------------------------------------------------
    iteration = 0
    while iteration < task.max_iterations:
        failing_regions = _find_failing_regions(trace)
        if not failing_regions:
            break

        repaired_any = False
        for region in failing_regions:
            step_id = region.step_id
            attempt_count = repair_attempts.get(step_id, 0)
            if attempt_count >= _MAX_REPAIR_ATTEMPTS_PER_REGION:
                logger.info("Step %s exhausted repair attempts; skipping.", step_id)
                continue

            repair_attempts[step_id] = attempt_count + 1

            # Build accepted context
            accepted = [s for s in trace.steps if s.status in ("accepted", "repaired")]
            assumptions = trace.assumptions
            checker_feedback = _collect_checker_feedback(region)
            local_obj = f"Fix step '{step_id}' so that: {region.text}"

            candidate_steps, updated_claims = repairer.repair(
                failed_steps=[region],
                accepted_steps=accepted,
                assumptions=assumptions,
                checker_feedback=checker_feedback,
                summary_state=trace.summary_state,
                local_objective=local_obj,
            )

            # Build a candidate trace with the repaired step(s); splice in any
            # LM-produced updated_formal_claims so they replace stale entries.
            candidate = _splice_steps(trace, [region], candidate_steps)
            if updated_claims:
                _apply_updated_claims(candidate, updated_claims)
            candidate = _critique_all(candidate, critic, run_id)
            candidate = _formalize_all(candidate, formalizer, task, run_id)
            candidate, new_art = _run_checks(candidate, smt_checker, lean_checker, task, run_id)
            checker_artifacts.extend(new_art)

            if _region_improved(trace, candidate, region):
                record = {
                    "iteration": iteration,
                    "step_id": step_id,
                    "attempt": attempt_count + 1,
                    "before_status": region.status,
                    "after_status": _find_step(candidate, step_id),
                }
                repair_history.append(record)
                log_event(run_id, "repair_applied", record, _DB_PATH)
                trace = candidate
                repaired_any = True

        _update_summary_state(trace)
        log_event(run_id, "summary_state_updated", trace.summary_state.model_dump(), _DB_PATH)

        if not repaired_any:
            # Escalate: try to regenerate from summary state and aggregate
            trace = _escalate(
                trace,
                task,
                generator,
                critic,
                formalizer,
                smt_checker,
                lean_checker,
                aggregator,
                run_id,
            )
            _update_summary_state(trace)
            log_event(run_id, "escalation_done", trace.summary_state.model_dump(), _DB_PATH)
            if _unresolved_critical_failures(trace):
                break

        iteration += 1

    # -----------------------------------------------------------------------
    # Step 9: Final gate
    # -----------------------------------------------------------------------
    gate_result = gater.gate(trace, trace.summary_state)
    log_event(run_id, "gate_result", gate_result, _DB_PATH)

    result = AgentResult(
        task_id=task.task_id,
        final_answer=gate_result.get("final_answer"),
        verification_status=gate_result.get("verification_status", "unverified"),
        accepted_steps=[s for s in trace.steps if s.status in ("accepted", "repaired")],
        failed_steps=[s for s in trace.steps if s.status == "failed"],
        checker_artifacts=checker_artifacts,
        repair_history=repair_history,
        summary_state=trace.summary_state.model_dump(),
    )

    log_run_end(run_id, result, result.verification_status, _DB_PATH)
    return result


# ---------------------------------------------------------------------------
# Internal pipeline helpers
# ---------------------------------------------------------------------------


def _critique_all(
    trace: ReasoningTrace,
    critic: CriticModule,
    run_id: str,
) -> ReasoningTrace:
    """Run per-step critique and global trace critique; mutate trace in-place."""
    accepted_so_far: list[ReasoningStep] = []
    for step in trace.steps:
        if step.status in ("accepted", "repaired", "discarded"):
            accepted_so_far.append(step)
            continue
        labels = critic.critique_step(step, accepted_so_far, trace.assumptions)
        step.critique_labels = labels
        log_event(
            run_id,
            "step_critiqued",
            {"step_id": step.step_id, "labels": [label.model_dump() for label in labels]},
            _DB_PATH,
        )
        if any(label.severity == "high" for label in labels):
            step.status = "failed"
        elif labels:
            step.status = "pending"
        else:
            step.status = "accepted"
        # Only include this step in the context for subsequent steps if it
        # actually passed critique; failed/pending steps must not pollute the
        # accepted context used by later steps.
        if step.status in ("accepted", "repaired"):
            accepted_so_far.append(step)

    # Global critique
    global_critique = critic.critique_trace(trace)
    log_event(run_id, "trace_critiqued", global_critique, _DB_PATH)
    open_obs = global_critique.get("open_obligations", [])
    if open_obs:
        trace.summary_state.open_obligations = list(
            set(trace.summary_state.open_obligations) | set(open_obs)
        )
    return trace


def _formalize_all(
    trace: ReasoningTrace,
    formalizer: FormalizerModule,
    task: TaskInput,
    run_id: str,
) -> ReasoningTrace:
    """Create/refresh FormalClaim objects for the current set of formalizable steps.

    This re-synchronizes step-derived claims with the current trace state on
    every call so repaired or reclassified steps do not retain stale FormalClaim
    entries from earlier iterations.
    """
    current_step_ids = {step.step_id for step in trace.steps}

    # Preserve claims that are not sourced from any current step (e.g. global
    # claims added externally).
    preserved_claims = [
        fc for fc in trace.formal_claims if fc.source_step_id not in current_step_ids
    ]

    refreshed_claims: list[FormalClaim] = []
    for step in trace.steps:
        if not step.formalizable:
            continue
        claim = formalizer.formalize(step, task.goal)
        refreshed_claims.append(claim)
        log_event(run_id, "claim_formalized", claim.model_dump(), _DB_PATH)

    trace.formal_claims = preserved_claims + refreshed_claims
    return trace


def _run_checks(
    trace: ReasoningTrace,
    smt_checker: SMTChecker,
    lean_checker: LeanChecker,
    task: TaskInput,
    run_id: str,
) -> tuple[ReasoningTrace, list[dict]]:
    """Route formal claims to checkers and propagate results back to steps."""
    artifacts: list[dict] = []
    step_map = {s.step_id: s for s in trace.steps}

    # Reset previously-resolved claims that belong to repaired steps so that
    # they are re-evaluated with fresh context.
    repaired_ids = {s.step_id for s in trace.steps if s.status == "repaired"}
    for claim in trace.formal_claims:
        if claim.source_step_id in repaired_ids and claim.status in ("passed", "failed"):
            claim.status = "pending"
            # Clear stale checker results from the source step as well.
            src_step = step_map.get(claim.source_step_id)
            if src_step is not None:
                src_step.checker_results = []

    for claim in trace.formal_claims:
        if claim.status in ("passed", "failed"):
            continue  # already resolved (and not repaired)

        accepted_steps = [s for s in trace.steps if s.status in ("accepted", "repaired")]

        if claim.formalization_target == "smt" and task.require_symbolic_checking:
            result = smt_checker.check(claim, trace.assumptions, accepted_steps)
        elif claim.formalization_target == "lean" and task.require_formal_proof:
            result = lean_checker.check(claim, trace.assumptions, accepted_steps)
        else:
            result = CheckerResult(
                checker_type="rubric",
                status="unknown",
                message="No checker applicable for this claim.",
            )

        claim.status = "passed" if result.status == "passed" else (
            "failed" if result.status == "failed" else "pending"
        )
        if result.artifact_ref:
            claim.artifact_ref = result.artifact_ref

        # Propagate checker result back to the source step
        src_step = step_map.get(claim.source_step_id)
        if src_step is not None:
            src_step.checker_results.append(result)
            if result.status == "failed" and src_step.status != "failed":
                src_step.status = "failed"
            elif result.status == "passed" and src_step.status == "pending":
                src_step.status = "accepted"

        artifact = {
            "claim_id": claim.claim_id,
            "checker_type": result.checker_type,
            "status": result.status,
            "message": result.message,
            "artifact_ref": result.artifact_ref,
            "counterexample": result.counterexample,
        }
        artifacts.append(artifact)
        log_event(run_id, "checker_result", artifact, _DB_PATH)

    return trace, artifacts


# ---------------------------------------------------------------------------
# Region helpers
# ---------------------------------------------------------------------------


def _apply_updated_claims(
    trace: ReasoningTrace,
    updated_claims: list[FormalClaim],
) -> None:
    """Replace or insert FormalClaim entries based on LM-produced updates.

    For each updated claim, any existing claim with the same ``claim_id`` is
    replaced; new claim_ids are appended.
    """
    updated_by_id = {c.claim_id: c for c in updated_claims}
    trace.formal_claims = [
        updated_by_id.pop(fc.claim_id, fc) for fc in trace.formal_claims
    ]
    # Append any brand-new claims the LM produced
    trace.formal_claims.extend(updated_by_id.values())



def _find_failing_regions(trace: ReasoningTrace) -> list[ReasoningStep]:
    """Return steps that have failed or whose dependencies failed."""
    failed_ids: set[str] = set()
    failing: list[ReasoningStep] = []

    for step in trace.steps:
        dep_failed = any(dep in failed_ids for dep in step.depends_on)
        is_failed = step.status == "failed"

        if dep_failed and step.status not in ("discarded",):
            step.status = "failed"
            is_failed = True

        if is_failed:
            failed_ids.add(step.step_id)
            failing.append(step)

    return failing


def _region_improved(
    old_trace: ReasoningTrace,
    new_trace: ReasoningTrace,
    region: ReasoningStep,
) -> bool:
    """Return True if the repaired candidate is strictly better for *region*."""
    old_step = _find_step_obj(old_trace, region.step_id)
    new_step = _find_step_obj(new_trace, region.step_id)
    if old_step is None or new_step is None:
        return False
    # Improvement: old was failed, new is not
    if old_step.status == "failed" and new_step.status != "failed":
        return True
    # Improvement: fewer high-severity labels
    old_high = sum(1 for label in old_step.critique_labels if label.severity == "high")
    new_high = sum(1 for label in new_step.critique_labels if label.severity == "high")
    return new_high < old_high


def _splice_steps(
    trace: ReasoningTrace,
    old_steps: list[ReasoningStep],
    new_steps: list[ReasoningStep],
) -> ReasoningTrace:
    """Return a copy of *trace* with *old_steps* replaced by *new_steps*."""
    old_ids = {s.step_id for s in old_steps}
    result = trace.model_copy(deep=True)
    result.steps = []
    for step in trace.steps:
        if step.step_id in old_ids:
            # Insert new_steps in place of the first match, drop subsequent
            if new_steps:
                result.steps.extend(new_steps)
                new_steps = []
        else:
            result.steps.append(step.model_copy(deep=True))
    return result


def _find_step(trace: ReasoningTrace, step_id: str) -> str:
    for s in trace.steps:
        if s.step_id == step_id:
            return s.status
    return "discarded"


def _find_step_obj(trace: ReasoningTrace, step_id: str) -> ReasoningStep | None:
    for s in trace.steps:
        if s.step_id == step_id:
            return s
    return None


def _collect_checker_feedback(step: ReasoningStep) -> list[dict]:
    feedback = []
    for cr in step.checker_results:
        feedback.append(cr.model_dump())
    for cl in step.critique_labels:
        feedback.append(cl.model_dump())
    return feedback


# ---------------------------------------------------------------------------
# Summary state
# ---------------------------------------------------------------------------


def _update_summary_state(trace: ReasoningTrace) -> None:
    """Refresh the SummaryState in the trace based on current step statuses."""
    state = trace.summary_state
    state.accepted_facts = [
        s.text for s in trace.steps if s.status in ("accepted", "repaired")
    ]
    state.failed_regions = [
        s.step_id for s in trace.steps if s.status == "failed"
    ]
    # best_partial_solutions: accepted steps that have at least one passed checker
    state.best_partial_solutions = [
        s.text
        for s in trace.steps
        if s.status in ("accepted", "repaired")
        and any(cr.status == "passed" for cr in s.checker_results)
    ]


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


def _escalate(
    trace: ReasoningTrace,
    task: TaskInput,
    generator: GeneratorModule,
    critic: CriticModule,
    formalizer: FormalizerModule,
    smt_checker: SMTChecker,
    lean_checker: LeanChecker,
    aggregator: AggregatorModule,
    run_id: str,
) -> ReasoningTrace:
    """Generate up to max_branches alternative traces and aggregate them."""
    log_event(run_id, "escalation_start", {"task_id": task.task_id}, _DB_PATH)

    # Build a modified task that incorporates the current summary state as context
    context = dict(task.context)
    context["accepted_facts"] = trace.summary_state.accepted_facts
    context["failed_regions"] = trace.summary_state.failed_regions

    alt_task = task.model_copy(
        update={
            "context": context,
            "max_iterations": 1,  # prevent recursive escalation
        }
    )

    branches: list[ReasoningTrace] = [trace]  # include current as a branch
    for i in range(min(task.max_branches - 1, 3)):
        try:
            alt = generator.forward(alt_task)
            alt = _critique_all(alt, critic, run_id)
            alt = _formalize_all(alt, formalizer, alt_task, run_id)
            alt, _ = _run_checks(alt, smt_checker, lean_checker, alt_task, run_id)
            branches.append(alt)
            log_event(run_id, "branch_generated", {"branch": i, "steps": len(alt.steps)}, _DB_PATH)
        except Exception as exc:
            logger.warning("Branch %d failed: %s", i, exc)

    if len(branches) == 1:
        return trace

    merged = aggregator.aggregate(branches, trace.summary_state)
    log_event(run_id, "traces_aggregated", {"steps": len(merged.steps)}, _DB_PATH)
    return merged


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------


def _unresolved_critical_failures(trace: ReasoningTrace) -> bool:
    """True if any step has a high-severity label with no passing checker."""
    for step in trace.steps:
        if step.status != "failed":
            continue
        has_high = any(label.severity == "high" for label in step.critique_labels)
        has_pass = any(cr.status == "passed" for cr in step.checker_results)
        if has_high and not has_pass:
            return True
    return False
