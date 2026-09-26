# Closet App — shared instructions for every Claude Code session and agent

A hackathon closet app: scan a face into a drawn avatar, scan the user's top into a digital closet, click **Make outfits** for a color-theory recommendation, and see the outfit on the avatar.

**Experts:** your `.claude/tasks/<ID>/ANNOUNCEMENT.md` contains everything you need. Don't read `PRD.md`, `TASKS.md`, `WORKFLOW.md`, or other tasks' folders; open `AGENT_RULES.md` only to look up a specific rule.
**Architect:** invoke the `architect` skill; it says what to read and when. **Humans:** see `WORKFLOW.md`.

## Parallel agent rules

**Multiple agents may be working simultaneously. If you see build errors in files you did NOT edit, do not try to fix them. Wait 30 seconds and retry the build - the other agent is likely mid edit.**

- Retry at most 3 times (about 90 seconds in total). If the errors persist, stop and report them with the full output; do not work around them.
- **Scopes:** each expert may edit only its scope in `.claude/scopes.json`, and only the allowlist in its announcement. Scopes never overlap, and each expert belongs to one lane, so the two laptops never edit the same files. A guard hook blocks out-of-scope edits before they happen.
- **Worktrees:** every task runs in its own git worktree at `../closet-wt/<task-id>`. Every shell command an expert runs starts with `cd <worktree> &&`. Experts edit files only with the Edit/Write tools.
- **Git:** no agent runs git write commands (add, commit, push, pull, fetch, merge, checkout, worktree, ...). Permission rules and the guard block them. The architect's `announce.py` commits announcements and collected work; humans merge and push.
- **Browser automation is never shared:** any browser an agent uses is its own fresh, isolated, headless instance (`.claude/scripts/ui_check.sh` does this). Never attach to the human's browser (including Claude in Chrome), another agent's browser, or another agent's tabs. Never log in to anything.
- **Everything is logged:** every prompt, tool call, file edit, command, web request, MCP or browser call, and post is logged with timestamps, session id, and agent id by an async hook. Never disable, edit, or bypass the hooks, and never put secrets where the log could capture them.

## Roles: architect and experts

- **Architect:** the main session of each laptop's lane (A: Scan & avatar, B: Recommend & render; the lane is in `.claude/lane.local`). Invoke the `architect` skill. Commands: `/build <what>`, `/dispatch <id>`, `/collect <id>`, `/status`, `/verify <id>`, `/review <id>`, `/rung <n>`, `/scopes`, `/dryrun`.
- **Experts:** the agents in `.claude/agents/`. Each works only from its `.claude/tasks/<ID>/ANNOUNCEMENT.md`, only in its own worktree and scope, and answers only with `.claude/tasks/<ID>/REPLY.md` (plus screenshots in `evidence/`).
- **All coordination flows through the architect.** Experts never talk to, invoke, or write to each other. What one expert needs from another goes under **Needs** in its REPLY, and the architect relays it as a new announcement. Requests for the other lane go to the humans as a handoff.
- The human approves every plan before the architect announces it, and merges and pushes every branch.
- The registry at `.claude/reports/_registry.md` records what's done. Each architect edits only its own lane's section.

## Token budget

- Read only the files named in your announcement or task, and only the parts you need (use line ranges for large files). Don't explore the repo "for context".
- Don't open images (screenshots, golden photos) unless your task says to; humans review `evidence/` screenshots.
- Keep command output small: `pytest -q --tb=short`, `tail`, `grep`; never print whole logs, lockfiles, or build output.
- When compacting, keep: the task ID, the announcement's allowlist and check, files changed, and the latest check output.

## Never

- Dispatch a HUMAN task, or announce a task by hand instead of with `announce.py`
- Announce to an expert of the other lane
- Run two tasks in parallel when `check_scopes.py --tasks` warns about an overlap
- Merge, push, pull, deploy, or touch cloud consoles or secrets
- Edit anything listed under `human_only` in `.claude/scopes.json`
- Add a chat interface or free-text LLM input
