# agentic_validation skills

This directory contains the Anthropic-style skills extracted from the repository's validation workflow.

- `agentic-validation/` exposes the end-to-end trace generation, critique, formalization, checking, repair, and gating loop.
- `formal-claim-checking/` exposes the SMT and Lean formal checking conventions used by the package.

Each skill is self-contained and can be symlinked into `~/.claude/skills/` or a project-local `.claude/skills/` when you want Claude-compatible skill discovery. If your automation uses repository-local agent assets instead, point `.agents/skills/` entries at these folders with symlinks.
