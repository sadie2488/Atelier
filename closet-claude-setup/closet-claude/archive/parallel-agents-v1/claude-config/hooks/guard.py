#!/usr/bin/env python3
"""PreToolUse guard (human-owned). Fast, local, no network. Exit 2 blocks the tool call and
shows the reason to Claude. Blocks, before they happen:

  - git write commands from any Claude session (backup to the permission deny rules)
  - an expert editing outside its task worktree, its scope, its announcement's allowlist,
    or anyone else's task files
  - test-runner / code-reviewer editing anything except their own report folder
  - any other subagent type editing files
  - the architect (main thread) editing inside a task worktree

Subagents are identified by agent_id / agent_type, which Claude Code adds to hook input
inside subagents. Internal errors allow the call; the final scope diff is the backstop.
"""
import json, os, re, sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
WT_RE = re.compile(r"/closet-wt/([^/]+)/")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
GIT_WRITE = re.compile(
    r"\bgit\s+(?:-[cC]\s+\S+\s+)*"
    r"(push|pull|fetch|merge(?!-base)|rebase|commit|add|reset|checkout|switch|restore|stash|"
    r"cherry-pick|revert|am|tag|clean|rm|mv|worktree|update-ref|"
    r"branch\s+(?:-[dDmMfc]\b|--delete|--force|--move|--copy))\b")
REPORT_DIRS = {"test-runner": ".claude/reports/tests/", "code-reviewer": ".claude/reports/review/"}


def block(msg):
    print(f"BLOCKED by guard: {msg}", file=sys.stderr)
    sys.exit(2)


def front_matter(path):
    try:
        text = path.read_text()
    except OSError:
        return {}
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    data, key = {}, None
    for line in (m.group(1).splitlines() if m else []):
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            data.setdefault(key, []).append(item.group(1).strip())
            continue
        kv = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if kv:
            key = kv.group(1)
            data[key] = kv.group(2).strip() or []
    return data


def main():
    d = json.load(sys.stdin)
    tool = d.get("tool_name", "")
    ti = d.get("tool_input") or {}
    agent_type = d.get("agent_type")
    is_sub = bool(d.get("agent_id"))

    if tool == "Bash":
        if GIT_WRITE.search(ti.get("command", "") or ""):
            block("agents never run git write commands (add, commit, push, pull, fetch, merge, "
                  "checkout, worktree, ...). The architect uses announce.py; humans merge and push.")
        return 0

    if tool not in EDIT_TOOLS:
        return 0
    raw = ti.get("file_path") or ti.get("notebook_path") or ""
    path = os.path.normpath(os.path.join(d.get("cwd") or str(ROOT), raw)).replace("\\", "/")
    m = WT_RE.search(path + ("/" if not path.endswith("/") else ""))
    in_wt = m is not None and path.find(f"/closet-wt/{m.group(1)}/") >= 0

    if not is_sub:
        if in_wt:
            block("the architect never edits inside a task worktree. Announce a task (or re-announce with "
                  "fixes) instead of implementing it yourself.")
        return 0

    cfg = json.loads((ROOT / ".claude" / "scopes.json").read_text())
    if agent_type in REPORT_DIRS:
        rel = path.split(f"/closet-wt/{m.group(1)}/", 1)[1] if in_wt else os.path.relpath(path, ROOT)
        if not rel.startswith(REPORT_DIRS[agent_type]):
            block(f"{agent_type} may only write its own report under {REPORT_DIRS[agent_type]}")
        return 0
    if agent_type not in cfg["agents"]:
        block(f"subagent type '{agent_type}' may not edit files; only the named experts may")
    if not in_wt:
        block(f"edit only inside your task worktree (../closet-wt/<ID>/), not {path}")

    task = m.group(1)
    wt = Path(path.split(f"/closet-wt/{task}/", 1)[0] + f"/closet-wt/{task}")
    rel = path.split(f"/closet-wt/{task}/", 1)[1]
    cwd_m = WT_RE.search((d.get("cwd") or "") + "/")
    if cwd_m and cwd_m.group(1) != task:
        block(f"you are working on task {cwd_m.group(1)}; {path} belongs to task {task}")

    ann = front_matter(wt / ".claude" / "tasks" / task / "ANNOUNCEMENT.md")
    if ann.get("agent") and ann["agent"] != agent_type:
        block(f"task {task} is assigned to {ann['agent']}, not {agent_type}")

    base = f".claude/tasks/{task}/"
    if rel.startswith(".claude/"):
        if rel.startswith(base) and any(rel[len(base):].startswith(f) for f in cfg["task_files"]):
            return 0
        block(f"experts may write only {base}REPLY.md and {base}evidence/ under .claude/")
    if any(rel.startswith(h) for h in cfg["human_only"]):
        block(f"{rel} is human-owned")
    if not any(rel.startswith(s) for s in cfg["agents"][agent_type]):
        block(f"{rel} is outside {agent_type}'s scope (.claude/scopes.json)")
    allow = ann.get("allowlist") or []
    if isinstance(allow, list) and allow and not any(rel.startswith(a.split("*")[0]) for a in allow):
        block(f"{rel} is inside your scope but not in task {task}'s allowlist")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
