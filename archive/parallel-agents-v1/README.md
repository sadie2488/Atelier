# Archived: parallel-agents setup (v1)

This is the earlier setup where each laptop ran an architect session that dispatched several expert
agents in parallel (announcements, replies, worktrees, guard hooks, Postgres action logging).
It was replaced by the two-agent setup (one Claude Code session per person) on 2026-09-26.

Renamed so Claude Code doesn't load it by accident:
- `CLAUDE.v1.md`   was the repo-root `CLAUDE.md`
- `claude-config/` was the repo-root `.claude/` folder (agents, commands, skills, hooks, scripts, settings)

To restore v1: move `claude-config/` back to `.claude/`, `CLAUDE.v1.md` back to `CLAUDE.md`, and the
other files back to the repo root. `PRD.v1.md` is the PRD as it was before the switch.

Agents: never read this folder.
