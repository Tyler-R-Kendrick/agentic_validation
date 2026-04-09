"""Pydantic schemas for the structured reasoning system."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class FormalClaim(BaseModel):
    claim_id: str
    source_step_id: str
    claim_text: str
    formalization_target: Literal["smt", "lean", "none"]
    formal_expression: str | None = None
    status: Literal["pending", "passed", "failed", "not_applicable"] = "pending"
    artifact_ref: str | None = None


class CritiqueLabel(BaseModel):
    label: Literal[
        "unsupported_inference",
        "missing_premise",
        "contradiction",
        "invalid_calculation",
        "malformed_formalization",
        "incomplete_case_analysis",
        "policy_violation",
        "unverifiable_claim",
        "irrelevant_step",
    ]
    severity: Literal["low", "medium", "high"]
    rationale: str


class CheckerResult(BaseModel):
    checker_type: Literal["rubric", "smt", "lean", "test"]
    status: Literal["passed", "failed", "unknown"]
    message: str
    artifact_ref: str | None = None
    counterexample: dict | None = None


class ReasoningStep(BaseModel):
    step_id: str
    text: str
    depends_on: list[str] = []
    evidence_refs: list[str] = []
    formalizable: bool = False
    critique_labels: list[CritiqueLabel] = []
    checker_results: list[CheckerResult] = []
    status: Literal[
        "pending",
        "accepted",
        "failed",
        "repaired",
        "discarded",
    ] = "pending"


class SummaryState(BaseModel):
    accepted_facts: list[str] = []
    open_obligations: list[str] = []
    failed_regions: list[str] = []
    best_partial_solutions: list[str] = []
    abandoned_paths: list[str] = []


class ReasoningTrace(BaseModel):
    task_id: str
    goal: str
    assumptions: list[str] = []
    steps: list[ReasoningStep] = []
    formal_claims: list[FormalClaim] = []
    summary_state: SummaryState = Field(default_factory=SummaryState)


class TaskInput(BaseModel):
    task_id: str
    goal: str
    context: dict = {}
    constraints: list[str] = []
    evidence: list[dict] = []
    require_formal_proof: bool = False
    require_symbolic_checking: bool = True
    max_iterations: int = 6
    max_branches: int = 4


class AgentResult(BaseModel):
    task_id: str
    final_answer: str | None
    verification_status: Literal[
        "hard_verified",
        "soft_verified",
        "corrected",
        "unverified",
        "rejected",
    ]
    accepted_steps: list[ReasoningStep]
    failed_steps: list[ReasoningStep]
    checker_artifacts: list[dict]
    repair_history: list[dict]
    summary_state: dict
