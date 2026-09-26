#!/usr/bin/env python3
"""Architect tool (human-owned). Run from the lane's main checkout, on branch main.

  announce.py --from-tasks A1      draft an announcement from TASKS.md into .claude/tasks/_drafts/
  announce.py --draft <path> [--dry-run]
                                   validate, create worktree + branch, commit ANNOUNCEMENT.md
  announce.py --collect A1         check the expert's work and commit it on the task branch
  announce.py --status             every task on this laptop and in main: expert, state, merged?

Refuses when: this laptop's lane doesn't own the task, local main is behind origin/main, the
allowlist leaves the expert's scope or touches human-only paths, it overlaps an unmerged task,
a dependency's REPLY.md isn't in main yet, the contract isn't frozen (for tasks that need it),
or the draft still has [ARCHITECT: ...] placeholders.
"""
import datetime, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_scopes as cs  # noqa: E402

ROOT = cs.ROOT
DRAFTS = ROOT / ".claude" / "tasks" / "_drafts"
LANE_FILE = ROOT / ".claude" / "lane.local"
VENV_PY = ROOT.parent / "closet-venv" / "bin" / "python"
ARCHITECT_PATHS = (".claude/tasks/_drafts/", ".claude/reports/", ".claude/logs/", ".claude/lane.local")


def run(*args, cwd=None):
    r = subprocess.run(list(args), capture_output=True, text=True, cwd=cwd or ROOT)
    return r.returncode, (r.stdout + r.stderr).strip()


def lane():
    if not LANE_FILE.exists():
        sys.exit("REFUSED: this laptop has no lane. Run: echo a > .claude/lane.local   (or b)")
    v = LANE_FILE.read_text().strip().lower()
    if v not in {"a", "b"}:
        sys.exit(f"REFUSED: .claude/lane.local must contain a or b (got '{v}')")
    return v


def in_main(path):
    return run("git", "cat-file", "-e", f"main:{path}")[0] == 0


def main_text(path):
    return run("git", "show", f"main:{path}")[1]


def reply_status_in_main(task):
    p = f".claude/tasks/{task}/REPLY.md"
    return cs.parse_front_matter(main_text(p))[0].get("status", "replied") if in_main(p) else None


def agent_branches():
    _, out = run("git", "for-each-ref", "--format=%(refname:short)", "refs/heads/agent/")
    return [b for b in out.splitlines() if b.strip()]


def task_of(branch):
    return branch.split("-", 1)[1] if "-" in branch else branch


def branch_announcement(branch, task):
    code, out = run("git", "show", f"{branch}:.claude/tasks/{task}/ANNOUNCEMENT.md")
    return cs.parse_front_matter(out)[0] if code == 0 else {}


def freshness():
    """(problems, warnings) about main vs origin/main."""
    problems, warns = [], []
    if run("git", "rev-parse", "--abbrev-ref", "HEAD")[1] != "main":
        problems.append("the lane checkout must be on branch main")
    if run("git", "remote", "get-url", "origin")[0]:
        warns.append("no 'origin' remote: the other laptop can't see your merges")
        return problems, warns
    if run("git", "fetch", "-q", "origin", "main")[0]:
        warns.append("could not fetch origin/main (offline?); dependency checks use your local main")
        return problems, warns
    behind = int(run("git", "rev-list", "--count", "main..origin/main")[1] or 0)
    ahead = int(run("git", "rev-list", "--count", "origin/main..main")[1] or 0)
    if behind:
        problems.append(f"local main is {behind} commit(s) behind origin/main: a human runs `git pull --ff-only` first")
    if ahead:
        warns.append(f"local main is {ahead} commit(s) ahead of origin/main: a human should `git push` so the other laptop sees it")
    return problems, warns


def fill(text, task, wt, port):
    py = str(VENV_PY) if VENV_PY.exists() else "python3"
    return (text.replace("{WT}", str(wt)).replace("{PY}", py)
                .replace("{PORT}", str(port)).replace("{ID}", task))


def free_port():
    used = set()
    for b in agent_branches():
        p = branch_announcement(b, task_of(b)).get("port")
        if p and str(p).isdigit():
            used.add(int(p))
    return next(p for p in range(3100, 3200) if p not in used)


def draft_from_tasks(task):
    sections = cs.tasks_md_sections()
    if task not in sections:
        sys.exit(f"REFUSED: {task} is not in TASKS.md")
    sec = sections[task]
    if "HUMAN" in sec.splitlines()[0]:
        sys.exit(f"REFUSED: {task} is a HUMAN task")
    agent = cs.TASK_AGENT.get(task)
    if not agent:
        sys.exit(f"REFUSED: {task} has no expert in scopes.json task_agents")

    def field(name):
        line = next((l for l in sec.splitlines() if f"**{name}" in l), "")
        return line.split(":**", 1)[-1].strip() if line else ""

    title = re.sub(r"^###\s+\S+\s+·\s*", "", sec.splitlines()[0]).strip()
    allow = re.findall(r"`([^`]+)`", field("May edit"))
    dep_text = re.search(r"\*\*Depends on:\*\*\s*(.*?)(?:$|·)", sec, re.M)
    deps = [d.strip() for d in (dep_text.group(1) if dep_text else "").split(",") if d.strip()]
    check = re.findall(r"`([^`]+)`", field("Check"))
    fm = ["---", f"task_id: {task}", f"title: {title}", f"agent: {agent}",
          f"lane: {cs.AGENT_LANES.get(agent)}", f"depends_on: {', '.join(deps) if deps else 'none'}",
          "allowlist:"] + [f"  - {p}" for p in allow] + [
          f"approved_dependencies: {field('Approved dependenc') or 'none'}",
          f"check: {check[0] if check else 'see body'}", "port: {PORT}", "worktree: {WT}", "---", ""]
    body = (f"# ANNOUNCEMENT: {task} {title}\n\nFrom: architect (lane {cs.AGENT_LANES.get(agent)})\nTo: {agent}\n\n"
            f"## Task spec (from TASKS.md)\n\n{sec}\n\n"
            "## Context from the architect\n\n- [ARCHITECT: add the contract excerpt, prior decisions, and interfaces before announcing]\n\n"
            + WHEN_DONE)
    DRAFTS.mkdir(parents=True, exist_ok=True)
    path = DRAFTS / f"{task}.md"
    path.write_text("\n".join(fm) + body)
    print(f"draft written: {path.relative_to(ROOT)}  (fill in the architect context, then --draft it)")
    return path


WHEN_DONE = """## Working rules for this task

- Your worktree is `{WT}`. Every shell command starts with `cd {WT} &&`.
- Edit files only with the Edit/Write tools, only inside your allowlist, plus `.claude/tasks/{ID}/REPLY.md` and `.claude/tasks/{ID}/evidence/`.
- Never run git write commands (add, commit, push, merge, checkout...). The architect commits your work.
- If a build fails in files you did not edit: wait 30 seconds and retry, at most 3 times, then report.
- Read only your allowlist files and the files named under "Context from the architect". Don't explore the repo, and don't open images unless the goal says to.
- Keep output small (`-q --tb=short`, `tail -n 40`); paste only the final result lines into your REPLY. Keep the REPLY under 40 lines.

## When you're done

1. Run the check: `{CHECK}`
2. Run `cd {WT} && python3 .claude/scripts/check_scopes.py --diff {ID}` (must print OK).
3. Write `.claude/tasks/{ID}/REPLY.md` from `.claude/tasks/_templates/REPLY.md`, pasting both outputs.
4. Return to the architect with one line: `{ID} <done|blocked|failed>: see REPLY.md`.

Never contact another expert. If you need something from one, put it under **Needs** in your REPLY.
"""


def validate(fm, text, my_lane):
    problems = []
    task, agent = fm.get("task_id", ""), fm.get("agent", "")
    allow = [cs.prefix(p) for p in cs.as_list(fm.get("allowlist"))]
    if not cs.TASK_ID_RE.match(task):
        problems.append(f"bad task_id '{task}'")
    if task.startswith("T") and not task.startswith(f"T{my_lane.upper()}"):
        problems.append(f"new task IDs on this laptop must start with T{my_lane.upper()} (e.g. T{my_lane.upper()}01)")
    if agent not in cs.AGENTS or not cs.AGENTS[agent]:
        problems.append(f"'{agent}' is not an implementing expert")
    elif cs.AGENT_LANES.get(agent) != my_lane:
        problems.append(f"{agent} belongs to lane {cs.AGENT_LANES.get(agent)}; only that laptop's architect may announce to it")
    exp = cs.expected_lane(task)
    if exp not in ("any", my_lane):
        problems.append(f"{task} is a lane {exp} task")
    if not allow:
        problems.append("empty allowlist")
    for p in allow:
        if any(cs.overlaps(p, h) for h in cs.HUMAN):
            problems.append(f"allowlist '{p}' touches a human-only path")
        elif agent in cs.AGENTS and not cs.in_scope(p, cs.AGENTS[agent]):
            problems.append(f"allowlist '{p}' is outside {agent}'s scope")
    if "[ARCHITECT:" in text:
        problems.append("draft still has an [ARCHITECT: ...] placeholder; fill in the context first")
    if (cs.wt_base() / task).exists():
        problems.append(f"worktree {cs.wt_base() / task} already exists")
    if any(task_of(b) == task for b in agent_branches()):
        problems.append(f"a branch for {task} already exists")
    if reply_status_in_main(task):
        problems.append(f"{task} is already merged into main; use a new task ID")
    for b in agent_branches():
        other = task_of(b)
        if other == task or reply_status_in_main(other):
            continue  # merged tasks release their files
        theirs = [cs.prefix(p) for p in cs.as_list(branch_announcement(b, other).get("allowlist"))]
        for p in allow:
            for q in theirs:
                if cs.overlaps(p, q):
                    problems.append(f"allowlist '{p}' overlaps unmerged task {other} '{q}': announce after it's merged")
    for dep in cs.as_list(fm.get("depends_on")):
        if dep.lower() == "contract":
            if not in_main("contract/FROZEN"):
                problems.append("the contract isn't frozen yet (contract/FROZEN is not in main)")
            continue
        if not cs.TASK_ID_RE.match(dep):
            continue
        st = reply_status_in_main(dep)
        if st is None:
            problems.append(f"dependency {dep} is not merged into main (pull, or wait for it)")
        elif st != "done":
            problems.append(f"dependency {dep} was merged with status '{st}', not done")
    return problems


def announce(path, dry):
    my_lane = lane()
    text = Path(path).read_text()
    fm, _ = cs.parse_front_matter(text)
    problems, warns = freshness()
    problems += validate(fm, text, my_lane)
    for w in warns:
        print(f"WARN  {w}")
    if problems:
        print(f"REFUSED {fm.get('task_id', '?')}:")
        for p in problems:
            print(f"  - {p}")
        return 1
    task = fm["task_id"]
    wt, branch = cs.wt_base() / task, f"agent/{my_lane}-{task}"
    port = free_port()
    if dry:
        print(f"OK (dry run): would create {wt} on {branch} for {fm['agent']} (port {port})")
        return 0
    cs.wt_base().mkdir(parents=True, exist_ok=True)
    code, out = run("git", "worktree", "add", "-q", str(wt), "-b", branch, "main")
    if code:
        print(f"REFUSED: git worktree add failed:\n{out}")
        return 1
    check = fill(fm.get("check", ""), task, wt, port)
    if check and not check.startswith("cd "):
        check = f"cd {wt} && {check}"
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    final = fill(text.replace("{CHECK}", check), task, wt, port)
    final = re.sub(r"^check: .*$", f"check: {check}", final, count=1, flags=re.M)
    final = final.replace("\n---\n", f"\nannounced_at: {stamp}\n---\n", 1)
    dest = wt / ".claude" / "tasks" / task / "ANNOUNCEMENT.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(final)
    run("git", "add", str(dest.relative_to(wt)), cwd=wt)
    code, out = run("git", "commit", "-q", "-m", f"announce {task}: {fm.get('title', '')}", cwd=wt)
    if code:
        print(f"ERROR: commit failed:\n{out}")
        return 1
    print(f"ANNOUNCED {task} -> {fm['agent']}\n  worktree: {wt}\n  branch:   {branch}\n  port:     {port}\n"
          f"  dispatch: Agent(subagent_type=\"{fm['agent']}\", cwd=\"{wt}\", run_in_background=true,\n"
          f"            prompt=\"Task {task}. Your worktree is {wt}. Read .claude/tasks/{task}/ANNOUNCEMENT.md "
          f"and follow it. It has everything you need.\")")
    return 0


def collect(task):
    my_lane = lane()
    wt = cs.wt_base() / task
    branch = next((b for b in agent_branches() if task_of(b) == task), None)
    if not wt.exists() or not branch:
        print(f"REFUSED: no worktree/branch for {task} on this laptop")
        return 1
    reply = wt / ".claude" / "tasks" / task / "REPLY.md"
    if not reply.exists():
        print(f"REFUSED: {task} has no REPLY.md yet")
        return 1
    rfm = cs.parse_front_matter(reply.read_text())[0]
    code, out = run(sys.executable, str(wt / ".claude" / "scripts" / "check_scopes.py"), "--diff", task, cwd=wt)
    print(out)
    if code == 2:
        print(f"REFUSED: {task} has scope errors; nothing committed. Re-announce with fixes or ask a human.")
        return 1
    _, stray = run("git", "status", "--porcelain", "--untracked-files=all")
    stray = [l[3:] for l in stray.splitlines() if l.strip() and not l[3:].startswith(ARCHITECT_PATHS)]
    if stray:
        print("WARN  unexpected changes in the lane checkout (an expert may have written in the wrong place):")
        for s in stray:
            print(f"        {s}")
    run("git", "add", "-A", cwd=wt)
    ann = cs.parse_front_matter((wt / ".claude" / "tasks" / task / "ANNOUNCEMENT.md").read_text())[0]
    code, out = run("git", "commit", "-q", "-m",
                    f"{task}: {ann.get('title', '')} ({ann.get('agent', '?')}, {rfm.get('status', '?')})", cwd=wt)
    print(("COLLECTED " + task) if code == 0 else f"nothing new to commit for {task}")
    print(f"  status: {rfm.get('status', '?')}\n  next:   re-run the check yourself:  {ann.get('check', '?')}")
    print(f"  then:   review, and give the human:\n"
          f"            git diff main...{branch}\n            git merge --no-ff {branch}\n"
          f"            git push\n            git worktree remove {wt}\n            git branch -d {branch}")
    return 0


def status():
    rows, seen = [], set()
    for b in agent_branches():
        t = task_of(b)
        seen.add(t)
        fm = branch_announcement(b, t)
        rep = cs.wt_base() / t / ".claude" / "tasks" / t / "REPLY.md"
        st = reply_status_in_main(t)
        if st:
            state = f"merged ({st})"
        elif rep.exists():
            state = "replied: " + cs.parse_front_matter(rep.read_text())[0].get("status", "?")
        else:
            state = "open"
        rows.append((t, fm.get("agent", "?"), b, state))
    _, out = run("git", "ls-tree", "-d", "--name-only", "main", ".claude/tasks/")
    for d in out.splitlines():
        t = d.rsplit("/", 1)[-1]
        if t.startswith("_") or t in seen or not in_main(f"{d}/ANNOUNCEMENT.md"):
            continue
        fm = cs.parse_front_matter(main_text(f"{d}/ANNOUNCEMENT.md"))[0]
        rows.append((t, fm.get("agent", "?"), "(in main)", f"merged ({reply_status_in_main(t) or 'no reply'})"))
    if not rows:
        print("no announced tasks")
    for r in sorted(rows):
        print("{:<6} {:<22} {:<20} {}".format(*r))
    return 0


def main(argv):
    if "--status" in argv:
        return status()
    if "--collect" in argv:
        return collect(argv[argv.index("--collect") + 1])
    if "--from-tasks" in argv:
        lane()
        draft_from_tasks(argv[argv.index("--from-tasks") + 1])
        return 0
    if "--draft" in argv:
        return announce(argv[argv.index("--draft") + 1], "--dry-run" in argv)
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
