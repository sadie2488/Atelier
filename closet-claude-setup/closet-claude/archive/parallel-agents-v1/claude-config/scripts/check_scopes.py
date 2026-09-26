#!/usr/bin/env python3
"""Scope checker for the closet-app agents. Human-owned.

  check_scopes.py                     static check: agent scopes overlapping each other or human-only
                                      paths, and every TASKS.md allowlist vs its agent's scope
  check_scopes.py --tasks A3 B2       can these tasks run in parallel? (announcements or TASKS.md)
  check_scopes.py --diff A3 [--base main]
                                      run inside the task's worktree: is every change in scope?

Exit codes: 0 = clean, 1 = warnings, 2 = errors.
"""
import json, re, subprocess, sys
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]
CFG = json.loads((ROOT / ".claude" / "scopes.json").read_text())
SHARED = CFG["shared_append_only"]
HUMAN = CFG["human_only"]
AGENTS = CFG["agents"]
TASK_AGENT = CFG["task_agents"]
TASK_ID_RE = re.compile(r"^[A-Z][A-Za-z0-9]{0,15}$")
AGENT_LANES = CFG["agent_lanes"]
TASK_FILES = CFG["task_files"]


def expected_lane(task):
    """Lane implied by a task ID: A*/QA*/TA* -> a, B*/QB*/TB* -> b, S* -> any."""
    for pre, lane in (("QA", "a"), ("TA", "a"), ("QB", "b"), ("TB", "b"), ("A", "a"), ("B", "b")):
        if task.startswith(pre):
            return lane
    return "any"


def task_file_ok(task, rel):
    """Experts may write only their own REPLY.md and evidence/ under .claude/tasks/<ID>/."""
    base = f".claude/tasks/{task}/"
    return rel.startswith(base) and any(rel[len(base):].startswith(f) for f in TASK_FILES)

warnings, errors = [], []


# ---------- shared helpers (also used by announce.py) ----------

def overlaps(a, b):
    return a.startswith(b) or b.startswith(a)

def is_shared(p):
    return any(p.startswith(s) for s in SHARED)

def in_scope(path, scope):
    return any(path.startswith(s) for s in scope)

def prefix(glob):
    return glob.split("*")[0]

def wt_base():
    return ROOT.parent if ROOT.parent.name == "closet-wt" else ROOT.parent / "closet-wt"

def parse_front_matter(text):
    """Tiny parser for the announcement/reply front matter (no YAML dependency)."""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    data, key = {}, None
    for line in m.group(1).splitlines():
        line = line.split("  #")[0].rstrip()
        if not line.strip():
            continue
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(item.group(1).strip())
            continue
        kv = re.match(r"^([A-Za-z_]+):\s*(.*)$", line)
        if kv:
            key, val = kv.group(1), kv.group(2).strip()
            data[key] = val if val else []
    return data, m.group(2)

def as_list(v):
    if isinstance(v, list):
        return v
    if not v or v.lower() == "none":
        return []
    return [x.strip() for x in v.split(",") if x.strip()]

def find_announcement(task):
    for c in (ROOT / ".claude" / "tasks" / task / "ANNOUNCEMENT.md",
              wt_base() / task / ".claude" / "tasks" / task / "ANNOUNCEMENT.md"):
        if c.exists():
            return c
    return None

def announcement(task):
    p = find_announcement(task)
    return parse_front_matter(p.read_text())[0] if p else None

def tasks_md_sections():
    """{task_id: section text} from TASKS.md."""
    text = (ROOT / "TASKS.md").read_text()
    out, current, buf = {}, None, []
    for line in text.splitlines():
        h = re.match(r"^###\s+([A-Z]+\d+[a-z]?)\b", line)
        if h or line.startswith("## ") or line.strip() == "---":
            if current:
                out[current] = "\n".join(buf).strip()
            current, buf = (h.group(1), [line]) if h else (None, [])
            continue
        if current:
            buf.append(line)
    if current:
        out[current] = "\n".join(buf).strip()
    return out

def tasks_md_allowlists():
    out = {}
    for tid, sec in tasks_md_sections().items():
        for line in sec.splitlines():
            if "**May edit:**" in line:
                out[tid] = [prefix(p) for p in re.findall(r"`([^`]+)`", line)]
    return out

def task_agent(task):
    ann = announcement(task)
    return ann.get("agent") if ann else TASK_AGENT.get(task)

def task_allowlist(task):
    ann = announcement(task)
    if ann:
        return [prefix(p) for p in as_list(ann.get("allowlist"))]
    return tasks_md_allowlists().get(task)


# ---------- checks ----------

def static_check():
    for (a, sa), (b, sb) in combinations(AGENTS.items(), 2):
        for p in sa:
            for q in sb:
                if overlaps(p, q) and not (is_shared(p) and is_shared(q)):
                    warnings.append(f"SCOPE OVERLAP: {a} '{p}' overlaps {b} '{q}'")
    for agent, scope in AGENTS.items():
        for p in scope:
            for h in HUMAN:
                if overlaps(p, h):
                    errors.append(f"HUMAN-ONLY CONFLICT: {agent} scope '{p}' overlaps human-only '{h}'")
    for agent in AGENTS:
        if agent not in AGENT_LANES:
            errors.append(f"NO LANE: {agent} has no entry in agent_lanes")
    for task, allow in tasks_md_allowlists().items():
        agent = TASK_AGENT.get(task)
        if agent is None:
            if not task.startswith("H"):
                warnings.append(f"UNROUTED TASK: {task} has an allowlist but no agent in task_agents")
            continue
        exp, got = expected_lane(task), AGENT_LANES.get(agent)
        if exp != "any" and got != exp:
            warnings.append(f"LANE MISMATCH: {task} implies lane {exp} but {agent} is lane {got}")
        for p in allow:
            if not in_scope(p, AGENTS[agent]) and not is_shared(p):
                warnings.append(f"TASK OUTSIDE AGENT SCOPE: {task} allows '{p}', outside {agent}'s scope")

def tasks_check(ids):
    allow = {}
    for t in ids:
        a = task_allowlist(t)
        if a is None:
            errors.append(f"UNKNOWN TASK: {t}")
        else:
            allow[t] = a
    for a, b in combinations(list(allow), 2):
        for p in allow[a]:
            for q in allow[b]:
                if overlaps(p, q) and not (is_shared(p) and is_shared(q)):
                    warnings.append(f"PARALLEL OVERLAP: {a} '{p}' overlaps {b} '{q}' -> run sequentially")

def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout

def diff_check(task, base):
    agent = task_agent(task)
    if agent is None:
        errors.append(f"UNKNOWN TASK: {task}")
        return
    ann_path = f".claude/tasks/{task}/ANNOUNCEMENT.md"
    added = git("log", "--diff-filter=A", "--format=%H", "--", ann_path).split()
    if added:
        base = added[-1]          # diff from the architect's announcement commit
    changed = git("diff", "--name-only", f"{base}..HEAD" if added else f"{base}...HEAD").split()
    for l in git("status", "--porcelain", "--untracked-files=all").splitlines():
        if l.strip():
            changed.append(l[3:].split(" -> ")[-1].strip().strip('"'))
    for f in sorted(set(changed)):
        if f.startswith(".claude/tasks/"):
            if not task_file_ok(task, f):
                errors.append(f"TASK FILE CHANGED: {f} (experts may only write .claude/tasks/{task}/REPLY.md and evidence/)")
        elif any(f.startswith(h) for h in HUMAN):
            errors.append(f"HUMAN-ONLY FILE CHANGED: {f}")
        elif is_shared(f):
            continue
        elif not in_scope(f, AGENTS.get(agent, [])):
            errors.append(f"OUT OF SCOPE: {f} is outside {agent}'s scope (task {task})")


def main(argv):
    if "--tasks" in argv:
        tasks_check(argv[argv.index("--tasks") + 1:])
    elif "--diff" in argv:
        i = argv.index("--diff")
        base = argv[argv.index("--base") + 1] if "--base" in argv else "main"
        diff_check(argv[i + 1], base)
    else:
        static_check()
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    if not warnings and not errors:
        print("OK   no scope problems")
    return 2 if errors else 1 if warnings else 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
