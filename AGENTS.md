# AGENTS.md

## git usage

Always use `git mv` to rename/move files.

## agent-skills

If you make agent-skills, put them in the root skill dir (~/skills). symlink them into the "~/.agents/skills" dir.
Always make them using Anthropic's "skill-creator" skill (npx skills add https://github.com/anthropics/skills --skill skill-creator)

## Code

Always use TDD with code coverage metrics to ensure 100% coverage.
Use Playwright to visually validate your work in the browser afterwards.
Take screenshots of the outcomes and put them into your PR description so we can view the outcomes that you believe are successful.

## Scaffolding

Use project specific cli tools to scaffold instead of manually creating/editing files (dotnet, uv, npm, etc.)
