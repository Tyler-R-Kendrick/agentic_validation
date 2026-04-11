# agentic_validation skills

This directory contains the repository's Anthropic-style `validate` skill.

- `validate/` merges the end-to-end reasoning-validation workflow with the SMT and Lean claim-checking guidance used by the package.

The skill is self-contained and can be symlinked into `~/.claude/skills/` or a project-local `.claude/skills/` when you want Claude-compatible skill discovery. If your automation uses repository-local agent assets instead, point `.agents/skills/` entries at this folder with a symlink.
